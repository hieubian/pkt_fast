"""Vercel Python Function: POST /api/export returns a Packet Tracer .pkt file."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlparse

from pkt_builder import handle

MAX_BODY_BYTES = 1_500_000


class handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._json(200, {"ok": "true", "service": "simulan-pkt-export"})

    def do_POST(self) -> None:
        if urlparse(self.path).path.rstrip("/") not in {"/api/export"}:
            self._json(404, {"error": "Không tìm thấy API."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Content-Length không hợp lệ."})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(413, {"error": "Yêu cầu trống hoặc vượt giới hạn 1,5 MB."})
            return
        status, ctype, body, filename = handle(self.rfile.read(length))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    print("This module runs as a Vercel Function; use server.py for local development.")

