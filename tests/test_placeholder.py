from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from caasys.engine import ContinuousEngine
from caasys.models import Feature
from caasys.storage import save_policy


class EngineSmokeTests(unittest.TestCase):
    def _workspace_temp_root(self) -> Path:
        base = Path(__file__).resolve().parent / ".tmp"
        base.mkdir(parents=True, exist_ok=True)
        root = base / f"case-{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_initialize_and_successful_iteration(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Ship MVP")

        engine.add_feature(
            Feature(
                id="F-001",
                category="smoke",
                description="Run success commands",
                priority=1,
                implementation_commands=['python -c "print(\'implement\')"'],
                verification_command='python -c "print(\'verify\')"',
            )
        )

        report = engine.run_iteration()
        self.assertTrue(report.success)
        self.assertEqual(report.feature_id, "F-001")
        self.assertIn("Iteration 1: completed F-001", engine.get_status().done)
        self.assertTrue(engine.list_features()[0].passes)
        self.assertTrue((root / "AGENT_STATUS.md").exists())

    def test_failed_iteration_records_blocker(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Handle failures")

        engine.add_feature(
            Feature(
                id="F-ERR",
                category="smoke",
                description="Fail implementation command",
                priority=1,
                implementation_commands=['python -c "import sys; sys.exit(2)"'],
                verification_command='python -c "print(\'should not run\')"',
            )
        )

        report = engine.run_iteration()
        status = engine.get_status()
        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("F-ERR" in blocker for blocker in status.blockers))

    def test_feature_without_commands_is_not_marked_done(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Reject empty features")

        engine.add_feature(
            Feature(
                id="F-EMPTY",
                category="smoke",
                description="No implementation or verification commands",
                priority=1,
            )
        )

        report = engine.run_iteration()
        status = engine.get_status()
        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("F-EMPTY" in blocker for blocker in status.blockers))

    def test_zero_ask_policy_is_persisted(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Policy test")

        policy = engine.get_policy()
        self.assertTrue(policy.zero_ask)
        self.assertTrue((root / "AGENT_POLICY.md").exists())

    def test_duplicate_feature_ids_are_auto_resolved_in_zero_ask_mode(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Duplicate handling")

        first = engine.add_feature(
            Feature(
                id="F-DUP",
                category="smoke",
                description="first",
                implementation_commands=["echo first"],
            )
        )
        second = engine.add_feature(
            Feature(
                id="F-DUP",
                category="smoke",
                description="second",
                implementation_commands=["echo second"],
            )
        )
        self.assertEqual(first.id, "F-DUP")
        self.assertEqual(second.id, "F-DUP-1")

    def test_quality_gate_detects_missing_required_context_file(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Gate failure")

        policy = engine.get_policy()
        policy.required_context_files = policy.required_context_files + ["MISSING_CONTEXT_FILE.md"]
        save_policy(root, policy)

        gate = engine.run_quality_gate(dry_run=True, run_smoke=False)
        self.assertFalse(gate.ok)
        self.assertTrue(any("MISSING_CONTEXT_FILE.md" in failure for failure in gate.failures))

    def test_parallel_iteration_completes_parallel_safe_features(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Parallel success")

        engine.add_feature(
            Feature(
                id="F-P1",
                category="parallel",
                description="parallel feature 1",
                priority=1,
                parallel_safe=True,
                implementation_commands=["echo p1"],
                verification_command="echo vp1",
            )
        )
        engine.add_feature(
            Feature(
                id="F-P2",
                category="parallel",
                description="parallel feature 2",
                priority=2,
                parallel_safe=True,
                implementation_commands=["echo p2"],
                verification_command="echo vp2",
            )
        )

        report = engine.run_parallel_iteration(team_count=2, max_features=2)
        self.assertTrue(report.success)
        self.assertEqual(len(report.team_results), 2)
        self.assertTrue(all(item.success for item in report.team_results))
        status = engine.get_status()
        self.assertTrue(any("F-P1" in item for item in status.done))
        self.assertTrue(any("F-P2" in item for item in status.done))

    def test_parallel_iteration_respects_parallel_safe_gate(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Parallel safety gate")

        engine.add_feature(
            Feature(
                id="F-NP",
                category="parallel",
                description="not parallel safe",
                priority=1,
                parallel_safe=False,
                implementation_commands=["echo np"],
                verification_command="echo vnp",
            )
        )

        report = engine.run_parallel_iteration(team_count=2, max_features=1, force_unsafe=False)
        self.assertFalse(report.success)
        self.assertEqual(report.selected_feature_ids, [])
        self.assertIn("parallel-safe", report.result)

    def test_run_project_loop_stops_when_all_features_pass(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Loop success")

        engine.add_feature(
            Feature(
                id="F-L1",
                category="loop",
                description="loop feature one",
                priority=1,
                implementation_commands=["echo l1"],
                verification_command="echo vl1",
            )
        )
        engine.add_feature(
            Feature(
                id="F-L2",
                category="loop",
                description="loop feature two",
                priority=2,
                implementation_commands=["echo l2"],
                verification_command="echo vl2",
            )
        )

        report = engine.run_project_loop(mode="single", max_iterations=10)
        self.assertTrue(report.success)
        self.assertEqual(report.stop_reason, "all_features_passed")
        self.assertGreaterEqual(report.final_passed_features, 2)
        self.assertLessEqual(report.iterations_executed, 3)

    def test_run_project_loop_stops_on_no_progress(self) -> None:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize("Loop stagnation")

        engine.add_feature(
            Feature(
                id="F-STUCK",
                category="loop",
                description="always fails",
                priority=1,
                implementation_commands=['python -c "import sys; sys.exit(2)"'],
                verification_command="echo never",
            )
        )
        policy = engine.get_policy()
        policy.max_no_progress_iterations = 2
        save_policy(root, policy)

        report = engine.run_project_loop(mode="single", max_iterations=5)
        self.assertFalse(report.success)
        self.assertEqual(report.stop_reason, "stagnation_no_progress")

    def test_browser_validation_http_backend(self) -> None:
        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = b"<html><body><h1>Dashboard Ready</h1></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            root = self._workspace_temp_root()
            engine = ContinuousEngine(root=root)
            engine.initialize("Browser validation")
            url = f"http://127.0.0.1:{server.server_port}/"
            report = engine.run_browser_validation(url=url, backend="http", expect_text="Dashboard Ready")
            self.assertTrue(report.success)
            self.assertEqual(report.backend, "http")
        finally:
            server.shutdown()
            server.server_close()

    def test_run_project_loop_with_browser_validation_before_stop(self) -> None:
        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = b"<html><body>Release Complete</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            root = self._workspace_temp_root()
            engine = ContinuousEngine(root=root)
            engine.initialize("Loop with browser stop check")
            engine.add_feature(
                Feature(
                    id="F-BSTOP",
                    category="loop",
                    description="pass quickly",
                    priority=1,
                    implementation_commands=["echo done"],
                    verification_command="echo vdone",
                )
            )

            policy = engine.get_policy()
            policy.require_browser_validation_before_stop = True
            policy.browser_validation_url = f"http://127.0.0.1:{server.server_port}/"
            policy.browser_validation_backend = "http"
            save_policy(root, policy)

            report = engine.run_project_loop(mode="single", max_iterations=5)
            self.assertTrue(report.success)
            self.assertEqual(report.stop_reason, "all_features_passed")
            self.assertIsNotNone(report.browser_validation)
            self.assertTrue(report.browser_validation.success)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
