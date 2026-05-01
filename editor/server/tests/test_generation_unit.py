"""Story 30 product generation prompt and validation rules."""

from __future__ import annotations

import sqlite3
import time
import json
from pathlib import Path
from contextlib import contextmanager

import pytest

from editor.server.generation import services
from editor.server.store.schema import init_db


def _db(tmp_path: Path):
    dbp = tmp_path / "generation.db"
    init_db(dbp)
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _song(conn, *, world: str | None = None, arc: str | None = None):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO songs (
            slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, world_brief, sequence_arc, created_at, updated_at
        ) VALUES ('song', '/song.wav', 5, 100, 'charcoal', 0, 'draft', ?, ?, ?, ?)
        """,
        (world, arc, now, now),
    )
    return cur.lastrowid


def _scene(conn, song_id: int, idx: int, *, text="line", beat=None, prompt_user=False):
    now = time.time()
    conn.execute(
        """
        INSERT INTO scenes (
            song_id, scene_index, kind, target_text, start_s, end_s,
            target_duration_s, num_frames, beat, prompt_is_user_authored,
            created_at, updated_at
        ) VALUES (?, ?, 'lyric', ?, ?, ?, 1, 24, ?, ?, ?, ?)
        """,
        (song_id, idx, text, idx - 1, idx, beat, int(prompt_user), now, now),
    )


def test_world_input_requires_saved_scenes(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)

    with pytest.raises(services.GenerationError) as exc:
        services.build_world_input(conn, song_id)

    assert exc.value.code == "scenes_missing"


def test_world_prompt_is_versioned_and_uses_saved_scene_text(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id, 1, text="saved lyric line")

    prompt = services.build_world_input(conn, song_id)

    assert prompt["prompt_version"] == services.WORLD_PROMPT_VERSION
    assert prompt["song"]["filter"] == "charcoal"
    assert prompt["song"]["abstraction"] == 0
    assert prompt["scenes"][0]["target_text"] == "saved lyric line"


def test_malformed_world_response_does_not_overwrite_existing_world(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="keep me")
    _scene(conn, song_id, 1)

    with pytest.raises(services.GenerationError) as exc:
        services.generate_world(conn, song_id, adapter=services.MalformedGenerationAdapter())

    assert exc.value.code == "model_response_malformed"
    row = conn.execute("SELECT world_brief FROM songs WHERE id = ?", (song_id,)).fetchone()
    assert row["world_brief"] == "keep me"


class WorldDescriptionAliasAdapter(services.FakeGenerationAdapter):
    def generate(self, *, stage, prompt):  # noqa: ANN001
        return {"world_description": "alias world"}


def test_world_response_accepts_common_provider_alias_before_persistence(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id, 1)

    services.generate_world(conn, song_id, adapter=WorldDescriptionAliasAdapter())

    row = conn.execute("SELECT world_brief FROM songs WHERE id = ?", (song_id,)).fetchone()
    assert row["world_brief"] == "alias world"


class _FakeHttpResponse:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode("utf-8")

    def read(self):
        return self.body


@contextmanager
def _fake_urlopen_response(body: dict):
    yield _FakeHttpResponse(body)


def test_gemini_adapter_sends_world_response_schema(monkeypatch):
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout):  # noqa: ANN001
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _fake_urlopen_response({
            "candidates": [
                {"content": {"parts": [{"text": json.dumps({"world_brief": "schema world"})}]}}
            ],
        })

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(services.urllib.request, "urlopen", fake_urlopen)

    adapter = services.GeminiJsonAdapter()
    result = adapter.generate(stage="world-brief", prompt={
        "prompt_version": services.WORLD_PROMPT_VERSION,
        "song": {"slug": "song"},
        "scenes": [],
    })

    payload = captured["payload"]
    assert result == {"world_brief": "schema world"}
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseSchema"]["required"] == ["world_brief"]
    assert "world_brief" in payload["contents"][0]["parts"][0]["text"]


def test_image_prompt_input_uses_only_eligible_non_authored_storyboard_scenes(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", arc="arc")
    _scene(conn, song_id, 1, beat="beat one")
    _scene(conn, song_id, 2, beat=None)
    _scene(conn, song_id, 3, beat="hand prompt", prompt_user=True)

    prompt = services.build_image_prompt_input(conn, song_id)

    assert prompt["prompt_version"] == services.IMAGE_PROMPT_VERSION
    assert prompt["eligible_scene_indices"] == [1]


class PartialPromptAdapter(services.FakeGenerationAdapter):
    def generate(self, *, stage, prompt):  # noqa: ANN001
        return {"prompts": []}


def test_partial_prompt_response_is_rejected_before_persistence(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn, world="world", arc="arc")
    _scene(conn, song_id, 1, beat="beat one")

    with pytest.raises(services.GenerationError) as exc:
        services.generate_image_prompts(conn, song_id, adapter=PartialPromptAdapter())

    assert exc.value.code == "model_response_malformed"
    row = conn.execute("SELECT image_prompt FROM scenes WHERE song_id = ?", (song_id,)).fetchone()
    assert row["image_prompt"] is None
