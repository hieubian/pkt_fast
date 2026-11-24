"""Local development server for SimuLAN Studio."""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from pkt_builder import TopologyError, build_pkt_bytes, decode_request

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 1_500_000


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/export":
            self._json(200, {"ok": "true", "service": "simulan-pkt-export"})
            return
        if urlparse(self.path).path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/export":
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
        try:
            payload = decode_request(self.rfile.read(length))
            pkt_data = build_pkt_bytes(payload)
            name = str(payload.get("name") or "topology")
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:48] or "topology"
        except TopologyError as exc:
            self._json(400, {"error": str(exc)})
            return
        except RuntimeError as exc:
            self._json(503, {"error": str(exc)})
            return
        except Exception:
            self._json(422, {"error": "Không thể tạo file từ cấu hình này. Hãy kiểm tra model và cổng thiết bị."})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}.pkt"')
        self.send_header("Content-Length", str(len(pkt_data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(pkt_data)


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    print(f"SimuLAN Studio: http://{address[0]}:{address[1]}")
    print("Ctrl+C to stop.")
    ThreadingHTTPServer(address, Handler).serve_forever()

