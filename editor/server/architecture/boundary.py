"""Static checks for forbidden experiment-code references in product files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FORBIDDEN_TOKENS = (
    "po" + "cs/",
    "po" + "cs/29-full-song",
    "poc_" + "scripts_root",
    "gen_" + "keyframes.py",
    "render_" + "clips.py",
    "make_" + "shots.py",
    "whisperx_" + "align.py",
)

RUNTIME_ROOTS = (
    Path("editor/server"),
    Path("editor/web/src"),
    Path("editor/server/tests"),
    Path("editor/web/tests"),
)

SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "architecture",
    "node_modules",
    "dist",
    "test-results",
    "fixtures",
}

SKIP_SUFFIXES = (
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".wav",
    ".mp3",
    ".mp4",
    ".sqlite",
    ".db",
)

TEST_NAME_MARKERS = (
    ".test.",
    ".spec.",
)


@dataclass(frozen=True)
class BoundaryViolation:
    path: str
    line: int
    token: str
    reason: str


def _repo_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_runtime_file(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if path.suffix in SKIP_SUFFIXES:
        return False
    if any(marker in path.name for marker in TEST_NAME_MARKERS):
        return False
    return path.is_file()


def _iter_runtime_files(root: Path) -> Iterable[Path]:
    for runtime_root in RUNTIME_ROOTS:
        base = root / runtime_root
        if not base.exists():
            continue
        yield from (p for p in base.rglob("*") if _is_runtime_file(p))


def scan_runtime_boundaries(root: Path) -> list[BoundaryViolation]:
    """Return forbidden product references."""
    root = root.resolve()
    violations: list[BoundaryViolation] = []

    for path in _iter_runtime_files(root):
        rel = _repo_relative(root, path)
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as exc:
            violations.append(BoundaryViolation(
                path=rel,
                line=0,
                token="<unreadable>",
                reason=f"runtime file is unreadable: {exc}",
            ))
            continue

        for line_no, line in enumerate(lines, start=1):
            for token in FORBIDDEN_TOKENS:
                if token not in line:
                    continue
                violations.append(BoundaryViolation(
                    path=rel,
                    line=line_no,
                    token=token,
                    reason="forbidden experiment-code reference in product code or tests",
                ))

    return violations
