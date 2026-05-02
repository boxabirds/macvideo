"""Common subprocess wrapper for product pipeline adapters.

The wrapper streams stdout, matches known progress patterns, and pumps a
progress callback so the editor can update DB state or emit SSE events while
the subprocess is still running.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ---------- progress parsing ------------------------------------------------

# Matches product adapter progress lines so the editor can attribute each line
# to a stage or scene.
_RE_PASS_A_DONE = re.compile(r"^\[Pass A\]\s+(?:cached|\d+(?:\.\d+)?s)")
_RE_PASS_C_DONE = re.compile(r"^\[Pass C\]\s+(?:cached|\d+(?:\.\d+)?s)")
_RE_PASS_B = re.compile(r"^\[shot\s+(\d+)\]\s+Pass B")
_RE_KEYFRAME_DONE = re.compile(r"^\[shot\s+(\d+)\]\s+keyframe")
_RE_CLIP_DONE = re.compile(r"^\[shot\s+(\d+)\]\s+clip OK")
_RE_CLIP_FAIL = re.compile(r"^\[shot\s+(\d+)\]\s+clip FAILED")
_RE_ALIGN = re.compile(r"^\[align\]\s+(\d+)%")
_RE_DONE = re.compile(r"^\[done\]")


@dataclass
class ProgressEvent:
    kind: str  # 'pass_a_done' | 'pass_c_done' | 'pass_b' | 'keyframe_done' | 'clip_done' | 'clip_failed' | 'progress' | 'done' | 'line'
    scene_index: Optional[int] = None
    progress_pct: Optional[int] = None
    raw: str = ""


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    events: list[ProgressEvent] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def parse_line(line: str) -> ProgressEvent:
    stripped = line.rstrip()
    if _RE_PASS_A_DONE.match(stripped):
        return ProgressEvent(kind="pass_a_done", raw=stripped)
    if _RE_PASS_C_DONE.match(stripped):
        return ProgressEvent(kind="pass_c_done", raw=stripped)
    m = _RE_PASS_B.match(stripped)
    if m:
        return ProgressEvent(kind="pass_b", scene_index=int(m.group(1)), raw=stripped)
    m = _RE_KEYFRAME_DONE.match(stripped)
    if m:
        return ProgressEvent(kind="keyframe_done", scene_index=int(m.group(1)), raw=stripped)
    m = _RE_CLIP_DONE.match(stripped)
    if m:
        return ProgressEvent(kind="clip_done", scene_index=int(m.group(1)), raw=stripped)
    m = _RE_CLIP_FAIL.match(stripped)
    if m:
        return ProgressEvent(kind="clip_failed", scene_index=int(m.group(1)), raw=stripped)
    m = _RE_ALIGN.match(stripped)
    if m:
        return ProgressEvent(kind="progress", progress_pct=int(m.group(1)), raw=stripped)
    if _RE_DONE.match(stripped):
        return ProgressEvent(kind="done", raw=stripped)
    return ProgressEvent(kind="line", raw=stripped)


# ---------- subprocess driver -----------------------------------------------

# Registry of running subprocesses keyed by source_run_id so the cancel
# endpoint can SIGTERM the right process. Populated on subprocess spawn,
# cleared on exit.
_RUN_PROCS: dict[int, subprocess.Popen] = {}


def cancel_run(run_id: int) -> bool:
    """SIGTERM the subprocess for a given regen_run_id. Escalates to SIGKILL
    after 2 seconds if the process is still alive. Returns True if a process
    was signalled.
    """
    proc = _RUN_PROCS.get(run_id)
    if proc is None or proc.poll() is not None:
        return False
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
    except Exception:
        return False
    return True


def run_script(
    script_path: Path,
    args: list[str],
    *,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
    timeout_s: Optional[float] = None,
    progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    python_bin: Optional[str] = None,
    run_id: Optional[int] = None,
) -> RunResult:
    """Run a Python script with progress parsing.

    `script_path` is executed under `python_bin` (defaults to sys.executable).
    Stdout is streamed in real time; each line is parsed via `parse_line` and
    forwarded to `progress_cb`. Stderr is captured as a single string.

    Raises `subprocess.TimeoutExpired` on timeout. Does NOT raise on non-zero
    exit; caller should check `result.ok`.
    """
    py = python_bin or sys.executable
    full_cmd = [py, str(script_path), *args]
    merged_env = {**os.environ, **(env or {})}

    start = time.time()
    stdout_lines: list[str] = []
    stderr_chunks: list[str] = []
    events: list[ProgressEvent] = []

    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        cwd=str(cwd) if cwd else None,
        text=True,
        bufsize=1,  # line-buffered
    )
    if run_id is not None:
        _RUN_PROCS[run_id] = proc

    def _pump_stderr() -> None:
        assert proc.stderr is not None
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_pump_stderr, daemon=True)
    stderr_thread.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line)
            event = parse_line(line)
            events.append(event)
            if progress_cb is not None:
                try:
                    progress_cb(event)
                except Exception as cb_err:  # noqa: BLE001
                    # A failing callback must not kill the subprocess — just
                    # log it to stderr and keep draining.
                    print(f"[subprocess_runner] progress callback failed: {cb_err}",
                          file=sys.stderr)
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        stderr_thread.join(timeout=2.0)
        if run_id is not None:
            _RUN_PROCS.pop(run_id, None)

    return RunResult(
        returncode=returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_chunks),
        events=events,
        duration_s=time.time() - start,
    )


def format_command(script_path: Path, args: list[str]) -> str:
    """Quote for human display — used in error messages + logs."""
    return " ".join(shlex.quote(s) for s in [str(script_path), *args])
