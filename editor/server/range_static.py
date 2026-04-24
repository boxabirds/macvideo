"""Range-aware static file responder for FastAPI.

Python's default file serving doesn't emit `Accept-Ranges: bytes` or honour
`Range` request headers, which silently breaks audio/video seeking in the
browser (the preview.html saga). This module solves it once for the editor.
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse


_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")
_CHUNK_SIZE = 1 << 16  # 64 KiB


def _iterate_range(file_path: Path, start: int, length: int):
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk


def serve_file_with_ranges(request: Request, file_path: Path) -> Response:
    """Serve `file_path`, honouring an optional `Range: bytes=start-end` header."""
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"{file_path} not found")

    file_size = file_path.stat().st_size
    content_type, _ = mimetypes.guess_type(str(file_path))
    content_type = content_type or "application/octet-stream"

    rng_header = request.headers.get("range")
    if not rng_header:
        def full_file():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(_CHUNK_SIZE)
                    if not chunk:
                        return
                    yield chunk

        return StreamingResponse(
            full_file(),
            status_code=200,
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    m = _RANGE_RE.match(rng_header)
    if not m:
        raise HTTPException(status_code=400, detail="Invalid Range header")

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    if start >= file_size or end >= file_size or start > end:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    length = end - start + 1
    return StreamingResponse(
        _iterate_range(file_path, start, length),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
        },
    )
