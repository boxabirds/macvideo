"""Product-owned keyframe, clip, and final video rendering services."""

from __future__ import annotations

import json
import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .. import config as _cfg
from ..pipeline.stages import StageResult
from ..store import connection


RenderStage = Literal["keyframes", "scene-keyframe", "scene-clip", "final-video"]
ArtefactKind = Literal["keyframe", "clip"]


@dataclass(frozen=True)
class RenderResult:
    stage: RenderStage
    changed: int
    provenance_ids: list[int]
    final_path: str | None = None


class RenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RenderAdapter(Protocol):
    provider: str
    model: str

    def render_keyframe(self, *, prompt: str, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        ...

    def render_clip(self, *, keyframe_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        ...

    def render_final(self, *, clip_paths: list[Path], audio_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        ...


def render_provider_ready() -> bool:
    provider = os.environ.get("EDITOR_RENDER_PROVIDER", "").strip().lower()
    return provider in {"fake", "fail-keyframe", "fail-clip", "fail-final"}


def _tiny_png(width: int = 8, height: int = 8) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    raw = b"".join(b"\x00" + b"\xa0\xa0\xa0" * width for _ in range(height))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


_FAKE_MP4 = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 512


class FakeRenderAdapter:
    provider = "fake"
    model = "deterministic-render-provider"

    def render_keyframe(self, *, prompt: str, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_tiny_png())
        return {"bytes": target.stat().st_size, "prompt_len": len(prompt), "settings": settings}

    def render_clip(self, *, keyframe_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        if not keyframe_path.exists():
            raise RenderError("keyframe_file_missing", f"Keyframe file is missing for clip render: {keyframe_path.name}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_FAKE_MP4)
        return {"bytes": target.stat().st_size, "keyframe": keyframe_path.name, "settings": settings}

    def render_final(self, *, clip_paths: list[Path], audio_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        missing = [p.name for p in clip_paths if not p.exists()]
        if missing:
            raise RenderError("clip_file_missing", f"Final video is missing clip files: {', '.join(missing)}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_FAKE_MP4 * max(2, len(clip_paths)))
        return {"bytes": target.stat().st_size, "clips": len(clip_paths), "audio": audio_path.name, "settings": settings}


class FailingRenderAdapter(FakeRenderAdapter):
    def __init__(self, failure: str) -> None:
        self.provider = failure
        self.model = "failing-render-provider"
        self.failure = failure

    def render_keyframe(self, *, prompt: str, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        if self.failure == "fail-keyframe":
            raise RenderError("renderer_failed", "Keyframe renderer failed for the selected scene.")
        return super().render_keyframe(prompt=prompt, target=target, settings=settings)

    def render_clip(self, *, keyframe_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        if self.failure == "fail-clip":
            raise RenderError("renderer_failed", "Clip renderer failed for the selected scene.")
        return super().render_clip(keyframe_path=keyframe_path, target=target, settings=settings)

    def render_final(self, *, clip_paths: list[Path], audio_path: Path, target: Path, settings: dict[str, Any]) -> dict[str, Any]:
        if self.failure == "fail-final":
            raise RenderError("renderer_failed", "Final video renderer failed.")
        return super().render_final(clip_paths=clip_paths, audio_path=audio_path, target=target, settings=settings)


def adapter_from_env() -> RenderAdapter:
    provider = os.environ.get("EDITOR_RENDER_PROVIDER", "").strip().lower()
    if provider == "fake":
        return FakeRenderAdapter()
    if provider in {"fail-keyframe", "fail-clip", "fail-final"}:
        return FailingRenderAdapter(provider)
    raise RenderError(
        "renderer_provider_missing",
        "Rendering requires EDITOR_RENDER_PROVIDER=fake or a configured product render adapter.",
    )


def _artifact_root(song_slug: str) -> Path:
    return Path(_cfg.OUTPUTS_DIR) / "_product_artifacts" / song_slug


def _song(conn, song_id: int):
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        raise RenderError("song_missing", "The song could not be found.")
    return row


def _scene_query(conn, song_id: int, scene_indices: list[int] | None = None):
    where = "WHERE s.song_id = ?"
    params: list[Any] = [song_id]
    if scene_indices is not None:
        if not scene_indices:
            raise RenderError("scene_missing", "No scenes were selected for rendering.")
        where += f" AND s.scene_index IN ({','.join('?' for _ in scene_indices)})"
        params.extend(scene_indices)
    return conn.execute(
        f"""
        SELECT s.*,
               kf.asset_path AS selected_keyframe_path,
               cl.asset_path AS selected_clip_path
        FROM scenes s
        LEFT JOIN takes kf ON kf.id = s.selected_keyframe_take_id
        LEFT JOIN takes cl ON cl.id = s.selected_clip_take_id
        {where}
        ORDER BY s.scene_index
        """,
        params,
    ).fetchall()


def _dirty_flags(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def _write_flags(conn, scene_id: int, flags: set[str]) -> None:
    conn.execute(
        "UPDATE scenes SET dirty_flags = ?, updated_at = ? WHERE id = ?",
        (json.dumps(sorted(flags)), time.time(), scene_id),
    )


def _record_provenance(
    conn,
    *,
    song_id: int,
    scene_id: int | None,
    artefact_kind: str,
    provider: str,
    model: str,
    source_json: dict[str, Any],
    artifact_path: str,
    source_run_id: int | None,
    metadata: dict[str, Any],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO render_provenance (
            song_id, scene_id, artefact_kind, provider, model,
            source_json, artifact_path, source_run_id, adapter_metadata_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            song_id, scene_id, artefact_kind, provider, model,
            json.dumps(source_json, sort_keys=True), artifact_path,
            source_run_id, json.dumps(metadata, sort_keys=True), time.time(),
        ),
    )
    return cur.lastrowid


def _insert_take(
    conn,
    *,
    scene,
    artefact_kind: ArtefactKind,
    asset_path: str,
    source_run_id: int | None,
    quality_mode: str | None,
    prompt_snapshot: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO takes (
            scene_id, artefact_kind, asset_path, prompt_snapshot,
            source_run_id, quality_mode, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'editor', ?)
        """,
        (
            scene["id"], artefact_kind, asset_path, prompt_snapshot,
            source_run_id, quality_mode, time.time(),
        ),
    )
    selected_col = "selected_keyframe_take_id" if artefact_kind == "keyframe" else "selected_clip_take_id"
    selected_path_col = "selected_keyframe_path" if artefact_kind == "keyframe" else "selected_clip_path"
    stale_flag = "keyframe_stale" if artefact_kind == "keyframe" else "clip_stale"
    selected_path = scene[selected_path_col]
    selected_is_usable = bool(selected_path) and Path(selected_path).exists()
    if scene[selected_col] is None or not selected_is_usable:
        flags = _dirty_flags(scene["dirty_flags"])
        flags.discard(stale_flag)
        conn.execute(
            f"UPDATE scenes SET {selected_col} = ?, dirty_flags = ?, updated_at = ? WHERE id = ?",
            (cur.lastrowid, json.dumps(sorted(flags)), time.time(), scene["id"]),
        )
    return cur.lastrowid


def render_keyframes(
    conn, song_id: int, *, scene_indices: list[int] | None = None,
    adapter: RenderAdapter | None = None, source_run_id: int | None = None,
) -> RenderResult:
    song = _song(conn, song_id)
    adapter = adapter or adapter_from_env()
    scenes = _scene_query(conn, song_id, scene_indices)
    if not scenes:
        raise RenderError("scene_missing", "Keyframe rendering needs saved scenes.")
    provenance_ids: list[int] = []
    for scene in scenes:
        prompt = (scene["image_prompt"] or "").strip()
        if not prompt:
            raise RenderError("image_prompt_missing", f"Scene {scene['scene_index']} has no image prompt.")
        target = _artifact_root(song["slug"]) / "keyframes" / f"scene_{scene['scene_index']:03d}_run{source_run_id or int(time.time())}.png"
        metadata = adapter.render_keyframe(
            prompt=prompt,
            target=target,
            settings={"quality_mode": song["quality_mode"], "filter": song["filter"], "abstraction": song["abstraction"]},
        )
        _insert_take(
            conn, scene=scene, artefact_kind="keyframe", asset_path=str(target),
            source_run_id=source_run_id, quality_mode=song["quality_mode"],
            prompt_snapshot=prompt,
        )
        provenance_ids.append(_record_provenance(
            conn, song_id=song_id, scene_id=scene["id"], artefact_kind="keyframe",
            provider=adapter.provider, model=adapter.model,
            source_json={"scene_index": scene["scene_index"], "image_prompt": prompt},
            artifact_path=str(target), source_run_id=source_run_id, metadata=metadata,
        ))
    return RenderResult("keyframes", len(provenance_ids), provenance_ids)


def render_clips(
    conn, song_id: int, *, scene_indices: list[int] | None = None,
    adapter: RenderAdapter | None = None, source_run_id: int | None = None,
) -> RenderResult:
    song = _song(conn, song_id)
    adapter = adapter or adapter_from_env()
    scenes = _scene_query(conn, song_id, scene_indices)
    if not scenes:
        raise RenderError("scene_missing", "Clip rendering needs saved scenes.")
    provenance_ids: list[int] = []
    for scene in scenes:
        if scene["selected_keyframe_take_id"] is None or not scene["selected_keyframe_path"]:
            raise RenderError("keyframe_missing", f"Scene {scene['scene_index']} needs a selected keyframe first.")
        keyframe = Path(scene["selected_keyframe_path"])
        target = _artifact_root(song["slug"]) / "clips" / f"scene_{scene['scene_index']:03d}_run{source_run_id or int(time.time())}.mp4"
        metadata = adapter.render_clip(
            keyframe_path=keyframe,
            target=target,
            settings={"quality_mode": song["quality_mode"], "target_duration_s": scene["target_duration_s"]},
        )
        _insert_take(
            conn, scene=scene, artefact_kind="clip", asset_path=str(target),
            source_run_id=source_run_id, quality_mode=song["quality_mode"],
            prompt_snapshot=scene["image_prompt"],
        )
        provenance_ids.append(_record_provenance(
            conn, song_id=song_id, scene_id=scene["id"], artefact_kind="clip",
            provider=adapter.provider, model=adapter.model,
            source_json={"scene_index": scene["scene_index"], "keyframe_path": str(keyframe)},
            artifact_path=str(target), source_run_id=source_run_id, metadata=metadata,
        ))
    return RenderResult("scene-clip", len(provenance_ids), provenance_ids)


def render_final_video(
    conn, song_id: int, *, adapter: RenderAdapter | None = None,
    source_run_id: int | None = None,
) -> RenderResult:
    song = _song(conn, song_id)
    adapter = adapter or adapter_from_env()
    scenes = _scene_query(conn, song_id)
    if not scenes:
        raise RenderError("scene_missing", "Final video rendering needs saved scenes.")
    missing = [s["scene_index"] for s in scenes if not s["selected_clip_take_id"] or not s["selected_clip_path"]]
    if missing:
        raise RenderError("clip_missing", f"Final video needs clips for scenes: {', '.join(map(str, missing))}.")
    clip_paths = [Path(s["selected_clip_path"]) for s in scenes]
    target = _artifact_root(song["slug"]) / "finals" / f"final_run{source_run_id or int(time.time())}_{song['quality_mode']}.mp4"
    metadata = adapter.render_final(
        clip_paths=clip_paths,
        audio_path=Path(song["audio_path"]),
        target=target,
        settings={"quality_mode": song["quality_mode"], "scene_count": len(scenes)},
    )
    cur = conn.execute(
        """
        INSERT INTO finished_videos (
            song_id, file_path, quality_mode, scene_count, gap_count,
            final_run_id, created_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (song_id, str(target), song["quality_mode"], len(scenes), source_run_id, time.time()),
    )
    provenance_id = _record_provenance(
        conn, song_id=song_id, scene_id=None, artefact_kind="final_video",
        provider=adapter.provider, model=adapter.model,
        source_json={"clip_paths": [str(p) for p in clip_paths], "finished_video_id": cur.lastrowid},
        artifact_path=str(target), source_run_id=source_run_id, metadata=metadata,
    )
    return RenderResult("final-video", 1, [provenance_id], final_path=str(target))


def run_render_stage(
    *,
    song_slug: str,
    stage: RenderStage,
    source_run_id: int | None,
    scene_index: int | None = None,
    db_path: Path | None = None,
) -> StageResult:
    started = time.time()
    try:
        with connection(db_path or _cfg.DB_PATH) as conn:
            song = conn.execute("SELECT id FROM songs WHERE slug = ?", (song_slug,)).fetchone()
            if song is None:
                raise RenderError("song_missing", f"Song '{song_slug}' could not be found.")
            if stage in ("keyframes", "scene-keyframe"):
                result = render_keyframes(
                    conn, song["id"],
                    scene_indices=[scene_index] if scene_index is not None else None,
                    source_run_id=source_run_id,
                )
            elif stage == "scene-clip":
                result = render_clips(
                    conn, song["id"],
                    scene_indices=[scene_index] if scene_index is not None else None,
                    source_run_id=source_run_id,
                )
            elif stage == "final-video":
                result = render_final_video(conn, song["id"], source_run_id=source_run_id)
            else:
                raise RenderError("unknown_stage", f"Stage '{stage}' is not a product render stage.")
    except RenderError as exc:
        return StageResult(
            ok=False, returncode=126, new_keyframes=0, new_prompts=0,
            stdout_tail="", stderr_tail=exc.message,
            duration_s=time.time() - started,
        )
    return StageResult(
        ok=True, returncode=0,
        new_keyframes=result.changed if stage in ("keyframes", "scene-keyframe") else 0,
        new_prompts=0,
        stdout_tail=f"{stage} rendered from saved product data",
        stderr_tail="",
        duration_s=time.time() - started,
    )
