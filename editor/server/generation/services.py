"""Product-owned world, storyboard, and scene-prompt generation.

The services in this module read saved song state from SQLite, assemble
versioned product prompts, call a model adapter, validate structured responses,
and persist product records. They intentionally do not read generated JSON files
or invoke experiment scripts.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .. import config as _cfg
from ..pipeline.result import StageResult
from ..store import connection


GenerationStage = Literal["world-brief", "storyboard", "image-prompts"]

WORLD_PROMPT_VERSION = "product-world-v1"
STORYBOARD_PROMPT_VERSION = "product-storyboard-v1"
IMAGE_PROMPT_VERSION = "product-image-prompts-v1"


@dataclass(frozen=True)
class GenerationResult:
    stage: GenerationStage
    changed: int
    provenance_id: int


class GenerationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelAdapter(Protocol):
    provider: str
    model: str

    def generate(self, *, stage: GenerationStage, prompt: dict[str, Any]) -> dict[str, Any]:
        ...


def generation_provider_ready() -> bool:
    provider = os.environ.get("EDITOR_GENERATION_PROVIDER", "").strip().lower()
    return provider in {"fake", "malformed"} or bool(os.environ.get("GEMINI_API_KEY"))


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _song(conn, song_id: int):
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        raise GenerationError("song_missing", "The song could not be found.")
    return row


def _scenes(conn, song_id: int):
    return conn.execute(
        """
        SELECT id, scene_index, kind, target_text, start_s, end_s,
               target_duration_s, beat, camera_intent, subject_focus,
               prev_link, next_link, image_prompt, prompt_is_user_authored
        FROM scenes
        WHERE song_id = ?
        ORDER BY scene_index
        """,
        (song_id,),
    ).fetchall()


def _scene_payload(scene) -> dict[str, Any]:
    return {
        "scene_index": scene["scene_index"],
        "kind": scene["kind"],
        "target_text": scene["target_text"],
        "start_s": scene["start_s"],
        "end_s": scene["end_s"],
        "target_duration_s": scene["target_duration_s"],
        "beat": scene["beat"],
        "camera_intent": scene["camera_intent"],
        "subject_focus": scene["subject_focus"],
    }


def _require_scenes(scenes) -> None:
    if not scenes:
        raise GenerationError(
            "scenes_missing",
            "Generation needs saved transcript scenes before it can start.",
        )


def _require_text_scene(scene) -> None:
    if not (scene["target_text"] or "").strip():
        raise GenerationError(
            "scene_text_missing",
            f"Scene {scene['scene_index']} has no transcript text for generation.",
        )


def build_world_input(conn, song_id: int) -> dict[str, Any]:
    song = _song(conn, song_id)
    scenes = _scenes(conn, song_id)
    _require_scenes(scenes)
    for scene in scenes:
        _require_text_scene(scene)
    if song["filter"] is None or song["abstraction"] is None:
        raise GenerationError(
            "visual_language_missing",
            "Choose a filter and abstraction before generating the world description.",
        )
    return {
        "prompt_version": WORLD_PROMPT_VERSION,
        "song": {
            "id": song["id"],
            "slug": song["slug"],
            "duration_s": song["duration_s"],
            "filter": song["filter"],
            "abstraction": song["abstraction"],
            "quality_mode": song["quality_mode"],
        },
        "scenes": [_scene_payload(scene) for scene in scenes],
    }


def build_storyboard_input(conn, song_id: int) -> dict[str, Any]:
    song = _song(conn, song_id)
    scenes = _scenes(conn, song_id)
    _require_scenes(scenes)
    if not (song["world_brief"] or "").strip():
        raise GenerationError(
            "world_missing",
            "Generate the world description before generating the storyboard.",
        )
    return {
        "prompt_version": STORYBOARD_PROMPT_VERSION,
        "song": {
            "id": song["id"],
            "slug": song["slug"],
            "filter": song["filter"],
            "abstraction": song["abstraction"],
            "world_brief": song["world_brief"],
        },
        "scenes": [_scene_payload(scene) for scene in scenes],
    }


def build_image_prompt_input(conn, song_id: int) -> dict[str, Any]:
    song = _song(conn, song_id)
    scenes = _scenes(conn, song_id)
    _require_scenes(scenes)
    if not (song["sequence_arc"] or "").strip():
        raise GenerationError(
            "storyboard_missing",
            "Generate the storyboard before generating image prompts.",
        )
    eligible = [
        scene for scene in scenes
        if not scene["prompt_is_user_authored"] and (scene["beat"] or "").strip()
    ]
    if not eligible:
        raise GenerationError(
            "prompt_scenes_missing",
            "Image prompt generation needs at least one scene with a storyboard beat.",
        )
    return {
        "prompt_version": IMAGE_PROMPT_VERSION,
        "song": {
            "id": song["id"],
            "slug": song["slug"],
            "filter": song["filter"],
            "abstraction": song["abstraction"],
            "world_brief": song["world_brief"],
            "sequence_arc": song["sequence_arc"],
        },
        "eligible_scene_indices": [scene["scene_index"] for scene in eligible],
        "scenes": [_scene_payload(scene) for scene in eligible],
    }


class FakeGenerationAdapter:
    provider = "fake"
    model = "deterministic-test-provider"

    def generate(self, *, stage: GenerationStage, prompt: dict[str, Any]) -> dict[str, Any]:
        slug = prompt["song"]["slug"]
        scenes = prompt.get("scenes", [])
        if stage == "world-brief":
            first = scenes[0]["target_text"] if scenes else "empty song"
            return {
                "world_brief": (
                    f"Product world for {slug}: {prompt['song'].get('filter')} "
                    f"at abstraction {prompt['song'].get('abstraction')}. "
                    f"The video opens from '{first}'."
                ),
            }
        if stage == "storyboard":
            return {
                "sequence_arc": f"Product storyboard arc for {slug}.",
                "scenes": [
                    {
                        "scene_index": scene["scene_index"],
                        "beat": f"Product beat {scene['scene_index']}: {scene['target_text']}",
                        "camera_intent": "static hold",
                        "subject_focus": f"scene {scene['scene_index']} subject",
                        "prev_link": None,
                        "next_link": None,
                    }
                    for scene in scenes
                ],
            }
        return {
            "prompts": [
                {
                    "scene_index": scene["scene_index"],
                    "image_prompt": (
                        f"{prompt['song'].get('filter')} frame for scene "
                        f"{scene['scene_index']}: {scene['beat']}"
                    ),
                }
                for scene in scenes
            ],
        }


class MalformedGenerationAdapter:
    provider = "malformed"
    model = "malformed-test-provider"

    def generate(self, *, stage: GenerationStage, prompt: dict[str, Any]) -> dict[str, Any]:
        return {"unexpected": stage, "prompt_seen": bool(prompt)}


class GeminiJsonAdapter:
    provider = "gemini"

    def __init__(self) -> None:
        self.model = os.environ.get("EDITOR_GENERATION_MODEL", "gemini-2.5-flash")
        self._api_key = os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise GenerationError(
                "model_credentials_missing",
                "Generation requires GEMINI_API_KEY or EDITOR_GENERATION_PROVIDER=fake.",
            )

    def generate(self, *, stage: GenerationStage, prompt: dict[str, Any]) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key}"
        )
        instruction = (
            f"You are generating the '{stage}' stage for a music-video editor. "
            "Return JSON only. Do not wrap it in markdown. "
            f"Required response schema: {_canonical(_response_schema(stage))}. "
            f"Input: {_canonical(prompt)}"
        )
        payload = {
            "contents": [{"parts": [{"text": instruction}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _response_schema(stage),
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise GenerationError(
                "model_request_failed",
                f"Generation provider request failed: {exc.reason if hasattr(exc, 'reason') else exc}.",
            ) from exc
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise GenerationError(
                "model_response_malformed",
                "Generation provider returned a malformed response.",
            ) from exc


def _response_schema(stage: GenerationStage) -> dict[str, Any]:
    if stage == "world-brief":
        return {
            "type": "OBJECT",
            "properties": {
                "world_brief": {
                    "type": "STRING",
                    "description": "A concise visual world description for the full song video.",
                },
            },
            "required": ["world_brief"],
        }
    if stage == "storyboard":
        scene_schema = {
            "type": "OBJECT",
            "properties": {
                "scene_index": {"type": "INTEGER"},
                "beat": {"type": "STRING"},
                "camera_intent": {"type": "STRING"},
                "subject_focus": {"type": "STRING"},
                "prev_link": {"type": "STRING", "nullable": True},
                "next_link": {"type": "STRING", "nullable": True},
            },
            "required": ["scene_index", "beat", "camera_intent", "subject_focus"],
        }
        return {
            "type": "OBJECT",
            "properties": {
                "sequence_arc": {"type": "STRING"},
                "scenes": {"type": "ARRAY", "items": scene_schema},
            },
            "required": ["sequence_arc", "scenes"],
        }
    return {
        "type": "OBJECT",
        "properties": {
            "prompts": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "scene_index": {"type": "INTEGER"},
                        "image_prompt": {"type": "STRING"},
                    },
                    "required": ["scene_index", "image_prompt"],
                },
            },
        },
        "required": ["prompts"],
    }


def adapter_from_env() -> ModelAdapter:
    provider = os.environ.get("EDITOR_GENERATION_PROVIDER", "").strip().lower()
    if provider == "fake":
        return FakeGenerationAdapter()
    if provider == "malformed":
        return MalformedGenerationAdapter()
    if provider not in ("", "gemini"):
        raise GenerationError(
            "model_provider_unknown",
            f"Generation provider '{provider}' is not supported.",
        )
    return GeminiJsonAdapter()


def _non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GenerationError(
            "model_response_malformed",
            f"Generation provider returned no {field}.",
        )
    return value.strip()


def _validate_world(raw: dict[str, Any]) -> str:
    for key in ("world_brief", "world_description", "description", "brief"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise GenerationError(
        "model_response_malformed",
        "Generation provider returned no world description. Expected JSON field 'world_brief'.",
    )


def _validate_storyboard(raw: dict[str, Any], expected_indices: set[int]) -> tuple[str, list[dict[str, Any]]]:
    arc = _non_empty_str(raw.get("sequence_arc"), "storyboard arc")
    scenes = raw.get("scenes")
    if not isinstance(scenes, list):
        raise GenerationError("model_response_malformed", "Generation provider returned no scene storyboard list.")
    by_idx: dict[int, dict[str, Any]] = {}
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_index"), int):
            raise GenerationError("model_response_malformed", "Generation provider returned an invalid storyboard scene.")
        idx = scene["scene_index"]
        by_idx[idx] = {
            "scene_index": idx,
            "beat": _non_empty_str(scene.get("beat"), f"beat for scene {idx}"),
            "camera_intent": _non_empty_str(scene.get("camera_intent"), f"camera intent for scene {idx}"),
            "subject_focus": _non_empty_str(scene.get("subject_focus"), f"subject focus for scene {idx}"),
            "prev_link": scene.get("prev_link") if isinstance(scene.get("prev_link"), str) else None,
            "next_link": scene.get("next_link") if isinstance(scene.get("next_link"), str) else None,
        }
    if set(by_idx) != expected_indices:
        raise GenerationError(
            "model_response_malformed",
            "Generation provider returned storyboard scenes that do not match the saved scene plan.",
        )
    return arc, [by_idx[idx] for idx in sorted(by_idx)]


def _validate_prompts(raw: dict[str, Any], expected_indices: set[int]) -> list[dict[str, Any]]:
    prompts = raw.get("prompts")
    if not isinstance(prompts, list):
        raise GenerationError("model_response_malformed", "Generation provider returned no image prompt list.")
    by_idx: dict[int, dict[str, Any]] = {}
    for item in prompts:
        if not isinstance(item, dict) or not isinstance(item.get("scene_index"), int):
            raise GenerationError("model_response_malformed", "Generation provider returned an invalid image prompt.")
        idx = item["scene_index"]
        by_idx[idx] = {
            "scene_index": idx,
            "image_prompt": _non_empty_str(item.get("image_prompt"), f"image prompt for scene {idx}"),
        }
    if set(by_idx) != expected_indices:
        raise GenerationError(
            "model_response_malformed",
            "Generation provider returned image prompts that do not match eligible saved scenes.",
        )
    return [by_idx[idx] for idx in sorted(by_idx)]


def _record_provenance(
    conn,
    *,
    song_id: int,
    stage: GenerationStage,
    prompt: dict[str, Any],
    adapter: ModelAdapter,
    source_run_id: int | None,
    changed: int,
) -> int:
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO generation_provenance (
            song_id, stage, prompt_version, provider, model, input_fingerprint,
            input_summary_json, response_metadata_json, source_run_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            song_id, stage, prompt["prompt_version"], adapter.provider,
            adapter.model, _fingerprint(prompt),
            json.dumps({
                "scene_count": len(prompt.get("scenes", [])),
                "eligible_scene_indices": prompt.get("eligible_scene_indices"),
                "song": prompt.get("song", {}),
            }, sort_keys=True),
            json.dumps({"changed": changed}, sort_keys=True),
            source_run_id,
            now,
        ),
    )
    return cur.lastrowid


def generate_world(
    conn, song_id: int, *, adapter: ModelAdapter | None = None,
    source_run_id: int | None = None,
) -> GenerationResult:
    adapter = adapter or adapter_from_env()
    prompt = build_world_input(conn, song_id)
    brief = _validate_world(adapter.generate(stage="world-brief", prompt=prompt))
    now = time.time()
    conn.execute(
        "UPDATE songs SET world_brief = ?, updated_at = ? WHERE id = ?",
        (brief, now, song_id),
    )
    provenance_id = _record_provenance(
        conn, song_id=song_id, stage="world-brief", prompt=prompt,
        adapter=adapter, source_run_id=source_run_id, changed=1,
    )
    return GenerationResult("world-brief", 1, provenance_id)


def generate_storyboard(
    conn, song_id: int, *, adapter: ModelAdapter | None = None,
    source_run_id: int | None = None,
) -> GenerationResult:
    adapter = adapter or adapter_from_env()
    prompt = build_storyboard_input(conn, song_id)
    expected = {scene["scene_index"] for scene in prompt["scenes"]}
    arc, scenes = _validate_storyboard(
        adapter.generate(stage="storyboard", prompt=prompt),
        expected,
    )
    now = time.time()
    conn.execute(
        "UPDATE songs SET sequence_arc = ?, updated_at = ? WHERE id = ?",
        (arc, now, song_id),
    )
    for scene in scenes:
        conn.execute(
            """
            UPDATE scenes
            SET beat = ?, camera_intent = ?, subject_focus = ?,
                prev_link = ?, next_link = ?, updated_at = ?
            WHERE song_id = ? AND scene_index = ?
            """,
            (
                scene["beat"], scene["camera_intent"], scene["subject_focus"],
                scene["prev_link"], scene["next_link"], now, song_id,
                scene["scene_index"],
            ),
        )
    provenance_id = _record_provenance(
        conn, song_id=song_id, stage="storyboard", prompt=prompt,
        adapter=adapter, source_run_id=source_run_id, changed=len(scenes),
    )
    return GenerationResult("storyboard", len(scenes), provenance_id)


def generate_image_prompts(
    conn, song_id: int, *, adapter: ModelAdapter | None = None,
    source_run_id: int | None = None,
) -> GenerationResult:
    adapter = adapter or adapter_from_env()
    prompt = build_image_prompt_input(conn, song_id)
    expected = set(prompt["eligible_scene_indices"])
    prompts = _validate_prompts(
        adapter.generate(stage="image-prompts", prompt=prompt),
        expected,
    )
    now = time.time()
    changed = 0
    for item in prompts:
        changed += conn.execute(
            """
            UPDATE scenes
            SET image_prompt = ?, updated_at = ?
            WHERE song_id = ? AND scene_index = ? AND prompt_is_user_authored = 0
            """,
            (item["image_prompt"], now, song_id, item["scene_index"]),
        ).rowcount
    provenance_id = _record_provenance(
        conn, song_id=song_id, stage="image-prompts", prompt=prompt,
        adapter=adapter, source_run_id=source_run_id, changed=changed,
    )
    return GenerationResult("image-prompts", changed, provenance_id)


def run_generation_stage(
    *,
    song_slug: str,
    stage: GenerationStage,
    source_run_id: int | None,
    db_path: Path | None = None,
) -> StageResult:
    started = time.time()
    try:
        with connection(db_path or _cfg.DB_PATH) as conn:
            song = conn.execute(
                "SELECT id FROM songs WHERE slug = ?",
                (song_slug,),
            ).fetchone()
            if song is None:
                raise GenerationError("song_missing", f"Song '{song_slug}' could not be found.")
            if stage == "world-brief":
                result = generate_world(conn, song["id"], source_run_id=source_run_id)
            elif stage == "storyboard":
                result = generate_storyboard(conn, song["id"], source_run_id=source_run_id)
            elif stage == "image-prompts":
                result = generate_image_prompts(conn, song["id"], source_run_id=source_run_id)
            else:
                raise GenerationError("unknown_stage", f"Stage '{stage}' is not a product generation stage.")
    except GenerationError as exc:
        return StageResult(
            ok=False,
            returncode=126,
            new_keyframes=0,
            new_prompts=0,
            stdout_tail="",
            stderr_tail=exc.message,
            duration_s=time.time() - started,
        )
    return StageResult(
        ok=True,
        returncode=0,
        new_keyframes=0,
        new_prompts=result.changed if stage == "image-prompts" else 0,
        stdout_tail=f"{stage} generated from saved product data",
        stderr_tail="",
        duration_s=time.time() - started,
    )
