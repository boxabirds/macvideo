"""Lossless lyric-line formatting for audio transcription output."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..generation.services import GenerationError


MAX_FORMAT_ATTEMPTS = 3
_TOKEN_RE = re.compile(r"\S+")


class LyricLineError(Exception):
    """Raised when model-proposed line breaks cannot be trusted."""


class LyricLineAdapter(Protocol):
    provider: str
    model: str

    def format_lines(self, *, transcript: str) -> dict[str, Any]:
        """Return a response containing `lines: [{line_index, text}, ...]`."""


@dataclass(frozen=True)
class SceneDraft:
    target_text: str
    start_s: float
    end_s: float
    source: str

    @property
    def target_duration_s(self) -> float:
        return self.end_s - self.start_s if self.end_s > self.start_s else 0.0


@dataclass(frozen=True)
class LyricLineAttempt:
    attempt: int
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class LyricLinePlan:
    scenes: list[SceneDraft]
    formatted: bool
    attempts: tuple[LyricLineAttempt, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _TokenTiming:
    text: str
    start_s: float
    end_s: float


def normalize_transcript(text: str) -> str:
    return " ".join((text or "").split())


def segments_to_transcript(segments: list[dict[str, Any]]) -> str:
    return normalize_transcript(" ".join(str(segment.get("text", "")) for segment in segments))


def fallback_scene_drafts(segments: list[dict[str, Any]]) -> list[SceneDraft]:
    return [
        SceneDraft(
            target_text=str(segment.get("text", "")),
            start_s=float(segment.get("start", 0.0) or 0.0),
            end_s=float(segment.get("end", 0.0) or 0.0),
            source="whisperx_segment",
        )
        for segment in segments
    ]


def validate_lines_lossless(transcript: str, lines: list[dict[str, Any]]) -> list[str]:
    if not lines:
        raise LyricLineError("formatter returned no lyric lines")
    expected_indexes = list(range(len(lines)))
    actual_indexes: list[int] = []
    texts: list[str] = []
    for item in lines:
        if not isinstance(item, dict):
            raise LyricLineError("formatter returned a non-object line item")
        index = item.get("line_index")
        text = item.get("text")
        if not isinstance(index, int) or not isinstance(text, str):
            raise LyricLineError("formatter line items must include integer line_index and string text")
        actual_indexes.append(index)
        if not normalize_transcript(text):
            raise LyricLineError("formatter returned an empty lyric line")
        texts.append(text)
    if actual_indexes != expected_indexes:
        raise LyricLineError("formatter line_index values must start at 0 and increment by 1")
    source = normalize_transcript(transcript)
    proposed = normalize_transcript(" ".join(texts))
    if proposed != source:
        raise LyricLineError("formatter changed transcript text")
    return texts


def assign_line_timings(segments: list[dict[str, Any]], line_texts: list[str]) -> list[SceneDraft]:
    token_timings = _source_token_timings(segments)
    cursor = 0
    scenes: list[SceneDraft] = []
    for line_text in line_texts:
        line_tokens = _tokens(line_text)
        if not line_tokens:
            raise LyricLineError("cannot assign timing to an empty lyric line")
        end = cursor + len(line_tokens)
        source_slice = token_timings[cursor:end]
        if len(source_slice) != len(line_tokens):
            raise LyricLineError("formatted lines do not match source token count")
        if [token.text for token in source_slice] != line_tokens:
            raise LyricLineError("formatted line token order does not match source transcript")
        scenes.append(
            SceneDraft(
                target_text=line_text,
                start_s=source_slice[0].start_s,
                end_s=source_slice[-1].end_s,
                source="lyric_line_formatter",
            ),
        )
        cursor = end
    if cursor != len(token_timings):
        raise LyricLineError("formatted lines did not consume every source token")
    return scenes


def format_segments_for_scene_drafts(
    segments: list[dict[str, Any]],
    *,
    adapter: LyricLineAdapter | None = None,
    max_attempts: int = MAX_FORMAT_ATTEMPTS,
) -> LyricLinePlan:
    transcript = segments_to_transcript(segments)
    if not transcript:
        return LyricLinePlan(scenes=fallback_scene_drafts(segments), formatted=False)

    attempts: list[LyricLineAttempt] = []
    formatter: LyricLineAdapter
    try:
        formatter = adapter or adapter_from_env()
    except Exception as exc:  # noqa: BLE001 - formatter is optional fallback.
        return LyricLinePlan(
            scenes=fallback_scene_drafts(segments),
            formatted=False,
            attempts=(LyricLineAttempt(1, False, str(exc)),),
        )

    for attempt in range(1, max_attempts + 1):
        try:
            raw = formatter.format_lines(transcript=transcript)
            raw_lines = raw.get("lines") if isinstance(raw, dict) else None
            if not isinstance(raw_lines, list):
                raise LyricLineError("formatter response must contain a lines array")
            line_texts = validate_lines_lossless(transcript, raw_lines)
            scenes = assign_line_timings(segments, line_texts)
            attempts.append(LyricLineAttempt(attempt, True))
            return LyricLinePlan(scenes=scenes, formatted=True, attempts=tuple(attempts))
        except Exception as exc:  # noqa: BLE001 - retry and then fallback.
            attempts.append(LyricLineAttempt(attempt, False, str(exc)))

    return LyricLinePlan(
        scenes=fallback_scene_drafts(segments),
        formatted=False,
        attempts=tuple(attempts),
    )


class FakeLyricLineAdapter:
    provider = "fake"
    model = "fake-lyric-line-formatter"

    def format_lines(self, *, transcript: str) -> dict[str, Any]:
        mode = os.environ.get("EDITOR_FAKE_LYRIC_LINE_MODE", "split").strip().lower()
        if mode == "malformed":
            return {"unexpected": transcript}
        if mode == "changed":
            return {"lines": [{"line_index": 0, "text": f"{transcript} changed"}]}
        tokens = _tokens(transcript)
        chunk_size = 3
        lines = [
            {
                "line_index": i,
                "text": " ".join(tokens[i * chunk_size:(i + 1) * chunk_size]),
            }
            for i in range((len(tokens) + chunk_size - 1) // chunk_size)
        ]
        return {"lines": lines}


class MalformedLyricLineAdapter:
    provider = "malformed"
    model = "malformed-lyric-line-formatter"

    def format_lines(self, *, transcript: str) -> dict[str, Any]:
        return {"lines": [{"line_index": 0, "text": f"{transcript} changed"}]}


class GeminiLyricLineAdapter:
    provider = "gemini"

    def __init__(self) -> None:
        self.model = os.environ.get("EDITOR_GENERATION_MODEL", "gemini-2.5-flash")
        self._api_key = os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise GenerationError(
                "model_credentials_missing",
                "Lyric-line formatting requires GEMINI_API_KEY or EDITOR_GENERATION_PROVIDER=fake.",
            )

    def format_lines(self, *, transcript: str) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": _prompt(transcript)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _response_schema(),
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
                f"Lyric-line formatter request failed: {exc.reason if hasattr(exc, 'reason') else exc}.",
            ) from exc
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GenerationError(
                "model_response_malformed",
                "Lyric-line formatter returned a malformed response.",
            ) from exc


def adapter_from_env() -> LyricLineAdapter:
    provider = (
        os.environ.get("EDITOR_LYRIC_LINE_PROVIDER")
        or os.environ.get("EDITOR_GENERATION_PROVIDER", "")
    ).strip().lower()
    if provider == "fake":
        return FakeLyricLineAdapter()
    if provider == "malformed":
        return MalformedLyricLineAdapter()
    if provider not in ("", "gemini"):
        raise GenerationError(
            "model_provider_unknown",
            f"Lyric-line formatter provider '{provider}' is not supported.",
        )
    return GeminiLyricLineAdapter()


def _source_token_timings(segments: list[dict[str, Any]]) -> list[_TokenTiming]:
    timings: list[_TokenTiming] = []
    for segment in segments:
        text = str(segment.get("text", ""))
        tokens = _tokens(text)
        if not tokens:
            continue
        start_s = float(segment.get("start", 0.0) or 0.0)
        end_s = float(segment.get("end", start_s) or start_s)
        duration = max(0.001, end_s - start_s)
        step = duration / len(tokens)
        for idx, token in enumerate(tokens):
            token_start = start_s + step * idx
            token_end = end_s if idx == len(tokens) - 1 else start_s + step * (idx + 1)
            timings.append(_TokenTiming(token, token_start, token_end))
    return timings


def _tokens(text: str) -> list[str]:
    return [match.group(0) for match in _TOKEN_RE.finditer(text or "")]


def _prompt(transcript: str) -> str:
    return (
        "You are formatting a raw sung transcription into song lyric lines.\n"
        "\n"
        "This is a line-break task only.\n"
        "Hard rules:\n"
        "- Preserve the transcription exactly.\n"
        "- Do not add words.\n"
        "- Do not remove words.\n"
        "- Do not reorder words.\n"
        "- Do not correct spelling, punctuation, capitalization, grammar, or ASR errors.\n"
        "- Only choose where lyric line breaks go.\n"
        "- Short lines are valid, including one-word lines.\n"
        "- Return JSON only, matching the provided schema.\n"
        "\n"
        "Return each line as one object in order. line_index must start at 0 and increment by 1.\n"
        "\n"
        "Raw transcription:\n"
        f"{transcript}"
    )


def _response_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "lines": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "line_index": {"type": "INTEGER"},
                        "text": {"type": "STRING"},
                    },
                    "required": ["line_index", "text"],
                },
            },
        },
        "required": ["lines"],
    }
