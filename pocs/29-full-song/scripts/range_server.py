"""Minimal HTTP server that supports HTTP Range requests.

Python's stock http.server does NOT support byte-range requests — which
silently breaks audio/video seeking in the browser. The browser can only
seek if the server can return 206 Partial Content.
"""

from __future__ import annotations

import os
import re
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer


class RangeRequestHandler(SimpleHTTPRequestHandler):
    def send_head(self):  # type: ignore[override]
        path = self.translate_path(self.path.split("?", 1)[0])
        if os.path.isdir(path):
            return super().send_head()
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return None

        ctype = self.guess_type(path)
        file_size = os.path.getsize(path)
        rng = self.headers.get("Range")

        if not rng:
            # Normal 200 OK, but advertise ranges
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return open(path, "rb")

        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        if not m:
            self.send_error(400, "Invalid Range header")
            return None
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else file_size - 1
        if start >= file_size or end >= file_size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return None
        length = end - start + 1
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        # SimpleHTTPRequestHandler.copyfile copies the whole file; we need
        # only `length` bytes. Wrap it.
        class _LimitedReader:
            def __init__(self, inner, remaining):
                self._inner = inner
                self._remaining = remaining
            def read(self, n=-1):
                if self._remaining <= 0:
                    return b""
                chunk = self._inner.read(n if n > 0 and n < self._remaining else self._remaining)
                self._remaining -= len(chunk)
                return chunk
            def close(self):
                self._inner.close()
        return _LimitedReader(f, length)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.chdir(os.environ.get("SERVE_DIR", "."))
    server = ThreadingHTTPServer(("127.0.0.1", port), RangeRequestHandler)
    print(f"range-aware HTTP server on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")


if __name__ == "__main__":
    main()
