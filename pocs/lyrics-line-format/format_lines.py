#!/usr/bin/env python3
"""POC: ask Gemini to insert lyric line breaks without changing text."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WHISPERX_JSON = REPO_ROOT / "pocs" / "lyrics-line-format" / "no-mans-land.whisperx.json"
DEFAULT_OUT = REPO_ROOT / "pocs" / "lyrics-line-format" / "no-mans-land.lines.json"
DEFAULT_MODEL = "gemini-2.5-flash"


def _load_env() -> None:
    root_str = str(REPO_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from editor.server.env_file import load_project_env

    load_project_env(REPO_ROOT)


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _read_whisperx_transcription(path: Path) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"WhisperX JSON not found at {path}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"WhisperX JSON is not valid JSON: {path}: {exc}") from exc

    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SystemExit(f"WhisperX JSON must contain a non-empty 'segments' array: {path}")

    segments: list[dict[str, Any]] = []
    for idx, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise SystemExit(f"WhisperX segment {idx} is not an object")
        text = segment.get("text")
        start = segment.get("start")
        end = segment.get("end")
        if not isinstance(text, str):
            raise SystemExit(f"WhisperX segment {idx} has no string 'text'")
        if not isinstance(start, int | float) or not isinstance(end, int | float):
            raise SystemExit(f"WhisperX segment {idx} must have numeric 'start' and 'end'")
        segments.append({
            "segment_index": idx,
            "start": float(start),
            "end": float(end),
            "text": text,
        })

    transcription = _normalize_ws(" ".join(segment["text"] for segment in segments))
    if not transcription:
        raise SystemExit(f"WhisperX JSON has empty segment transcription text: {path}")
    metadata = {
        key: value for key, value in payload.items()
        if key != "segments" and isinstance(value, str | int | float | bool | type(None))
    }
    return transcription, segments, metadata


def _schema() -> dict[str, Any]:
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


def _prompt(transcription: str) -> str:
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
        f"{transcription}"
    )


def _call_gemini(*, model: str, api_key: str, transcription: str) -> dict[str, Any]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": _prompt(transcription)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _schema(),
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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Gemini request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Gemini request failed: {exc}") from exc

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(
            "Gemini returned a malformed response:\n"
            + json.dumps(body, indent=2)[:4000],
        ) from exc


def _validate(input_text: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    output_text = _normalize_ws(" ".join(str(line.get("text", "")) for line in lines))
    valid = input_text == output_text
    result: dict[str, Any] = {
        "valid": valid,
        "input_char_count": len(input_text),
        "output_char_count": len(output_text),
        "line_count": len(lines),
    }
    if valid:
        return result

    limit = min(len(input_text), len(output_text))
    first_diff = next((i for i in range(limit) if input_text[i] != output_text[i]), limit)
    start = max(0, first_diff - 80)
    end = first_diff + 160
    result.update({
        "first_diff_char": first_diff,
        "input_near_diff": input_text[start:end],
        "output_near_diff": output_text[start:end],
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whisperx-json", type=Path, default=DEFAULT_WHISPERX_JSON)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default=os.environ.get("EDITOR_GENERATION_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)

    _load_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set in the environment or project .env")

    transcription, source_segments, source_metadata = _read_whisperx_transcription(args.whisperx_json)
    started = time.time()
    response = _call_gemini(
        model=args.model,
        api_key=api_key,
        transcription=transcription,
    )

    raw_lines = response.get("lines")
    if not isinstance(raw_lines, list):
        raise SystemExit("Gemini response did not contain a 'lines' array")
    lines = [
        {"line_index": int(item["line_index"]), "text": str(item["text"])}
        for item in raw_lines
        if isinstance(item, dict) and "line_index" in item and "text" in item
    ]
    if len(lines) != len(raw_lines):
        raise SystemExit("Gemini response contained malformed line items")

    validation = _validate(transcription, lines)
    payload = {
        "model": args.model,
        "created_at": time.time(),
        "latency_s": round(time.time() - started, 2),
        "valid": validation["valid"],
        "validation": validation,
        "source": {
            "whisperx_json": str(args.whisperx_json),
            "metadata": source_metadata,
            "segment_count": len(source_segments),
            "segments": source_segments,
        },
        "lines": lines,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    print(f"valid={payload['valid']} lines={len(lines)} latency_s={payload['latency_s']}")
    if not payload["valid"]:
        print("validation failed: output changed the transcription text", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
