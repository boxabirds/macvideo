#!/usr/bin/env python
"""Separate a song into a vocals stem for the editor audio-transcribe pipeline.

The editor calls this wrapper with:

    demucs_separate.py --audio music/song.wav --out outputs/song/vocals.wav

Demucs writes stems under <work>/htdemucs_6s/<song-stem>/vocals.wav. This
wrapper keeps that implementation detail out of the editor pipeline and copies
the vocals stem to the exact path requested by the caller.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_MODEL = "htdemucs_6s"


def _find_vocals(work_dir: Path, model: str, audio: Path) -> Path:
    expected = work_dir / model / audio.stem / "vocals.wav"
    if expected.exists():
        return expected

    matches = sorted((work_dir / model).glob("*/vocals.wav"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"demucs completed but produced no vocals.wav under {work_dir / model}"
        )
    raise RuntimeError(
        "demucs produced multiple vocals.wav candidates: "
        + ", ".join(str(p) for p in matches)
    )


def separate_vocals(audio: Path, out: Path, *, model: str = DEFAULT_MODEL) -> None:
    if not audio.exists():
        raise FileNotFoundError(f"audio not found at {audio}")

    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="macvideo-demucs-") as tmp:
        work_dir = Path(tmp)
        cmd = [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            model,
            str(audio),
            "-o",
            str(work_dir),
        ]
        subprocess.run(cmd, check=True)
        vocals = _find_vocals(work_dir, model, audio)
        shutil.copyfile(vocals, out)

    print(f"[demucs] wrote {out}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)

    try:
        separate_vocals(args.audio, args.out, model=args.model)
    except Exception as exc:  # noqa: BLE001
        print(f"[demucs] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
