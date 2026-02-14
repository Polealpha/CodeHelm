"""Local HTTP API server for status and iteration control."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .engine import ContinuousEngine


class _ControlHandler(BaseHTTPRequestHandler):
    engine: ContinuousEngine
    root: Path

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"ok": True})
            return

        if path == "/status":
            status_path = self.root / "AGENT_STATUS.md"
            payload = {
                "status_markdown": status_path.read_text(encoding="utf-8") if status_path.exists() else "",
                "features": [item.to_dict() for item in self.engine.list_features()],
                "iteration": self.engine.get_status().iteration,
            }
            self._send_json(200, payload)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/iterate":
            self._send_json(404, {"error": "not found"})
            return

        body = self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        report = self.engine.run_iteration(
            commit=bool(payload.get("commit", False)),
            dry_run=bool(payload.get("dry_run", False)),
        )
        self._send_json(200, report.to_dict())

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        # Keep CLI output concise for local control use.
        return

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(root: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Start local control service in foreground."""
    engine = ContinuousEngine(root=root)

    handler = type(
        "ControlHandler",
        (_ControlHandler,),
        {
            "engine": engine,
            "root": Path(root).resolve(),
        },
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"caasys server listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
