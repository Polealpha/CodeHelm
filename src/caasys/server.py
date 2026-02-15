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

        if path == "/policy":
            self._send_json(200, self.engine.get_policy().to_dict())
            return

        if path == "/quality-gate":
            report = self.engine.run_quality_gate(dry_run=False, run_smoke=True)
            self._send_json(200 if report.ok else 409, report.to_dict())
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {
            "/iterate",
            "/iterate-parallel",
            "/run-project",
            "/browser-validate",
            "/osworld-run",
            "/plan-task",
            "/set-model",
        }:
            self._send_json(404, {"error": "not found"})
            return

        body = self.rfile.read(int(self.headers.get("Content-Length", "0")) or 0)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        if path == "/iterate":
            report = self.engine.run_iteration(
                commit=bool(payload.get("commit", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            self._send_json(200, report.to_dict())
            return

        if path == "/plan-task":
            report = self.engine.plan_task(
                task_id=str(payload.get("task_id", "")),
                description=str(payload.get("description", "")),
                max_features=payload.get("max_features"),
                category=str(payload.get("category", "functional")),
                parallel_safe=bool(payload.get("parallel_safe", False)),
                dry_run=bool(payload.get("dry_run", False)),
                model=payload.get("model"),
                reasoning_effort=payload.get("reasoning_effort"),
            )
            self._send_json(200 if bool(report.get("success")) else 409, report)
            return

        if path == "/set-model":
            policy = self.engine.set_model_settings(
                cli_path=payload.get("cli_path"),
                implementation_backend=payload.get("implementation_backend"),
                model=payload.get("model"),
                reasoning_effort=payload.get("reasoning_effort"),
                ui_language=payload.get("ui_language"),
                sandbox_mode=payload.get("sandbox"),
                full_auto=payload.get("full_auto"),
                skip_git_repo_check=payload.get("skip_git_repo_check"),
                ephemeral=payload.get("ephemeral"),
                timeout_seconds=payload.get("timeout_seconds"),
                planner_sandbox_mode=payload.get("planner_sandbox"),
                planner_disable_shell_tool=payload.get("planner_disable_shell_tool"),
                planner_max_features_per_task=payload.get("planner_max_features"),
            )
            self._send_json(200, policy.to_dict())
            return

        if path == "/iterate-parallel":
            report = self.engine.run_parallel_iteration(
                team_count=payload.get("teams"),
                max_features=payload.get("max_features"),
                force_unsafe=bool(payload.get("force_unsafe", False)),
                commit=bool(payload.get("commit", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            self._send_json(200 if report.success else 409, report.to_dict())
            return

        if path == "/run-project":
            report = self.engine.run_project_loop(
                mode=str(payload.get("mode", "single")),
                max_iterations=payload.get("max_iterations"),
                team_count=payload.get("teams"),
                max_features=payload.get("max_features"),
                force_unsafe=bool(payload.get("force_unsafe", False)),
                commit=bool(payload.get("commit", False)),
                dry_run=bool(payload.get("dry_run", False)),
                browser_validate_on_stop=payload.get("browser_validate_on_stop"),
            )
            self._send_json(200 if report.success else 409, report.to_dict())
            return

        if path == "/browser-validate":
            report = self.engine.run_browser_validation(
                url=payload.get("url"),
                backend=payload.get("backend"),
                steps_file=payload.get("steps_file"),
                expect_text=payload.get("expect_text"),
                headless=payload.get("headless"),
                open_system_browser=payload.get("open_system_browser"),
                dry_run=bool(payload.get("dry_run", False)),
            )
            self._send_json(200 if report.success else 409, report.to_dict())
            return

        report = self.engine.run_osworld_mode(
            backend=payload.get("backend"),
            steps_file=payload.get("steps_file"),
            url=payload.get("url"),
            headless=payload.get("headless"),
            enable_desktop_control=payload.get("enable_desktop_control"),
            dry_run=bool(payload.get("dry_run", False)),
        )
        self._send_json(200 if report.success else 409, report.to_dict())

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
