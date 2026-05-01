"""Static checks for product runtime references to temporary legacy code."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FORBIDDEN_TOKENS = (
    "pocs/",
    "pocs/29-full-song",
    "poc_scripts_root",
    "gen_keyframes.py",
    "render_clips.py",
    "make_shots.py",
    "whisperx_align.py",
    "shots.json",
    "character_brief.json",
    "storyboard.json",
    "image_prompts.json",
)

RUNTIME_ROOTS = (
    Path("editor/server"),
    Path("editor/web/src"),
)

SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "architecture",
    "node_modules",
    "dist",
    "test-results",
    "tests",
    "fixtures",
    "fake_scripts",
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
class LegacyInventoryEntry:
    path: str
    owner_story: int
    workflow: str
    reason_remaining: str
    removal_condition: str


@dataclass(frozen=True)
class BoundaryViolation:
    path: str
    line: int
    token: str
    reason: str
    inventoried: bool = False
    owner_story: int | None = None
    removal_condition: str | None = None


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


def _load_inventory(root: Path) -> dict[str, LegacyInventoryEntry]:
    path = root / "docs" / "architecture" / "temporary-legacy-dependencies.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    entries: dict[str, LegacyInventoryEntry] = {}
    for raw in payload.get("entries", []):
        entries[raw["path"]] = _entry_from_payload(raw)
    return entries


def _entry_from_payload(raw: dict[str, Any]) -> LegacyInventoryEntry:
    return LegacyInventoryEntry(
        path=str(raw.get("path", "")),
        owner_story=int(raw.get("owner_story", 0)),
        workflow=str(raw.get("workflow", "")),
        reason_remaining=str(raw.get("reason_remaining", "")),
        removal_condition=str(raw.get("removal_condition", "")),
    )


def _entry_is_complete(entry: LegacyInventoryEntry) -> bool:
    return (
        bool(entry.path)
        and entry.owner_story > 0
        and bool(entry.workflow.strip())
        and bool(entry.reason_remaining.strip())
        and bool(entry.removal_condition.strip())
    )


def scan_runtime_boundaries(root: Path) -> list[BoundaryViolation]:
    """Return forbidden runtime references not covered by the inventory.

    The scanner is intentionally plain text. Story 26 is a guardrail, not a
    parser: the goal is to make every remaining legacy reference visible and
    owned until later stories delete it.
    """
    root = root.resolve()
    inventory = _load_inventory(root)
    violations: list[BoundaryViolation] = []

    for path in _iter_runtime_files(root):
        rel = _repo_relative(root, path)
        entry = inventory.get(rel)
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
                if entry is not None and _entry_is_complete(entry):
                    continue
                violations.append(BoundaryViolation(
                    path=rel,
                    line=line_no,
                    token=token,
                    reason=(
                        "legacy runtime reference is not listed in "
                        "docs/architecture/temporary-legacy-dependencies.json"
                    ),
                    inventoried=entry is not None,
                    owner_story=entry.owner_story if entry else None,
                    removal_condition=entry.removal_condition if entry else None,
                ))

    for rel, entry in inventory.items():
        target = root / rel
        if not _entry_is_complete(entry):
            violations.append(BoundaryViolation(
                path=rel,
                line=0,
                token="<inventory>",
                reason="temporary legacy inventory entry is incomplete",
                inventoried=True,
                owner_story=entry.owner_story,
                removal_condition=entry.removal_condition,
            ))
        elif not target.exists():
            violations.append(BoundaryViolation(
                path=rel,
                line=0,
                token="<inventory>",
                reason="temporary legacy inventory entry points at a missing file",
                inventoried=True,
                owner_story=entry.owner_story,
                removal_condition=entry.removal_condition,
            ))

    return violations
