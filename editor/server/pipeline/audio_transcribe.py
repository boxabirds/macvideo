"""Story 18: audio-only transcription pipeline (Demucs → WhisperX → segments).

Demucs → WhisperX → return timestamped segments. Scene insertion happens in
api/audio_transcribe.py _orchestrate().

Story 18 eliminates the lyrics.txt intermediate file entirely. WhisperX emits
JSON with timestamped segments; _orchestrate consumes them and inserts scene
rows into the DB directly. The forced-alignment stage is no longer used.

Three phases run sequentially:
  1. Demucs separates vocals from the song into a vocals.wav stem.
  2. WhisperX transcribes the vocals stem to JSON with segments.
  3. Segments are returned to the caller for DB insertion.

Tests inject fake subprocess scripts via EDITOR_FAKE_DEMUCS and
EDITOR_FAKE_WHISPERX_TRANSCRIBE so the suite runs in seconds.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .paths import SongPaths
from .subprocess_runner import RunResult, cancel_run, run_script


# ---------- public types ----------------------------------------------------

PHASE_SEPARATING_VOCALS = "separating-vocals"
PHASE_TRANSCRIBING = "transcribing"

ProgressCb = Callable[[str, float], None]


@dataclass
class AudioTranscribeResult:
    ok: bool
    cancelled: bool = False
    returncode: int = 0
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0
    phase_durations: dict[str, float] = field(default_factory=dict)
    segments: list[dict[str, Any]] = field(default_factory=list)
    failing_phase: Optional[str] = None


# ---------- internals -------------------------------------------------------

_CANCEL_POLL_S = 0.05
_TAIL_BYTES = 4000


def _tail(s: str, n: int = _TAIL_BYTES) -> str:
    return s if len(s) <= n else s[-n:]


def _start_cancel_watcher(
    cancel_event: threading.Event, run_id: int, stop: threading.Event,
) -> threading.Thread:
    """Translate the cancel_event API into the existing SIGTERM machinery in
    subprocess_runner. Polls every _CANCEL_POLL_S; when cancel fires, calls
    cancel_run(run_id) which terminates the registered subprocess.
    """
    def _watch() -> None:
        while not stop.is_set():
            if cancel_event.is_set():
                cancel_run(run_id)
                return
            time.sleep(_CANCEL_POLL_S)
    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t


def _run_phase(
    *, script: Path, args: list[str], run_id: int,
    cancel_event: threading.Event,
) -> RunResult:
    stop = threading.Event()
    watcher = _start_cancel_watcher(cancel_event, run_id, stop)
    try:
        return run_script(script, args, run_id=run_id)
    finally:
        stop.set()
        watcher.join(timeout=1.0)


def _resolve_demucs_script() -> Path:
    """Test path: EDITOR_FAKE_DEMUCS points at a fake script. Production
    path: a thin shell that invokes `python -m demucs ...` lives at
    editor/server/pipeline/scripts/demucs_separate.py.
    """
    fake = os.environ.get("EDITOR_FAKE_DEMUCS")
    if fake:
        return Path(fake)
    here = Path(__file__).resolve()
    return here.parent / "scripts" / "demucs_separate.py"


def _resolve_whisperx_script() -> Path:
    """Test path: EDITOR_FAKE_WHISPERX_TRANSCRIBE. Production: the POC 30
    transcribe script.
    """
    fake = os.environ.get("EDITOR_FAKE_WHISPERX_TRANSCRIBE")
    if fake:
        return Path(fake)
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    return (repo_root / "pocs" / "30-whisper-timestamped"
            / "scripts" / "transcribe_whisperx_noprompt.py")


# ---------- public API ------------------------------------------------------

def run_audio_transcribe(
    *, slug: str, paths: SongPaths, run_id: int, force: bool,
    progress_cb: Optional[ProgressCb] = None,
    cancel_event: Optional[threading.Event] = None,
) -> AudioTranscribeResult:
    """Run Demucs + WhisperX, then write the transcript to the lyrics path.

    Cancel discipline:
      - Pre-phase: if cancel_event is set on entry, no subprocess spawns.
      - Mid-phase: a watcher thread translates cancel_event → cancel_run() →
        SIGTERM on the registered subprocess (subprocess_runner already
        registers each invocation under run_id).
      - Post-success-pre-write: if cancel_event fires AFTER WhisperX exited
        ok but BEFORE the lyrics write, the lyrics file is NOT written —
        cancel takes priority over commit.

    Partial files (vocals.wav under the run dir, the temp transcript) are
    removed on cancellation. The canonical lyrics path is only ever written
    via os.replace from a temp file inside the music dir, so a partial write
    cannot leave a corrupt lyrics file.
    """
    cancel_event = cancel_event or threading.Event()
    started = time.time()
    phase_durations: dict[str, float] = {}
    cb = progress_cb or (lambda _phase, _pct: None)

    if not paths.music_wav.exists():
        return AudioTranscribeResult(
            ok=False, returncode=126,
            stderr_tail=f"audio not found at {paths.music_wav}",
            duration_s=time.time() - started,
            failing_phase="preflight",
        )
    if cancel_event.is_set():
        return AudioTranscribeResult(
            ok=True, cancelled=True,
            duration_s=time.time() - started,
        )

    paths.run_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = paths.run_dir / "vocals.wav"
    # Clean up a stale partial vocals from a prior cancelled run.
    if vocals_path.exists() and force:
        vocals_path.unlink(missing_ok=True)

    # ---------- phase 1: Demucs vocals separation ---------------------------
    demucs_script = _resolve_demucs_script()
    if not demucs_script.exists():
        return AudioTranscribeResult(
            ok=False, returncode=126,
            stderr_tail=f"demucs script not found at {demucs_script}",
            duration_s=time.time() - started,
            failing_phase=PHASE_SEPARATING_VOCALS,
        )
    cb(PHASE_SEPARATING_VOCALS, 0.0)
    p1_start = time.time()
    demucs_result = _run_phase(
        script=demucs_script,
        args=["--audio", str(paths.music_wav), "--out", str(vocals_path)],
        run_id=run_id,
        cancel_event=cancel_event,
    )
    phase_durations[PHASE_SEPARATING_VOCALS] = time.time() - p1_start
    if cancel_event.is_set():
        vocals_path.unlink(missing_ok=True)
        return AudioTranscribeResult(
            ok=True, cancelled=True,
            stdout_tail=_tail(demucs_result.stdout),
            stderr_tail=_tail(demucs_result.stderr),
            duration_s=time.time() - started,
            phase_durations=phase_durations,
        )
    if not demucs_result.ok:
        vocals_path.unlink(missing_ok=True)
        return AudioTranscribeResult(
            ok=False, returncode=demucs_result.returncode,
            stdout_tail=_tail(demucs_result.stdout),
            stderr_tail=_tail(demucs_result.stderr) or
                        f"demucs failed (code {demucs_result.returncode})",
            duration_s=time.time() - started,
            phase_durations=phase_durations,
            failing_phase=PHASE_SEPARATING_VOCALS,
        )

    # ---------- phase 2: WhisperX transcription (JSON with segments) --------
    wx_script = _resolve_whisperx_script()
    if not wx_script.exists():
        return AudioTranscribeResult(
            ok=False, returncode=126,
            stderr_tail=f"whisperx transcribe script not found at {wx_script}",
            duration_s=time.time() - started,
            phase_durations=phase_durations,
            failing_phase=PHASE_TRANSCRIBING,
        )
    cb(PHASE_TRANSCRIBING, 0.0)
    tmp_dir = Path(tempfile.mkdtemp(prefix="audio-transcribe-", dir=str(paths.run_dir)))
    tmp_json = tmp_dir / f"{slug}.segments.json"
    p2_start = time.time()
    wx_result = _run_phase(
        script=wx_script,
        args=["--audio", str(vocals_path), "--out", str(tmp_json)],
        run_id=run_id,
        cancel_event=cancel_event,
    )
    phase_durations[PHASE_TRANSCRIBING] = time.time() - p2_start
    if cancel_event.is_set():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return AudioTranscribeResult(
            ok=True, cancelled=True,
            stdout_tail=_tail(wx_result.stdout),
            stderr_tail=_tail(wx_result.stderr),
            duration_s=time.time() - started,
            phase_durations=phase_durations,
        )
    if not wx_result.ok:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return AudioTranscribeResult(
            ok=False, returncode=wx_result.returncode,
            stdout_tail=_tail(wx_result.stdout),
            stderr_tail=_tail(wx_result.stderr) or
                        f"whisperx transcribe failed (code {wx_result.returncode})",
            duration_s=time.time() - started,
            phase_durations=phase_durations,
            failing_phase=PHASE_TRANSCRIBING,
        )
    if not tmp_json.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return AudioTranscribeResult(
            ok=False, returncode=126,
            stderr_tail=f"whisperx exited ok but produced no json at {tmp_json}",
            duration_s=time.time() - started,
            phase_durations=phase_durations,
            failing_phase=PHASE_TRANSCRIBING,
        )

    # Parse the JSON to extract segments.
    try:
        payload = json.loads(tmp_json.read_text())
        segments = payload.get("segments", [])
        if not segments:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return AudioTranscribeResult(
                ok=False, returncode=126,
                stderr_tail="whisperx produced json but no segments",
                duration_s=time.time() - started,
                phase_durations=phase_durations,
                failing_phase=PHASE_TRANSCRIBING,
            )
    except (json.JSONDecodeError, KeyError) as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return AudioTranscribeResult(
            ok=False, returncode=126,
            stderr_tail=f"failed to parse whisperx json: {e}",
            duration_s=time.time() - started,
            phase_durations=phase_durations,
            failing_phase=PHASE_TRANSCRIBING,
        )

    if cancel_event.is_set():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return AudioTranscribeResult(
            ok=True, cancelled=True,
            stdout_tail=_tail(wx_result.stdout),
            stderr_tail=_tail(wx_result.stderr),
            duration_s=time.time() - started,
            phase_durations=phase_durations,
        )

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return AudioTranscribeResult(
        ok=True,
        stdout_tail=_tail(wx_result.stdout),
        stderr_tail=_tail(wx_result.stderr),
        duration_s=time.time() - started,
        phase_durations=phase_durations,
        segments=segments,
    )
