"""Private-friendly Trading Agent HQ web server.

Serves dashboard/ and streams data/hq_events.jsonl as Server-Sent Events.
Default bind is localhost so an operator can put Cloudflare Access/reverse
proxy in front without exposing an unauthenticated dashboard.
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
EVENT_FILE = Path(os.getenv("HQ_EVENT_FILE", str(ROOT.parent / "data/hq_events.jsonl")))
HOST = os.getenv("HQ_HOST", "127.0.0.1")
PORT = int(os.getenv("HQ_PORT", "8787"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _headers(self, content_type: str, length: int | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/events":
            self._events()
            return
        if path == "/health":
            body = b'{"ok":true,"service":"trading-agent-hq"}'
            self._headers("application/json; charset=utf-8", len(body))
            self.wfile.write(body)
            self.wfile.flush()
            return
        if path == "/":
            path = "/index.html"
        if path.startswith("/"):
            path = path[1:]
        target = (ROOT / path).resolve()
        if ROOT not in target.parents and target != ROOT:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else (
            "text/css; charset=utf-8" if target.suffix == ".css" else
            "application/javascript; charset=utf-8" if target.suffix == ".js" else
            "application/octet-stream"
        )
        data = target.read_bytes()
        self._headers(content_type, len(data))
        self.wfile.write(data)
        self.wfile.flush()

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            EVENT_FILE.touch(exist_ok=True)
            with EVENT_FILE.open("r", encoding="utf-8") as handle:
                # Replay recent state first so a newly opened HQ is populated
                # immediately, then continue streaming only new events.
                recent = handle.readlines()[-1000:]
                for line in recent:
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.wfile.write(("data: " + line.strip() + "\n\n").encode("utf-8"))
                self.wfile.flush()
                handle.seek(0, 2)
                last_keepalive = time.monotonic()
                while True:
                    line = handle.readline()
                    if line:
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        self.wfile.write(("data: " + line.strip() + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                        continue
                    if time.monotonic() - last_keepalive >= 15:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_keepalive = time.monotonic()
                    time.sleep(0.5)

        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def log_message(self, fmt: str, *args) -> None:
        print("[hq]", fmt % args)


if __name__ == "__main__":
    print(f"[hq] serving on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
