"""Shared result contract for queued product stage handlers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StageResult:
    ok: bool
    returncode: int
    new_keyframes: int
    new_prompts: int
    stdout_tail: str
    stderr_tail: str
    duration_s: float
