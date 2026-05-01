"""Product-level dependency checks before pipeline work is queued."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .audio_transcribe import _resolve_demucs_script, _resolve_whisperx_script
from .paths import poc_scripts_root, resolve_song_paths


StageName = Literal[
    "audio-transcribe",
    "transcribe",
    "world-brief",
    "storyboard",
    "image-prompts",
    "keyframes",
    "scene-keyframe",
    "scene-clip",
    "final-video",
]


@dataclass(frozen=True)
class MissingDependency:
    code: str
    detail: str
    affected_action: str


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    stage: str
    missing: list[MissingDependency] = field(default_factory=list)

    @property
    def first_reason(self) -> str:
        if not self.missing:
            return ""
        return self.missing[0].detail

    def to_http_detail(self) -> dict[str, object]:
        return {
            "code": "dependency_preflight_failed",
            "stage": self.stage,
            "reason": self.first_reason,
            "missing": [m.__dict__ for m in self.missing],
        }


def _script_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _is_fake_override(name: str) -> bool:
    return bool(os.environ.get(name))


def _missing_script(path: Path, code: str, action: str) -> MissingDependency | None:
    if path.exists():
        return None
    return MissingDependency(
        code=code,
        detail=f"{action} is unavailable because its configured product command is missing.",
        affected_action=action,
    )


def _generation_provider_ready() -> bool:
    provider = os.environ.get("EDITOR_GENERATION_PROVIDER", "").strip().lower()
    return provider in {"fake", "malformed"} or bool(os.environ.get("GEMINI_API_KEY"))


def _render_provider_ready() -> bool:
    provider = os.environ.get("EDITOR_RENDER_PROVIDER", "").strip().lower()
    return provider in {"fake", "fail-keyframe", "fail-clip", "fail-final"}


def _missing_text_generation_provider(action: str) -> MissingDependency | None:
    if _generation_provider_ready():
        return None
    return MissingDependency(
        code="model_credentials_missing",
        detail=(
            f"{action} requires GEMINI_API_KEY or a configured product "
            "generation provider before it can start."
        ),
        affected_action=action,
    )


def _missing_render_provider(action: str) -> MissingDependency | None:
    if _render_provider_ready():
        return None
    return MissingDependency(
        code="renderer_provider_missing",
        detail=f"{action} requires a configured product render adapter before it can start.",
        affected_action=action,
    )


def _missing_gemini(action: str) -> MissingDependency | None:
    if os.environ.get("GEMINI_API_KEY") or _is_fake_override("EDITOR_FAKE_GEN_KEYFRAMES"):
        return None
    return MissingDependency(
        code="model_credentials_missing",
        detail=f"{action} requires GEMINI_API_KEY before it can start.",
        affected_action=action,
    )


def _missing_ffmpeg(action: str) -> MissingDependency | None:
    if shutil.which("ffmpeg") is not None:
        return None
    return MissingDependency(
        code="ffmpeg_missing",
        detail=f"{action} requires ffmpeg on PATH before it can start.",
        affected_action=action,
    )


def _append_if_missing(items: list[MissingDependency], item: MissingDependency | None) -> None:
    if item is not None:
        items.append(item)


def preflight_stage(*, slug: str, stage: StageName) -> PreflightResult:
    """Check product-level dependencies before queueing a stage.

    This intentionally returns product language instead of raw filesystem
    paths. Raw paths can still be logged by the lower-level runner if a later
    race occurs, but request-time failures should tell users what to fix.
    """
    from .. import config as _cfg

    missing: list[MissingDependency] = []
    scripts = poc_scripts_root()
    paths = resolve_song_paths(
        outputs_root=_cfg.OUTPUTS_DIR,
        music_root=_cfg.MUSIC_DIR,
        slug=slug,
    )

    if stage == "audio-transcribe":
        _append_if_missing(
            missing,
            _missing_script(_resolve_demucs_script(), "demucs_command_missing", "audio separation"),
        )
        _append_if_missing(
            missing,
            _missing_script(_resolve_whisperx_script(), "whisperx_command_missing", "audio transcription"),
        )
        if not paths.music_wav.exists():
            missing.append(MissingDependency(
                code="audio_missing",
                detail="audio transcription requires a song audio file before it can start.",
                affected_action="audio transcription",
            ))
    elif stage == "transcribe":
        _append_if_missing(
            missing,
            _missing_script(
                _script_from_env("EDITOR_FAKE_WHISPERX_ALIGN", scripts / "whisperx_align.py"),
                "legacy_alignment_command_missing",
                "legacy transcription",
            ),
        )
        _append_if_missing(
            missing,
            _missing_script(
                _script_from_env("EDITOR_FAKE_MAKE_SHOTS", scripts / "make_shots.py"),
                "legacy_shot_planning_command_missing",
                "legacy transcription",
            ),
        )
        if not paths.music_wav.exists():
            missing.append(MissingDependency(
                code="audio_missing",
                detail="legacy transcription requires a song audio file before it can start.",
                affected_action="legacy transcription",
            ))
    elif stage in {"world-brief", "storyboard", "image-prompts"}:
        _append_if_missing(missing, _missing_text_generation_provider("generation"))
    elif stage in {"keyframes", "scene-keyframe", "scene-clip", "final-video"}:
        _append_if_missing(missing, _missing_render_provider("rendering"))
    else:
        missing.append(MissingDependency(
            code="unknown_stage",
            detail=f"stage '{stage}' is not a known product action.",
            affected_action=str(stage),
        ))

    return PreflightResult(ok=not missing, stage=stage, missing=missing)
