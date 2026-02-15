from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from caasys.engine import ContinuousEngine
from caasys.agents import (
    CodexPlannerAgent,
    OperatorAgent,
    ShellExecutor,
    _adapt_verification_command_for_environment,
    _normalize_prompt_for_codex_exec,
)
from caasys.cli import (
    _attach_history_context,
    _build_history_context,
    build_parser,
    _extract_plan_failure_hint,
    _is_placeholder_fallback_plan,
    _normalize_language,
    _parse_iteration_mode_choice,
    _parse_manual_iteration_count,
    _resolve_history_target,
    main as cli_main,
)
from caasys.models import CommandResult, Feature
from caasys.storage import save_policy


class EngineSmokeTests(unittest.TestCase):
    def _workspace_temp_root(self) -> Path:
        base = Path(__file__).resolve().parent / ".tmp"
        base.mkdir(parents=True, exist_ok=True)
        root = base / f"case-{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _new_engine(self, objective: str, implementation_backend: str = "shell") -> tuple[ContinuousEngine, Path]:
        root = self._workspace_temp_root()
        engine = ContinuousEngine(root=root)
        engine.initialize(objective)
        policy = engine.get_policy()
        policy.implementation_backend = implementation_backend
        save_policy(root, policy)
        return engine, root

    def test_initialize_and_successful_iteration(self) -> None:
        engine, root = self._new_engine("Ship MVP")

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
        engine, root = self._new_engine("Handle failures")

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
        engine, root = self._new_engine("Reject empty features")

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
        engine, root = self._new_engine("Policy test")

        policy = engine.get_policy()
        self.assertTrue(policy.zero_ask)
        self.assertTrue((root / "AGENT_POLICY.md").exists())

    def test_duplicate_feature_ids_are_auto_resolved_in_zero_ask_mode(self) -> None:
        engine, root = self._new_engine("Duplicate handling")

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
        engine, root = self._new_engine("Gate failure")

        policy = engine.get_policy()
        policy.required_context_files = policy.required_context_files + ["MISSING_CONTEXT_FILE.md"]
        save_policy(root, policy)

        gate = engine.run_quality_gate(dry_run=True, run_smoke=False)
        self.assertFalse(gate.ok)
        self.assertTrue(any("MISSING_CONTEXT_FILE.md" in failure for failure in gate.failures))

    def test_parallel_iteration_completes_parallel_safe_features(self) -> None:
        engine, root = self._new_engine("Parallel success")

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
        engine, root = self._new_engine("Parallel safety gate")
        policy = engine.get_policy()
        policy.require_parallel_safe_flag = True
        save_policy(root, policy)

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
        engine, root = self._new_engine("Loop success")

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
        engine, root = self._new_engine("Loop stagnation")

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
        policy.auto_handoff_enabled = False
        save_policy(root, policy)

        report = engine.run_project_loop(mode="single", max_iterations=5)
        self.assertFalse(report.success)
        self.assertEqual(report.stop_reason, "stagnation_no_progress")

    def test_run_project_loop_iteration_is_full_epoch_in_single_mode(self) -> None:
        engine, root = self._new_engine("Loop epoch semantics single")

        engine.add_feature(
            Feature(
                id="F-EPOCH-FAIL",
                category="loop",
                description="fails but should not block rest of epoch",
                priority=1,
                implementation_commands=['python -c "import sys; sys.exit(2)"'],
            )
        )
        engine.add_feature(
            Feature(
                id="F-EPOCH-OK",
                category="loop",
                description="still runs in same epoch",
                priority=2,
                implementation_commands=["echo ok"],
                verification_command="echo vok",
            )
        )

        report = engine.run_project_loop(mode="single", max_iterations=1)
        self.assertEqual(report.iterations_executed, 1)
        feature_state = {item.id: item.passes for item in engine.list_features()}
        self.assertFalse(feature_state["F-EPOCH-FAIL"])
        self.assertTrue(feature_state["F-EPOCH-OK"])
        self.assertEqual(
            report.reports[0]["attempted_feature_ids"],
            ["F-EPOCH-FAIL", "F-EPOCH-OK"],
        )

    def test_run_project_loop_parallel_epoch_can_skip_unsafe_and_continue(self) -> None:
        engine, root = self._new_engine("Loop epoch semantics parallel")
        policy = engine.get_policy()
        policy.enable_parallel_teams = True
        policy.require_parallel_safe_flag = True
        policy.max_parallel_features_per_iteration = 1
        save_policy(root, policy)

        engine.add_feature(
            Feature(
                id="F-P-UNSAFE",
                category="parallel",
                description="unsafe and should be skipped",
                priority=1,
                parallel_safe=False,
                implementation_commands=["echo unsafe"],
            )
        )
        engine.add_feature(
            Feature(
                id="F-P-SAFE",
                category="parallel",
                description="safe work in same epoch",
                priority=2,
                parallel_safe=True,
                implementation_commands=["echo safe"],
                verification_command="echo vsafe",
            )
        )

        report = engine.run_project_loop(mode="parallel", max_iterations=1, team_count=1, max_features=1)
        self.assertEqual(report.iterations_executed, 1)
        feature_state = {item.id: item.passes for item in engine.list_features()}
        self.assertFalse(feature_state["F-P-UNSAFE"])
        self.assertTrue(feature_state["F-P-SAFE"])

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
            engine, root = self._new_engine("Browser validation")
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
            engine, root = self._new_engine("Loop with browser stop check")
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

    def test_auto_handoff_triggers_and_records_summary(self) -> None:
        engine, root = self._new_engine("Handoff trigger")
        engine.add_feature(
            Feature(
                id="F-HAND",
                category="loop",
                description="fails to force no progress",
                priority=1,
                implementation_commands=['python -c "import sys; sys.exit(2)"'],
            )
        )

        policy = engine.get_policy()
        policy.handoff_on_no_progress_iterations = 1
        policy.handoff_after_iterations = 100
        policy.handoff_context_char_threshold = 1_000_000
        save_policy(root, policy)

        report = engine.run_project_loop(mode="single", max_iterations=2, dry_run=False)
        self.assertGreaterEqual(len(report.handoff_events), 1)
        summary_path = Path(report.handoff_events[0]["summary_file"])
        self.assertTrue(summary_path.exists())

    def test_osworld_mode_dry_run(self) -> None:
        engine, root = self._new_engine("OSWorld dry run")

        steps_path = root / ".caasys" / "osworld_steps.json"
        steps_path.parent.mkdir(parents=True, exist_ok=True)
        steps_path.write_text(
            json.dumps(
                [
                    {"action": "goto", "url": "http://127.0.0.1:3000"},
                    {"action": "click", "selector": "text=Login"},
                ]
            ),
            encoding="utf-8",
        )

        policy = engine.get_policy()
        policy.osworld_steps_file = str(steps_path)
        save_policy(root, policy)

        report = engine.run_osworld_mode(backend="auto", dry_run=True)
        self.assertTrue(report.success)
        self.assertGreaterEqual(len(report.actions), 1)

    def test_codex_backend_can_execute_feature_without_impl_commands_in_dry_run(self) -> None:
        engine, root = self._new_engine("Codex backend dry run", implementation_backend="codex")
        engine.add_feature(
            Feature(
                id="F-CDX",
                category="codex",
                description="Implement a tiny change using codex backend",
                priority=1,
            )
        )

        report = engine.run_iteration(dry_run=True)
        self.assertTrue(report.success)
        self.assertEqual(report.feature_id, "F-CDX")
        self.assertTrue(engine.list_features()[0].passes)
        self.assertEqual(engine.get_active_workers(), [])

    def test_codex_acknowledgement_response_is_not_counted_as_success(self) -> None:
        engine, root = self._new_engine("Codex noop guard", implementation_backend="codex")
        engine.add_feature(
            Feature(
                id="F-CDX-NOOP",
                category="codex",
                description="Create API and tests",
                priority=1,
            )
        )
        fake_results = [
            CommandResult(
                command="codex.cmd exec ...",
                exit_code=0,
                stdout="Operating in autonomous coding mode. Provide the next work item.",
                stderr="",
                duration_seconds=0.01,
                phase="implement-codex",
            )
        ]

        with patch("caasys.engine.CodexProgrammerAgent.implement", return_value=fake_results):
            report = engine.run_iteration(dry_run=False)

        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("acknowledgement/no-op" in item for item in engine.get_status().blockers))

    def test_codex_success_without_repo_changes_is_not_counted_as_success(self) -> None:
        engine, root = self._new_engine("Codex workspace guard", implementation_backend="codex")
        engine.add_feature(
            Feature(
                id="F-CDX-UNCHANGED",
                category="codex",
                description="Implement a tiny API",
                priority=1,
            )
        )
        fake_results = [
            CommandResult(
                command="codex.cmd exec ...",
                exit_code=0,
                stdout="Implemented feature and completed checks.",
                stderr="",
                duration_seconds=0.01,
                phase="implement-codex",
            )
        ]

        with patch("caasys.engine.CodexProgrammerAgent.implement", return_value=fake_results):
            report = engine.run_iteration(dry_run=False)

        self.assertFalse(report.success)
        self.assertFalse(engine.list_features()[0].passes)
        self.assertTrue(any("no repository file changes" in item for item in engine.get_status().blockers))

    def test_codex_success_with_repo_changes_can_pass(self) -> None:
        engine, root = self._new_engine("Codex workspace changed", implementation_backend="codex")
        engine.add_feature(
            Feature(
                id="F-CDX-CHANGED",
                category="codex",
                description="Create project skeleton",
                priority=1,
            )
        )

        def _fake_implement(*args, **kwargs):
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            return [
                CommandResult(
                    command="codex.cmd exec ...",
                    exit_code=0,
                    stdout="Implemented and wrote files.",
                    stderr="",
                    duration_seconds=0.01,
                    phase="implement-codex",
                )
            ]

        with patch("caasys.engine.CodexProgrammerAgent.implement", side_effect=_fake_implement):
            report = engine.run_iteration(dry_run=False)

        self.assertTrue(report.success)
        self.assertTrue(engine.list_features()[0].passes)

    def test_plan_task_dry_run_returns_planned_features(self) -> None:
        engine, root = self._new_engine("Planner dry run")
        report = engine.plan_task(
            task_id="T-PLAN",
            description="Build a notifications center with unread counter",
            max_features=3,
            parallel_safe=True,
            dry_run=True,
        )
        self.assertTrue(report["success"])
        self.assertTrue(report["dry_run"])
        self.assertEqual(len(report["feature_ids"]), 3)
        self.assertEqual(len(engine.list_features()), 0)

    def test_codex_planner_falls_back_when_subprocess_fails(self) -> None:
        root = self._workspace_temp_root()
        planner = CodexPlannerAgent(
            cli_path="definitely-missing-codex-cli",
            model="gpt-5.3-codex",
            reasoning_effort="xhigh",
            sandbox_mode="read-only",
            full_auto=True,
            skip_git_repo_check=True,
            ephemeral=False,
            disable_shell_tool=True,
            timeout_seconds=5,
        )
        features, result, planner_output, used_fallback = planner.plan_task(
            task_id="T-FAIL",
            task_description="Build a small API",
            cwd=root,
            max_features=3,
            default_category="functional",
            parallel_safe_default=True,
            objective="Planner fallback test",
            dry_run=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(used_fallback)
        self.assertEqual(len(features), 3)
        self.assertTrue(planner_output)
        self.assertTrue(any(item.implementation_commands for item in features))
        self.assertTrue(all(item.verification_command for item in features))

    def test_extract_plan_failure_hint_prefers_stderr(self) -> None:
        hint = _extract_plan_failure_hint(
            {
                "success": False,
                "command_results": [
                    {
                        "exit_code": 2,
                        "stderr": "Not inside a trusted directory.\nUse --skip-git-repo-check.",
                        "stdout": "",
                    }
                ],
            }
        )
        self.assertIn("trusted directory", hint.lower())

    def test_normalize_prompt_for_codex_exec_flattens_multiline(self) -> None:
        raw = "line one\n\nline two\n  line three  \n"
        normalized = _normalize_prompt_for_codex_exec(raw)
        self.assertEqual(normalized, "line one | line two | line three")
        self.assertNotIn("\n", normalized)

    def test_adapt_verification_command_strips_docker_segments(self) -> None:
        raw = (
            "docker compose up -d --build && .\\.venv\\Scripts\\pytest tests/test_api.py -q "
            "&& docker compose down"
        )
        adapted = _adapt_verification_command_for_environment(raw, docker_available=False)
        self.assertNotIn("docker compose up", adapted.lower())
        self.assertNotIn("docker compose down", adapted.lower())
        self.assertIn("pytest tests/test_api.py -q", adapted)

    def test_placeholder_fallback_plan_detector(self) -> None:
        self.assertTrue(
            _is_placeholder_fallback_plan(
                {
                    "features": [
                        {"implementation_commands": [], "verification_command": None},
                        {"implementation_commands": [], "verification_command": ""},
                    ]
                }
            )
        )
        self.assertFalse(
            _is_placeholder_fallback_plan(
                {
                    "features": [
                        {
                            "implementation_commands": ["create project scaffold"],
                            "verification_command": None,
                        }
                    ]
                }
            )
        )

    def test_set_model_settings_updates_policy(self) -> None:
        engine, root = self._new_engine("Model settings update")
        updated = engine.set_model_settings(
            cli_path="codex",
            implementation_backend="auto",
            model="gpt-5.3-codex",
            reasoning_effort="high",
            ui_language="zh",
            sandbox_mode="workspace-write",
            full_auto=False,
            skip_git_repo_check=True,
            ephemeral=True,
            timeout_seconds=1200,
            planner_sandbox_mode="read-only",
            planner_disable_shell_tool=True,
            planner_max_features_per_task=6,
        )
        self.assertEqual(updated.implementation_backend, "auto")
        self.assertEqual(updated.codex_cli_path, "codex")
        self.assertEqual(updated.codex_model, "gpt-5.3-codex")
        self.assertEqual(updated.codex_reasoning_effort, "high")
        self.assertEqual(updated.ui_language, "zh")
        self.assertFalse(updated.codex_full_auto)
        self.assertTrue(updated.codex_skip_git_repo_check)
        self.assertTrue(updated.codex_ephemeral)
        self.assertEqual(updated.codex_timeout_seconds, 1200)
        self.assertEqual(updated.planner_sandbox_mode, "read-only")
        self.assertTrue(updated.planner_disable_shell_tool)
        self.assertEqual(updated.planner_max_features_per_task, 6)

        persisted = engine.get_policy()
        self.assertEqual(persisted.codex_reasoning_effort, "high")
        self.assertEqual(persisted.implementation_backend, "auto")
        self.assertEqual(persisted.ui_language, "zh")

    def test_normalize_language_aliases(self) -> None:
        self.assertEqual(_normalize_language("en"), "en")
        self.assertEqual(_normalize_language("English"), "en")
        self.assertEqual(_normalize_language("\u4e2d\u6587"), "zh")
        self.assertEqual(_normalize_language("zh-cn"), "zh")
        self.assertIsNone(_normalize_language("jp"))

    def test_parse_iteration_mode_choice(self) -> None:
        self.assertEqual(_parse_iteration_mode_choice(""), "auto")
        self.assertEqual(_parse_iteration_mode_choice("1"), "auto")
        self.assertEqual(_parse_iteration_mode_choice("auto"), "auto")
        self.assertEqual(_parse_iteration_mode_choice("2"), "manual")
        self.assertEqual(_parse_iteration_mode_choice("manual"), "manual")
        self.assertEqual(_parse_iteration_mode_choice("manual "), "manual")
        self.assertEqual(_parse_iteration_mode_choice("\u624b\u52a8"), "manual")
        self.assertIsNone(_parse_iteration_mode_choice("x"))

    def test_parse_manual_iteration_count(self) -> None:
        self.assertEqual(_parse_manual_iteration_count("5"), 5)
        self.assertEqual(_parse_manual_iteration_count(" 12 "), 12)
        self.assertIsNone(_parse_manual_iteration_count(""))
        self.assertIsNone(_parse_manual_iteration_count("0"))
        self.assertIsNone(_parse_manual_iteration_count("-3"))
        self.assertIsNone(_parse_manual_iteration_count("abc"))

    def test_build_history_context_and_attach(self) -> None:
        context = _build_history_context(
            {
                "src/a.py": "[file] src/a.py\n[recent_commits]\nabc first change",
                "src/b.py": "[file] src/b.py\n[current_file_tail]\nprint('ok')",
            }
        )
        self.assertIn("[history:src/a.py]", context)
        self.assertIn("[history:src/b.py]", context)

        attached = _attach_history_context(
            task_description="Implement trading API",
            history_context=context,
            language="en",
        )
        self.assertIn("Implement trading API", attached)
        self.assertIn("Supplemental project history context", attached)
        self.assertIn("[history:src/a.py]", attached)

    def test_resolve_history_target_rejects_outside_workspace(self) -> None:
        root = self._workspace_temp_root()
        inside = root / "inside.txt"
        inside.write_text("ok\n", encoding="utf-8")
        outside = root.parent / f"outside-{uuid4().hex}.txt"
        outside.write_text("no\n", encoding="utf-8")
        try:
            resolved_inside = _resolve_history_target(root=root, raw_path="inside.txt")
            self.assertEqual(resolved_inside, inside.resolve())
            resolved_outside = _resolve_history_target(root=root, raw_path=str(outside))
            self.assertIsNone(resolved_outside)
        finally:
            if outside.exists():
                outside.unlink()

    def test_operator_verify_falls_back_when_docker_missing(self) -> None:
        class _FakeExecutor(ShellExecutor):
            def run(self, command: str, cwd: Path, phase: str, timeout_seconds: int = 120):  # type: ignore[override]
                if "docker compose" in command.lower():
                    return CommandResult(
                        command=command,
                        exit_code=1,
                        stdout="",
                        stderr="'docker' is not recognized as an internal or external command",
                        duration_seconds=0.01,
                        phase=phase,
                    )
                return CommandResult(
                    command=command,
                    exit_code=0,
                    stdout="pytest ok",
                    stderr="",
                    duration_seconds=0.01,
                    phase=phase,
                )

        operator = OperatorAgent(executor=_FakeExecutor(), retry_once=True)
        feature = Feature(
            id="F-DOCKER",
            category="non-functional",
            description="verification with docker wrapper",
            verification_command=(
                "docker compose up -d --build && .\\.venv\\Scripts\\pytest tests/test_a.py -q "
                "&& docker compose down"
            ),
        )
        results = operator.verify(feature=feature, cwd=Path("."))
        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(all(item.exit_code == 0 for item in results))
        self.assertTrue(any(item.phase == "verify-no-docker" for item in results))

    def test_interactive_parallel_safe_default_enabled(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["interactive"])
        self.assertTrue(args.parallel_safe)

    def test_interactive_no_parallel_safe_override(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["interactive", "--no-parallel-safe"])
        self.assertFalse(args.parallel_safe)

    def test_interactive_once_mode_accepts_direct_task_text(self) -> None:
        root = self._workspace_temp_root()
        init_code = cli_main(["--root", str(root), "init", "--objective", "Interactive once mode"])
        self.assertEqual(init_code, 0)
        run_code = cli_main(
            [
                "--root",
                str(root),
                "interactive",
                "--once",
                "Create a minimal endpoint",
                "--no-auto-run",
                "--dry-run",
                "--max-features",
                "3",
            ]
        )
        self.assertEqual(run_code, 0)

    def test_agents_command_returns_without_error(self) -> None:
        root = self._workspace_temp_root()
        init_code = cli_main(["--root", str(root), "init", "--objective", "Agents command test"])
        self.assertEqual(init_code, 0)
        agents_code = cli_main(["--root", str(root), "agents", "--json", "--limit", "5"])
        self.assertEqual(agents_code, 0)

    def test_agents_command_all_scope_returns_without_error(self) -> None:
        root = self._workspace_temp_root()
        init_code = cli_main(["--root", str(root), "init", "--objective", "Agents all command test"])
        self.assertEqual(init_code, 0)
        agents_code = cli_main(["--root", str(root), "agents", "--all", "--json", "--limit", "5"])
        self.assertEqual(agents_code, 0)

    def test_set_model_ui_language_via_cli(self) -> None:
        root = self._workspace_temp_root()
        init_code = cli_main(["--root", str(root), "init", "--objective", "Set language via cli"])
        self.assertEqual(init_code, 0)
        set_code = cli_main(["--root", str(root), "set-model", "--ui-language", "zh"])
        self.assertEqual(set_code, 0)
        engine = ContinuousEngine(root=root)
        self.assertEqual(engine.get_policy().ui_language, "zh")

    def test_active_worker_role_numbering(self) -> None:
        engine, _ = self._new_engine("Role numbering check")
        engine._register_worker_activity(worker_key="w-prog-1", role="Programmer", feature_id="F-1")
        engine._register_worker_activity(worker_key="w-prog-2", role="Programmer", feature_id="F-2")
        engine._register_worker_activity(worker_key="w-op-1", role="Operator", feature_id="F-1")
        workers = engine.get_active_workers()
        role_ids = {str(item.get("worker_key")): str(item.get("role_id")) for item in workers}
        self.assertEqual(role_ids["w-prog-1"], "PRG-01")
        self.assertEqual(role_ids["w-prog-2"], "PRG-02")
        self.assertEqual(role_ids["w-op-1"], "OPS-01")
        engine._unregister_worker_activity("w-prog-1")
        engine._unregister_worker_activity("w-prog-2")
        engine._unregister_worker_activity("w-op-1")
        self.assertEqual(engine.get_active_workers(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
