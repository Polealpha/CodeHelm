"""Iteration engine implementing PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> NEXT."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
from pathlib import Path
from threading import Lock
from time import time

from .agents import (
    CodexPlannerAgent,
    CodexProgrammerAgent,
    OperatorAgent,
    ProgrammerAgent,
    ShellExecutor,
)
from .browser import BrowserValidator, OSWorldRunner
from .models import (
    AgentPolicy,
    AgentStatus,
    BrowserValidationReport,
    CommandResult,
    Feature,
    HandoffReport,
    HygieneReport,
    IterationReport,
    OSWorldRunReport,
    ParallelIterationReport,
    ProjectRunReport,
    StopDecision,
    TeamExecutionResult,
)
from .orchestrator import Orchestrator
from .storage import (
    append_progress,
    load_features,
    load_policy,
    load_status,
    read_progress_tail,
    save_features,
    save_policy,
    save_status,
)


class ContinuousEngine:
    """Main entry point for initializing and running autonomous iterations."""

    def __init__(
        self,
        root: str | Path,
        policy: AgentPolicy | None = None,
        orchestrator: Orchestrator | None = None,
        programmer: ProgrammerAgent | None = None,
        operator: OperatorAgent | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.policy = policy or load_policy(self.root)
        self.orchestrator = orchestrator or Orchestrator(policy=self.policy)
        self.programmer = programmer or ProgrammerAgent(retry_once=self.policy.retry_failed_commands_once)
        self.operator = operator or OperatorAgent(retry_once=self.policy.retry_failed_commands_once)
        self._executor = ShellExecutor()
        self._browser_validator = BrowserValidator()
        self._osworld_runner = OSWorldRunner()
        self._activity_lock = Lock()
        self._active_workers: dict[str, dict[str, object]] = {}
        self._worker_identity_numbers: dict[str, int] = {}
        self._worker_role_numbers: dict[tuple[str, str], int] = {}
        self._next_role_identity_by_role: dict[str, int] = {}
        self._next_worker_identity = 1
        self._sync_runtime_policy()

    def _register_worker_activity(
        self,
        *,
        worker_key: str,
        role: str,
        feature_id: str | None = None,
        team_id: str | None = None,
        task_id: str | None = None,
        model: str | None = None,
        backend: str | None = None,
    ) -> None:
        with self._activity_lock:
            number = self._worker_identity_numbers.get(worker_key)
            if number is None:
                number = self._next_worker_identity
                self._worker_identity_numbers[worker_key] = number
                self._next_worker_identity += 1
            role_key = (role, worker_key)
            role_number = self._worker_role_numbers.get(role_key)
            if role_number is None:
                role_number = self._next_role_identity_by_role.get(role, 1)
                self._worker_role_numbers[role_key] = role_number
                self._next_role_identity_by_role[role] = role_number + 1
            self._active_workers[worker_key] = {
                "worker_key": worker_key,
                "ai_id": f"AI-{number:02d}",
                "number": number,
                "role": role,
                "role_id": _format_role_identity(role=role, number=role_number),
                "role_number": role_number,
                "feature_id": feature_id or "",
                "team_id": team_id or "",
                "task_id": task_id or "",
                "model": model or "",
                "backend": backend or "",
                "started_at": time(),
            }

    def _unregister_worker_activity(self, worker_key: str) -> None:
        with self._activity_lock:
            self._active_workers.pop(worker_key, None)

    def get_active_workers(self) -> list[dict[str, object]]:
        with self._activity_lock:
            workers = [dict(item) for item in self._active_workers.values()]
        workers.sort(key=lambda item: int(item.get("number", 0)))
        return workers

    def _sync_runtime_policy(self) -> None:
        self.orchestrator.policy = self.policy
        self.programmer._retry_once = self.policy.retry_failed_commands_once
        self.operator._retry_once = self.policy.retry_failed_commands_once

    def initialize(self, objective: str, zero_ask: bool | None = None) -> AgentStatus:
        self.root.mkdir(parents=True, exist_ok=True)
        policy = load_policy(self.root)
        if zero_ask is not None:
            policy.zero_ask = zero_ask
        if not (self.root / "tests").exists():
            policy.run_smoke_before_iteration = False
            policy.smoke_test_command = None
        save_policy(self.root, policy)
        self.policy = policy
        self._sync_runtime_policy()

        status = load_status(self.root)
        status.current_objective = objective.strip()
        status.in_progress = ["System initialized and ready for Iteration 1."]
        status.next_steps = ["Add or review feature_list.json, then run `caasys iterate`."]
        status.last_command_summary = [f"Initialization completed. zero_ask={str(self.policy.zero_ask).lower()}"]
        status.last_test_summary = "No tests executed yet."
        save_status(self.root, status)

        if not (self.root / "feature_list.json").exists():
            save_features(self.root, [])
        append_progress(
            self.root,
            f"Initialized objective: {status.current_objective} (zero_ask={str(self.policy.zero_ask).lower()})",
        )
        return status

    def add_feature(self, feature: Feature) -> Feature:
        features = load_features(self.root)
        existing_ids = {item.id for item in features}
        if feature.id in existing_ids:
            if self.policy.zero_ask and self.policy.auto_resolve_duplicate_feature_ids:
                original = feature.id
                feature.id = self._resolve_feature_id(original, existing_ids)
                append_progress(self.root, f"Auto-resolved duplicate feature id: {original} -> {feature.id}")
            else:
                raise ValueError(f"Feature '{feature.id}' already exists")
        features.append(feature)
        save_features(self.root, features)
        append_progress(self.root, f"Feature added: {feature.id}")
        return feature

    def _resolve_feature_id(self, base_id: str, existing_ids: set[str]) -> str:
        index = 1
        candidate = f"{base_id}-{index}"
        while candidate in existing_ids:
            index += 1
            candidate = f"{base_id}-{index}"
        return candidate

    def list_features(self) -> list[Feature]:
        return load_features(self.root)

    def get_status(self) -> AgentStatus:
        return load_status(self.root)

    def get_policy(self) -> AgentPolicy:
        self.policy = load_policy(self.root)
        self._sync_runtime_policy()
        return self.policy

    def set_model_settings(
        self,
        *,
        cli_path: str | None = None,
        implementation_backend: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        ui_language: str | None = None,
        sandbox_mode: str | None = None,
        full_auto: bool | None = None,
        skip_git_repo_check: bool | None = None,
        ephemeral: bool | None = None,
        timeout_seconds: int | None = None,
        planner_sandbox_mode: str | None = None,
        planner_disable_shell_tool: bool | None = None,
        planner_max_features_per_task: int | None = None,
    ) -> AgentPolicy:
        policy = self.get_policy()
        if cli_path is not None:
            policy.codex_cli_path = cli_path.strip()
        if implementation_backend is not None:
            policy.implementation_backend = implementation_backend.strip().lower()
        if model is not None:
            policy.codex_model = model.strip()
        if reasoning_effort is not None:
            policy.codex_reasoning_effort = reasoning_effort.strip()
        if ui_language is not None:
            normalized = ui_language.strip().lower()
            if normalized in {"en", "english", "en-us"}:
                policy.ui_language = "en"
            elif normalized in {"zh", "zh-cn", "cn", "chinese", "中文"}:
                policy.ui_language = "zh"
        if sandbox_mode is not None:
            policy.codex_sandbox_mode = sandbox_mode.strip()
        if full_auto is not None:
            policy.codex_full_auto = full_auto
        if skip_git_repo_check is not None:
            policy.codex_skip_git_repo_check = skip_git_repo_check
        if ephemeral is not None:
            policy.codex_ephemeral = ephemeral
        if timeout_seconds is not None:
            policy.codex_timeout_seconds = max(30, timeout_seconds)
        if planner_sandbox_mode is not None:
            policy.planner_sandbox_mode = planner_sandbox_mode.strip()
        if planner_disable_shell_tool is not None:
            policy.planner_disable_shell_tool = planner_disable_shell_tool
        if planner_max_features_per_task is not None:
            policy.planner_max_features_per_task = max(1, planner_max_features_per_task)

        save_policy(self.root, policy)
        self.policy = policy
        self._sync_runtime_policy()
        append_progress(
            self.root,
            "Model settings updated: "
            f"backend={policy.implementation_backend}, model={policy.codex_model}, "
            f"reasoning_effort={policy.codex_reasoning_effort}, ui_language={policy.ui_language}",
        )
        return policy

    def plan_task(
        self,
        *,
        task_id: str,
        description: str,
        max_features: int | None = None,
        category: str = "functional",
        parallel_safe: bool = False,
        dry_run: bool = False,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, object]:
        normalized_task_id = task_id.strip()
        normalized_description = description.strip()
        if not normalized_task_id or not normalized_description:
            return {
                "task_id": task_id,
                "success": False,
                "message": "task_id and description are required.",
                "feature_ids": [],
                "features": [],
                "dry_run": dry_run,
                "used_fallback_plan": False,
                "command_results": [],
                "planner_output": "",
            }

        policy = self.get_policy()
        status = self.get_status()
        planner = CodexPlannerAgent(
            cli_path=policy.codex_cli_path,
            model=model or policy.codex_model,
            reasoning_effort=reasoning_effort or policy.codex_reasoning_effort,
            sandbox_mode=policy.planner_sandbox_mode,
            full_auto=policy.codex_full_auto,
            skip_git_repo_check=policy.codex_skip_git_repo_check,
            ephemeral=policy.codex_ephemeral,
            disable_shell_tool=policy.planner_disable_shell_tool,
            timeout_seconds=policy.codex_timeout_seconds,
        )
        resolved_max_features = max_features or policy.planner_max_features_per_task
        resolved_max_features = max(1, resolved_max_features)
        planner_worker_key = f"planner:{normalized_task_id}"
        self._register_worker_activity(
            worker_key=planner_worker_key,
            role="Planner",
            task_id=normalized_task_id,
            model=model or policy.codex_model,
            backend="codex",
        )
        try:
            planned_features, planner_result, planner_output, used_fallback = planner.plan_task(
                task_id=normalized_task_id,
                task_description=normalized_description,
                cwd=self.root,
                max_features=resolved_max_features,
                default_category=category.strip() or "functional",
                parallel_safe_default=parallel_safe,
                objective=status.current_objective,
                dry_run=dry_run,
            )
        finally:
            self._unregister_worker_activity(planner_worker_key)

        if not planned_features:
            return {
                "task_id": task_id,
                "success": False,
                "message": "Planner did not return any features.",
                "feature_ids": [],
                "features": [],
                "dry_run": dry_run,
                "used_fallback_plan": used_fallback,
                "command_results": [planner_result.to_dict()],
                "planner_output": planner_output,
            }

        created_features: list[Feature] = []
        if dry_run:
            created_features = planned_features
        else:
            for feature in planned_features:
                created_features.append(self.add_feature(feature))
            append_progress(
                self.root,
                f"Task planned: {normalized_task_id} -> {', '.join(item.id for item in created_features)}",
            )

        return {
            "task_id": normalized_task_id,
            "success": True,
            "message": (
                f"Planned {len(created_features)} features from task {normalized_task_id}."
                + (" (dry-run)" if dry_run else "")
                + (" Fallback plan used." if used_fallback else "")
            ),
            "feature_ids": [item.id for item in created_features],
            "features": [item.to_dict() for item in created_features],
            "dry_run": dry_run,
            "used_fallback_plan": used_fallback,
            "command_results": [planner_result.to_dict()],
            "planner_output": planner_output,
        }

    def bootstrap_session(self, dry_run: bool = False) -> tuple[list[str], list[CommandResult]]:
        """Collect lightweight state to reduce context drift across sessions."""
        status = load_status(self.root)
        features = load_features(self.root)
        pending_count = len([item for item in features if not item.passes])
        done_count = len(features) - pending_count
        notes = [
            f"cwd: {self.root}",
            f"iteration: {status.iteration}",
            f"features: pending={pending_count}, done={done_count}",
        ]
        tail = read_progress_tail(self.root, lines=5)
        if tail:
            notes.append(f"progress_tail: {tail[-1]}")

        command_results: list[CommandResult] = []
        if (self.root / "git-data").exists() or (self.root / ".git").exists():
            if dry_run:
                command_results.append(
                    CommandResult(
                        command="git log --oneline -5",
                        exit_code=0,
                        stdout="dry-run: git log skipped",
                        stderr="",
                        duration_seconds=0.0,
                        phase="bootstrap",
                    )
                )
            else:
                command_results.append(
                    self._executor.run(command="git log --oneline -5", cwd=self.root, phase="bootstrap")
                )
        return notes, command_results

    def run_quality_gate(self, dry_run: bool = False, run_smoke: bool | None = None) -> HygieneReport:
        """Validate anti-context-rot checks before starting a new feature."""
        policy = self.get_policy()
        checks: list[str] = []
        failures: list[str] = []
        command_results: list[CommandResult] = []

        for required in policy.required_context_files:
            required_path = self.root / required
            if required_path.exists():
                checks.append(f"required file present: {required}")
            else:
                if self._restore_required_context_file(required):
                    checks.append(f"required file restored: {required}")
                else:
                    failures.append(f"required file missing: {required}")

        features = load_features(self.root)
        ids = [item.id for item in features]
        if len(ids) != len(set(ids)):
            failures.append("feature_list.json contains duplicate feature ids")
        else:
            checks.append("feature ids are unique")

        status = load_status(self.root)
        if status.in_progress and status.iteration > 0:
            failures.append("status has non-empty In Progress from previous run (possible interrupted iteration)")
        else:
            checks.append("status has no stale In Progress entries")

        should_run_smoke = policy.run_smoke_before_iteration if run_smoke is None else run_smoke
        if should_run_smoke and policy.smoke_test_command:
            if dry_run:
                command_results.append(
                    CommandResult(
                        command=policy.smoke_test_command,
                        exit_code=0,
                        stdout="dry-run: smoke test skipped",
                        stderr="",
                        duration_seconds=0.0,
                        phase="quality-gate",
                    )
                )
                checks.append("smoke test dry-run completed")
            else:
                smoke_result = self._executor.run(
                    command=policy.smoke_test_command,
                    cwd=self.root,
                    phase="quality-gate",
                    timeout_seconds=300,
                )
                command_results.append(smoke_result)
                if smoke_result.exit_code == 0:
                    checks.append("smoke test passed")
                else:
                    failures.append("smoke test failed")
        else:
            checks.append("smoke test disabled by policy")

        return HygieneReport(ok=not failures, checks=checks, failures=failures, command_results=command_results)

    def _restore_required_context_file(self, required: str) -> bool:
        """Best-effort recovery for core engine artifacts when manually deleted."""
        token = required.strip().replace("\\", "/").lower()
        if token == "agent_status.md":
            save_status(self.root, load_status(self.root))
            return True
        if token == "feature_list.json":
            save_features(self.root, load_features(self.root))
            return True
        if token == "progress.log":
            (self.root / "progress.log").touch(exist_ok=True)
            return True
        if token == "agent_policy.md":
            save_policy(self.root, load_policy(self.root))
            return True
        return False

    def _feature_progress(self) -> tuple[int, int]:
        features = load_features(self.root)
        total = len(features)
        passed = len([item for item in features if item.passes])
        return passed, total

    def _resolve_implementation_backend(self, feature: Feature) -> str:
        backend = (self.policy.implementation_backend or "codex").strip().lower()
        if backend in {"shell", "codex"}:
            return backend
        if backend == "auto":
            return "shell" if feature.implementation_commands else "codex"
        return "codex"

    def run_browser_validation(
        self,
        *,
        url: str | None = None,
        backend: str | None = None,
        steps_file: str | None = None,
        expect_text: str | None = None,
        headless: bool | None = None,
        open_system_browser: bool | None = None,
        dry_run: bool = False,
    ) -> BrowserValidationReport:
        policy = self.get_policy()
        target_url = url or policy.browser_validation_url
        if not target_url:
            return BrowserValidationReport(
                success=False,
                backend=backend or policy.browser_validation_backend,
                url="",
                message="Browser validation URL is not configured.",
                checks=[],
                errors=["Set policy.browser_validation_url or pass --url."],
                command_results=[],
            )

        resolved_backend = backend or policy.browser_validation_backend
        resolved_steps = steps_file or policy.browser_validation_steps_file
        resolved_headless = policy.browser_validation_headless if headless is None else headless
        resolved_open_browser = (
            policy.browser_validation_open_system_browser
            if open_system_browser is None
            else open_system_browser
        )
        return self._browser_validator.validate(
            url=target_url,
            backend=resolved_backend,
            steps_file=resolved_steps,
            expect_text=expect_text,
            headless=resolved_headless,
            open_system_browser=resolved_open_browser,
            dry_run=dry_run,
        )

    def run_osworld_mode(
        self,
        *,
        backend: str | None = None,
        steps_file: str | None = None,
        url: str | None = None,
        headless: bool | None = None,
        enable_desktop_control: bool | None = None,
        dry_run: bool = False,
    ) -> OSWorldRunReport:
        policy = self.get_policy()
        resolved_backend = backend or policy.osworld_action_backend
        resolved_steps = steps_file or policy.osworld_steps_file
        resolved_url = url or policy.browser_validation_url
        resolved_headless = policy.osworld_headless if headless is None else headless
        resolved_desktop_control = (
            policy.osworld_enable_desktop_control
            if enable_desktop_control is None
            else enable_desktop_control
        )
        return self._osworld_runner.run(
            backend=resolved_backend,
            steps_file=resolved_steps,
            url=resolved_url,
            headless=resolved_headless,
            screenshot_dir=policy.osworld_screenshot_dir,
            enable_desktop_control=resolved_desktop_control,
            dry_run=dry_run,
        )

    def estimate_context_chars(self) -> int:
        files = ["AGENT_STATUS.md", "feature_list.json", "progress.log"]
        total = 0
        for name in files:
            path = self.root / name
            if path.exists():
                total += len(path.read_text(encoding="utf-8"))
        return total

    def trigger_handoff_if_needed(
        self,
        *,
        iterations_executed: int,
        no_progress_iterations: int,
        context_chars: int,
        last_report: dict,
    ) -> HandoffReport:
        policy = self.get_policy()
        if not policy.auto_handoff_enabled:
            return HandoffReport(
                triggered=False,
                reason="auto_handoff_disabled",
                iteration=iterations_executed,
                context_chars=context_chars,
                summary_file=policy.handoff_summary_file,
                summary={},
            )

        reason = ""
        if iterations_executed > 0 and iterations_executed % max(1, policy.handoff_after_iterations) == 0:
            reason = "iteration_threshold"
        if no_progress_iterations >= max(1, policy.handoff_on_no_progress_iterations):
            reason = "no_progress_threshold"
        if context_chars >= max(2000, policy.handoff_context_char_threshold):
            reason = "context_pressure"

        if not reason:
            return HandoffReport(
                triggered=False,
                reason="no_trigger",
                iteration=iterations_executed,
                context_chars=context_chars,
                summary_file=policy.handoff_summary_file,
                summary={},
            )

        summary = self._build_handoff_summary(
            iterations_executed=iterations_executed,
            no_progress_iterations=no_progress_iterations,
            context_chars=context_chars,
            last_report=last_report,
            policy=policy,
        )
        summary_path = self.root / policy.handoff_summary_file
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        append_progress(
            self.root,
            f"Auto handoff triggered reason={reason} iteration={iterations_executed} context_chars={context_chars}",
        )
        return HandoffReport(
            triggered=True,
            reason=reason,
            iteration=iterations_executed,
            context_chars=context_chars,
            summary_file=str(summary_path),
            summary=summary,
        )

    def _build_handoff_summary(
        self,
        *,
        iterations_executed: int,
        no_progress_iterations: int,
        context_chars: int,
        last_report: dict,
        policy: AgentPolicy,
    ) -> dict:
        status = self.get_status()
        features = self.list_features()
        pending = [item for item in features if not item.passes]
        pending.sort(key=lambda item: (item.priority, item.id))
        progress_tail = read_progress_tail(self.root, lines=max(5, policy.handoff_max_tail_lines))
        return {
            "iteration": iterations_executed,
            "current_objective": status.current_objective,
            "context_chars": context_chars,
            "no_progress_iterations": no_progress_iterations,
            "done_count": len([item for item in features if item.passes]),
            "pending_count": len(pending),
            "top_pending_features": [
                {
                    "id": item.id,
                    "priority": item.priority,
                    "description": item.description,
                    "parallel_safe": item.parallel_safe,
                }
                for item in pending[:10]
            ],
            "latest_blockers": status.blockers[-10:],
            "latest_commands": status.last_command_summary[-10:],
            "latest_test_summary": status.last_test_summary,
            "progress_tail": progress_tail,
            "last_report": last_report,
        }

    def evaluate_stop_condition(
        self,
        *,
        policy: AgentPolicy,
        iterations_executed: int,
        max_iterations: int,
        passed_features: int,
        total_features: int,
        no_progress_iterations: int,
        last_report_success: bool,
        last_quality_gate_ok: bool | None,
        browser_validation: BrowserValidationReport | None,
    ) -> StopDecision:
        if policy.stop_on_quality_gate_failure and last_quality_gate_ok is False:
            return StopDecision(
                should_stop=True,
                reason="quality_gate_failed",
                success=False,
            )

        if policy.stop_when_all_features_pass and total_features > 0 and passed_features >= total_features:
            if policy.require_browser_validation_before_stop:
                if browser_validation is None:
                    return StopDecision(
                        should_stop=False,
                        reason="await_browser_validation",
                        success=False,
                    )
                if not browser_validation.success:
                    return StopDecision(
                        should_stop=True,
                        reason="browser_validation_failed",
                        success=False,
                    )
            return StopDecision(
                should_stop=True,
                reason="all_features_passed",
                success=True,
            )

        if total_features == 0 and iterations_executed >= 1 and last_report_success:
            return StopDecision(
                should_stop=True,
                reason="no_features_configured",
                success=True,
            )

        if no_progress_iterations >= max(1, policy.max_no_progress_iterations):
            return StopDecision(
                should_stop=True,
                reason="stagnation_no_progress",
                success=False,
            )

        if iterations_executed >= max_iterations:
            return StopDecision(
                should_stop=True,
                reason="max_iterations_reached",
                success=last_report_success and passed_features == total_features and total_features > 0,
            )

        return StopDecision(
            should_stop=False,
            reason="continue",
            success=False,
        )

    def run_project_loop(
        self,
        *,
        mode: str = "single",
        max_iterations: int | None = None,
        team_count: int | None = None,
        max_features: int | None = None,
        force_unsafe: bool = False,
        commit: bool = False,
        dry_run: bool = False,
        browser_validate_on_stop: bool | None = None,
    ) -> ProjectRunReport:
        policy = self.get_policy()
        resolved_mode = mode.strip().lower()
        if resolved_mode not in {"single", "parallel"}:
            resolved_mode = "single"

        resolved_max_epochs = max_iterations or policy.max_iterations_per_run
        resolved_max_epochs = max(1, resolved_max_epochs)

        reports: list[dict] = []
        quality_gate_failures = 0
        no_progress_iterations = 0
        last_stop = StopDecision(should_stop=False, reason="continue", success=False)
        browser_report: BrowserValidationReport | None = None
        handoff_events: list[dict] = []
        osworld_runs: list[dict] = []
        passed_before, _ = self._feature_progress()

        for _ in range(resolved_max_epochs):
            # One run-project "iteration" is treated as a full epoch:
            # each feature pending at epoch start is attempted at most once.
            epoch_number = len(reports) + 1
            epoch_initial_pending_ids = [item.id for item in self.list_features() if not item.passes]
            epoch_attempted_ids: set[str] = set()
            epoch_subreports: list[dict] = []
            epoch_last_quality_gate_ok: bool | None = True
            epoch_last_success = True

            if epoch_initial_pending_ids:
                while True:
                    remaining_ids = [
                        feature_id
                        for feature_id in epoch_initial_pending_ids
                        if feature_id not in epoch_attempted_ids
                    ]
                    if not remaining_ids:
                        break

                    if resolved_mode == "parallel":
                        iteration_report = self.run_parallel_iteration(
                            team_count=team_count,
                            max_features=max_features,
                            force_unsafe=force_unsafe,
                            commit=commit,
                            dry_run=dry_run,
                            exclude_feature_ids=epoch_attempted_ids,
                        )
                        report_dict = iteration_report.to_dict()
                        considered_ids = set(iteration_report.selected_feature_ids) | set(
                            iteration_report.skipped_feature_ids
                        )
                        epoch_last_quality_gate_ok = iteration_report.quality_gate_ok
                        epoch_last_success = iteration_report.success
                    else:
                        iteration_report = self.run_iteration(
                            commit=commit,
                            dry_run=dry_run,
                            exclude_feature_ids=epoch_attempted_ids,
                        )
                        report_dict = iteration_report.to_dict()
                        considered_ids = {iteration_report.feature_id} if iteration_report.feature_id else set()
                        epoch_last_quality_gate_ok = iteration_report.quality_gate_ok
                        epoch_last_success = iteration_report.success

                    epoch_subreports.append(report_dict)
                    epoch_attempted_ids.update(considered_ids)

                    if epoch_last_quality_gate_ok is False:
                        break
                    if not considered_ids:
                        break

            if epoch_subreports:
                epoch_success = all(bool(item.get("success", False)) for item in epoch_subreports)
                epoch_last_success = bool(epoch_subreports[-1].get("success", False))
                epoch_last_quality_gate_ok = all(
                    item.get("quality_gate_ok") is not False for item in epoch_subreports
                )
            else:
                epoch_success = True
                epoch_last_success = True
                epoch_last_quality_gate_ok = True if not epoch_initial_pending_ids else None

            epoch_report = {
                "epoch": epoch_number,
                "mode": resolved_mode,
                "initial_pending_feature_ids": epoch_initial_pending_ids,
                "attempted_feature_ids": sorted(epoch_attempted_ids),
                "subreports": epoch_subreports,
                "success": epoch_success,
                "quality_gate_ok": epoch_last_quality_gate_ok,
                "pending_after_epoch": [item.id for item in self.list_features() if not item.passes],
            }
            reports.append(epoch_report)

            if epoch_last_quality_gate_ok is False:
                quality_gate_failures += 1

            passed_after, total_features = self._feature_progress()
            if passed_after > passed_before:
                no_progress_iterations = 0
            else:
                no_progress_iterations += 1
            passed_before = passed_after

            context_chars = self.estimate_context_chars()
            handoff = self.trigger_handoff_if_needed(
                iterations_executed=len(reports),
                no_progress_iterations=no_progress_iterations,
                context_chars=context_chars,
                last_report=epoch_report,
            )
            if handoff.triggered:
                handoff_events.append(handoff.to_dict())
                # Handoff provides a fresh state boundary; give one extra attempt window.
                if no_progress_iterations > 0:
                    no_progress_iterations -= 1

            need_browser_before_stop = (
                policy.require_browser_validation_before_stop
                if browser_validate_on_stop is None
                else browser_validate_on_stop
            )
            tentative_stop = self.evaluate_stop_condition(
                policy=policy,
                iterations_executed=len(reports),
                max_iterations=resolved_max_epochs,
                passed_features=passed_after,
                total_features=total_features,
                no_progress_iterations=no_progress_iterations,
                last_report_success=epoch_last_success,
                last_quality_gate_ok=epoch_last_quality_gate_ok,
                browser_validation=browser_report,
            )

            if (
                tentative_stop.reason in {"all_features_passed", "await_browser_validation"}
                and need_browser_before_stop
                and browser_report is None
            ):
                if policy.osworld_mode_enabled:
                    osworld_report = self.run_osworld_mode(dry_run=dry_run)
                    osworld_runs.append(osworld_report.to_dict())
                    browser_report = BrowserValidationReport(
                        success=osworld_report.success,
                        backend=f"osworld:{osworld_report.backend}",
                        url=policy.browser_validation_url or "",
                        message=osworld_report.message,
                        checks=[item.message for item in osworld_report.actions if item.success],
                        errors=[item.message for item in osworld_report.actions if not item.success],
                        command_results=osworld_report.command_results,
                    )
                else:
                    browser_report = self.run_browser_validation(dry_run=dry_run)
                tentative_stop = self.evaluate_stop_condition(
                    policy=policy,
                    iterations_executed=len(reports),
                    max_iterations=resolved_max_epochs,
                    passed_features=passed_after,
                    total_features=total_features,
                    no_progress_iterations=no_progress_iterations,
                    last_report_success=epoch_last_success,
                    last_quality_gate_ok=epoch_last_quality_gate_ok,
                    browser_validation=browser_report,
                )

            last_stop = tentative_stop
            if tentative_stop.should_stop:
                break

        append_progress(
            self.root,
            f"Project loop finished mode={resolved_mode} epochs={len(reports)} reason={last_stop.reason}",
        )
        return ProjectRunReport(
            mode=resolved_mode,
            iterations_executed=len(reports),
            success=last_stop.success,
            stop_reason=last_stop.reason,
            final_passed_features=passed_before,
            total_features=self._feature_progress()[1],
            reports=reports,
            quality_gate_failures=quality_gate_failures,
            no_progress_iterations=no_progress_iterations,
            browser_validation=browser_report,
            handoff_events=handoff_events,
            osworld_runs=osworld_runs,
        )

    def _execute_feature(
        self,
        feature: Feature,
        dry_run: bool = False,
        team_id: str | None = None,
        objective: str | None = None,
        iteration_number: int | None = None,
    ) -> TeamExecutionResult:
        phase_prefix = f"{team_id}:" if team_id else ""
        implementation_backend = self._resolve_implementation_backend(feature)
        workspace_before_snapshot: dict[str, tuple[int, int]] | None = None
        if implementation_backend == "codex" and not dry_run:
            workspace_before_snapshot = _snapshot_workspace_files(self.root)
        if (
            implementation_backend == "shell"
            and not feature.implementation_commands
            and not feature.verification_command
        ):
            return TeamExecutionResult(
                team_id=team_id or "single",
                feature_id=feature.id,
                success=False,
                message=f"{phase_prefix}feature has no implementation_commands and no verification_command",
                command_results=[],
            )

        programmer_key = f"{team_id or 'single'}:{feature.id}:{implementation_backend}:programmer"
        self._register_worker_activity(
            worker_key=programmer_key,
            role="Programmer",
            feature_id=feature.id,
            team_id=team_id,
            model=self.policy.codex_model if implementation_backend == "codex" else "",
            backend=implementation_backend,
        )
        try:
            if implementation_backend == "codex":
                programmer = CodexProgrammerAgent(
                    cli_path=self.policy.codex_cli_path,
                    model=self.policy.codex_model,
                    reasoning_effort=self.policy.codex_reasoning_effort,
                    sandbox_mode=self.policy.codex_sandbox_mode,
                    full_auto=self.policy.codex_full_auto,
                    skip_git_repo_check=self.policy.codex_skip_git_repo_check,
                    ephemeral=self.policy.codex_ephemeral,
                    timeout_seconds=self.policy.codex_timeout_seconds,
                    retry_once=self.policy.retry_failed_commands_once,
                )
                implementation_results = programmer.implement(
                    feature=feature,
                    cwd=self.root,
                    dry_run=dry_run,
                    objective=objective,
                    team_id=team_id,
                    iteration_number=iteration_number,
                )
            else:
                programmer = ProgrammerAgent(retry_once=self.policy.retry_failed_commands_once)
                implementation_results = programmer.implement(feature=feature, cwd=self.root, dry_run=dry_run)
        finally:
            self._unregister_worker_activity(programmer_key)

        operator = OperatorAgent(retry_once=self.policy.retry_failed_commands_once)

        if implementation_backend == "codex" and not dry_run:
            guard_result = _detect_codex_noop_result(implementation_results)
            if guard_result is not None:
                implementation_results.append(guard_result)

        implementation_ok = all(result.exit_code == 0 for result in implementation_results)

        verification_results: list[CommandResult] = []
        if implementation_ok:
            operator_key = f"{team_id or 'single'}:{feature.id}:operator"
            self._register_worker_activity(
                worker_key=operator_key,
                role="Operator",
                feature_id=feature.id,
                team_id=team_id,
                backend="verify",
            )
            try:
                verification_results = operator.verify(feature=feature, cwd=self.root, dry_run=dry_run)
            finally:
                self._unregister_worker_activity(operator_key)
        command_results = implementation_results + verification_results
        if implementation_backend == "codex" and not dry_run and workspace_before_snapshot is not None:
            workspace_after_snapshot = _snapshot_workspace_files(self.root)
            workspace_guard = _detect_missing_workspace_change(
                before_snapshot=workspace_before_snapshot,
                after_snapshot=workspace_after_snapshot,
                verification_results=verification_results,
            )
            if workspace_guard is not None:
                command_results.append(workspace_guard)

        success = all(result.exit_code == 0 for result in command_results)
        if success:
            message = f"{phase_prefix}feature {feature.id} completed"
        else:
            failure = _find_first_failure(command_results)
            failure_text = failure.to_summary() if failure else "feature execution failed with unknown reason."
            hard_blocker = _detect_hard_blocker(failure_text, self.policy)
            if hard_blocker:
                failure_text = f"{failure_text} | hard_blocker={hard_blocker}"
            message = f"{phase_prefix}{failure_text}"

        return TeamExecutionResult(
            team_id=team_id or "single",
            feature_id=feature.id,
            success=success,
            message=message,
            command_results=command_results,
        )

    def run_iteration(
        self,
        commit: bool = False,
        dry_run: bool = False,
        exclude_feature_ids: set[str] | None = None,
    ) -> IterationReport:
        status = load_status(self.root)
        self.policy = load_policy(self.root)
        self._sync_runtime_policy()
        features = load_features(self.root)
        bootstrap_notes, bootstrap_command_results = self.bootstrap_session(dry_run=dry_run)
        gate = self.run_quality_gate(dry_run=dry_run)
        preflight_command_results = bootstrap_command_results + gate.command_results

        status.iteration += 1
        iteration_number = status.iteration

        if not gate.ok:
            status.in_progress = []
            for failure in gate.failures:
                status.blockers.append(f"Iteration {iteration_number} preflight: {failure}")
            status.next_steps = ["Fix preflight blockers and rerun `caasys iterate`."]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results] or [
                "Preflight failed before running commands."
            ]
            status.last_test_summary = "Quality gate failed before feature execution."
            save_status(self.root, status)
            append_progress(
                self.root,
                f"Iteration {iteration_number} blocked by quality gate: {'; '.join(gate.failures)}",
            )
            return IterationReport(
                iteration_number=iteration_number,
                goal="Preflight quality gate",
                plan=[
                    "BOOTSTRAP: refresh status, progress tail, and git summary",
                    "QUALITY_GATE: required artifacts, stale-state check, smoke test",
                    "STOP: gate failed, apply fallback chain",
                ],
                feature_id=None,
                success=False,
                result="Iteration stopped by quality gate.",
                next_step=status.next_steps[0],
                quality_gate_ok=False,
                bootstrap_notes=bootstrap_notes,
                command_results=preflight_command_results,
            )

        orchestrator_key = f"orchestrator:iteration:{iteration_number}:single"
        self._register_worker_activity(
            worker_key=orchestrator_key,
            role="Orchestrator",
            backend="scheduler",
        )
        try:
            feature = self.orchestrator.pick_next_feature(features, exclude_feature_ids=exclude_feature_ids)
            orchestrator_plan = self.orchestrator.build_plan(feature) if feature is not None else []
        finally:
            self._unregister_worker_activity(orchestrator_key)

        if feature is None:
            status.in_progress = []
            status.next_steps = ["No pending features. Add new features to continue."]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results] or [
                "No iteration executed: all features already pass."
            ]
            status.last_test_summary = "Quality gate passed. No pending verification."
            save_status(self.root, status)
            append_progress(self.root, f"Iteration {iteration_number} skipped: no pending features")
            return IterationReport(
                iteration_number=iteration_number,
                goal="No pending features",
                plan=[
                    "BOOTSTRAP: refresh status, progress tail, and git summary",
                    "QUALITY_GATE: required artifacts and smoke test",
                    "No pending feature to execute",
                ],
                feature_id=None,
                success=True,
                result="All features already pass.",
                next_step="Add new features if more work is needed.",
                quality_gate_ok=True,
                bootstrap_notes=bootstrap_notes,
                command_results=preflight_command_results,
            )

        plan = [
            "BOOTSTRAP: refresh status, progress tail, and git summary",
            "QUALITY_GATE: required artifacts and smoke test",
            *orchestrator_plan,
        ]
        status.in_progress = [f"Iteration {iteration_number}: {feature.id} {feature.description}"]

        execution = self._execute_feature(
            feature=feature,
            dry_run=dry_run,
            objective=status.current_objective,
            iteration_number=iteration_number,
        )
        command_results = execution.command_results
        success = execution.success
        verification_results = [item for item in command_results if item.phase.startswith("verify")]

        all_command_results = preflight_command_results + command_results
        if success:
            feature.passes = True
            status.done.append(f"Iteration {iteration_number}: completed {feature.id}")
            result = f"Feature {feature.id} completed successfully."
            test_summary = (
                "Quality gate and verification passed."
                if verification_results
                else "Quality gate passed; no verification command configured."
            )
        else:
            failure_text = execution.message
            status.blockers.append(f"Iteration {iteration_number} {feature.id}: {failure_text}")
            result = f"Feature {feature.id} failed. Blocker recorded."
            test_summary = (
                "Quality gate passed; verification failed."
                if verification_results
                else "Quality gate passed; implementation failed before verification."
            )

        status.in_progress = []
        status.last_command_summary = [item.to_summary() for item in all_command_results] or [
            "No commands were configured for this feature."
        ]
        status.last_test_summary = test_summary

        self._register_worker_activity(
            worker_key=orchestrator_key,
            role="Orchestrator",
            backend="scheduler",
        )
        try:
            next_feature = self.orchestrator.pick_next_feature(features)
        finally:
            self._unregister_worker_activity(orchestrator_key)
        if next_feature:
            status.next_steps = [f"Run next feature: {next_feature.id} - {next_feature.description}"]
        else:
            status.next_steps = ["All listed features now pass."]

        save_features(self.root, features)
        save_status(self.root, status)
        append_progress(
            self.root,
            f"Iteration {iteration_number} {'passed' if success else 'failed'} on {feature.id}",
        )

        if commit:
            self._attempt_git_commit(feature=feature, success=success, iteration_number=iteration_number)

        return IterationReport(
            iteration_number=iteration_number,
            goal=f"Deliver feature {feature.id}",
            plan=plan,
            feature_id=feature.id,
            success=success,
            result=result,
            next_step=status.next_steps[0],
            quality_gate_ok=True,
            bootstrap_notes=bootstrap_notes,
            command_results=all_command_results,
        )

    def run_parallel_iteration(
        self,
        team_count: int | None = None,
        max_features: int | None = None,
        commit: bool = False,
        dry_run: bool = False,
        force_unsafe: bool = False,
        exclude_feature_ids: set[str] | None = None,
    ) -> ParallelIterationReport:
        status = load_status(self.root)
        self.policy = load_policy(self.root)
        self._sync_runtime_policy()
        features = load_features(self.root)
        bootstrap_notes, bootstrap_command_results = self.bootstrap_session(dry_run=dry_run)
        gate = self.run_quality_gate(dry_run=dry_run)
        preflight_command_results = bootstrap_command_results + gate.command_results

        status.iteration += 1
        iteration_number = status.iteration

        if not self.policy.enable_parallel_teams:
            gate_ok = False
            status.blockers.append(f"Iteration {iteration_number} parallel: policy disabled parallel teams")
            status.in_progress = []
            status.next_steps = ["Enable parallel mode in policy or use `caasys iterate`."]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results]
            status.last_test_summary = "Parallel iteration blocked by policy."
            save_status(self.root, status)
            append_progress(self.root, f"Iteration {iteration_number} parallel blocked: policy disabled")
            return ParallelIterationReport(
                iteration_number=iteration_number,
                team_count=0,
                selected_feature_ids=[],
                success=False,
                result="Parallel mode disabled by policy.",
                next_step=status.next_steps[0],
                quality_gate_ok=gate_ok,
                skipped_feature_ids=[],
                bootstrap_notes=bootstrap_notes,
                team_results=[],
                command_results=preflight_command_results,
            )

        if not gate.ok:
            status.in_progress = []
            for failure in gate.failures:
                status.blockers.append(f"Iteration {iteration_number} preflight: {failure}")
            status.next_steps = ["Fix preflight blockers and rerun `caasys iterate-parallel`."]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results] or [
                "Preflight failed before running parallel teams."
            ]
            status.last_test_summary = "Quality gate failed before parallel execution."
            save_status(self.root, status)
            append_progress(
                self.root,
                f"Iteration {iteration_number} parallel blocked by quality gate: {'; '.join(gate.failures)}",
            )
            return ParallelIterationReport(
                iteration_number=iteration_number,
                team_count=0,
                selected_feature_ids=[],
                success=False,
                result="Parallel iteration stopped by quality gate.",
                next_step=status.next_steps[0],
                quality_gate_ok=False,
                skipped_feature_ids=[],
                bootstrap_notes=bootstrap_notes,
                team_results=[],
                command_results=preflight_command_results,
            )

        resolved_team_count = max(1, team_count or self.policy.default_parallel_teams)
        resolved_max_features = max_features or self.policy.max_parallel_features_per_iteration
        resolved_max_features = max(1, resolved_max_features)

        orchestrator_key = f"orchestrator:iteration:{iteration_number}:parallel"
        self._register_worker_activity(
            worker_key=orchestrator_key,
            role="Orchestrator",
            backend="scheduler",
        )
        try:
            candidates = self.orchestrator.pick_next_features(
                features,
                resolved_max_features,
                exclude_feature_ids=exclude_feature_ids,
            )
        finally:
            self._unregister_worker_activity(orchestrator_key)
        if not candidates:
            status.in_progress = []
            status.next_steps = ["No pending features. Add new features to continue."]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results] or [
                "No parallel work executed: all features already pass."
            ]
            status.last_test_summary = "Quality gate passed. No pending verification."
            save_status(self.root, status)
            append_progress(self.root, f"Iteration {iteration_number} parallel skipped: no pending features")
            return ParallelIterationReport(
                iteration_number=iteration_number,
                team_count=resolved_team_count,
                selected_feature_ids=[],
                success=True,
                result="All features already pass.",
                next_step="Add new features if more work is needed.",
                quality_gate_ok=True,
                skipped_feature_ids=[],
                bootstrap_notes=bootstrap_notes,
                team_results=[],
                command_results=preflight_command_results,
            )

        selected_features: list[Feature] = []
        skipped_unsafe: list[str] = []
        for feature in candidates:
            if self.policy.require_parallel_safe_flag and not force_unsafe and not feature.parallel_safe:
                skipped_unsafe.append(feature.id)
                continue
            selected_features.append(feature)

        if not selected_features:
            status.in_progress = []
            status.blockers.append(
                f"Iteration {iteration_number} parallel: no selected features are parallel_safe "
                f"(candidates={','.join(item.id for item in candidates)})"
            )
            status.next_steps = [
                "Mark target features with parallel_safe=true or use --force-unsafe / single iterate mode."
            ]
            status.last_command_summary = [item.to_summary() for item in preflight_command_results]
            status.last_test_summary = "Parallel iteration blocked by safety policy."
            save_status(self.root, status)
            append_progress(self.root, f"Iteration {iteration_number} parallel blocked: no parallel_safe features")
            return ParallelIterationReport(
                iteration_number=iteration_number,
                team_count=resolved_team_count,
                selected_feature_ids=[],
                success=False,
                result="No parallel-safe features available for parallel execution.",
                next_step=status.next_steps[0],
                quality_gate_ok=True,
                skipped_feature_ids=skipped_unsafe,
                bootstrap_notes=bootstrap_notes,
                team_results=[],
                command_results=preflight_command_results,
            )

        status.in_progress = [
            f"Iteration {iteration_number}: parallel teams running {len(selected_features)} features "
            f"with {resolved_team_count} teams"
        ]
        team_results: list[TeamExecutionResult] = []
        feature_by_id = {feature.id: feature for feature in selected_features}

        with ThreadPoolExecutor(max_workers=resolved_team_count) as pool:
            futures = []
            for index, feature in enumerate(selected_features):
                team_id = f"team-{(index % resolved_team_count) + 1}"
                futures.append(
                    pool.submit(
                        self._execute_feature,
                        feature,
                        dry_run,
                        team_id,
                        status.current_objective,
                        iteration_number,
                    )
                )

            for future in as_completed(futures):
                team_results.append(future.result())

        # deterministic order for reporting and status updates
        team_results.sort(key=lambda item: (item.team_id, item.feature_id))

        for item in team_results:
            if item.success:
                feature_by_id[item.feature_id].passes = True
                status.done.append(f"Iteration {iteration_number}: {item.team_id} completed {item.feature_id}")
            else:
                status.blockers.append(f"Iteration {iteration_number} {item.team_id} {item.feature_id}: {item.message}")

        if skipped_unsafe:
            status.blockers.append(
                f"Iteration {iteration_number} parallel skipped non-parallel-safe features: {', '.join(skipped_unsafe)}"
            )

        all_command_results = preflight_command_results + [
            command for team in team_results for command in team.command_results
        ]
        status.in_progress = []
        status.last_command_summary = [item.to_summary() for item in all_command_results] or [
            "No commands were configured for selected parallel features."
        ]
        success = all(item.success for item in team_results) and not skipped_unsafe
        if success:
            status.last_test_summary = "Quality gate and parallel team verification passed."
        else:
            status.last_test_summary = "Quality gate passed; one or more parallel team executions failed or were skipped."

        self._register_worker_activity(
            worker_key=orchestrator_key,
            role="Orchestrator",
            backend="scheduler",
        )
        try:
            next_feature = self.orchestrator.pick_next_feature(features)
        finally:
            self._unregister_worker_activity(orchestrator_key)
        if next_feature:
            status.next_steps = [f"Next pending feature: {next_feature.id} - {next_feature.description}"]
        else:
            status.next_steps = ["All listed features now pass."]

        save_features(self.root, features)
        save_status(self.root, status)
        append_progress(
            self.root,
            f"Iteration {iteration_number} parallel {'passed' if success else 'failed'} "
            f"features={','.join(item.feature_id for item in team_results)}",
        )

        if commit:
            self._attempt_git_commit_parallel(
                feature_ids=[item.feature_id for item in team_results],
                success=success,
                iteration_number=iteration_number,
            )

        return ParallelIterationReport(
            iteration_number=iteration_number,
            team_count=resolved_team_count,
            selected_feature_ids=[item.feature_id for item in team_results],
            success=success,
            result=(
                "Parallel iteration completed successfully."
                if success
                else "Parallel iteration completed with failures or safety skips."
            ),
            next_step=status.next_steps[0],
            quality_gate_ok=True,
            skipped_feature_ids=skipped_unsafe,
            bootstrap_notes=bootstrap_notes,
            team_results=team_results,
            command_results=all_command_results,
        )

    def _attempt_git_commit(self, feature: Feature, success: bool, iteration_number: int) -> None:
        message_prefix = "feat" if success else "fix"
        message = f"{message_prefix}: iteration {iteration_number} processed {feature.id}"
        commands = [
            ["git", "add", "AGENT_STATUS.md", "feature_list.json", "progress.log"],
            ["git", "commit", "-m", message],
        ]
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                # Commit errors should not crash the main loop; record them in progress.
                append_progress(
                    self.root,
                    f"Git command failed: {' '.join(command)} :: {completed.stderr.strip() or completed.stdout.strip()}",
                )
                break

    def _attempt_git_commit_parallel(self, feature_ids: list[str], success: bool, iteration_number: int) -> None:
        message_prefix = "feat" if success else "fix"
        feature_part = ",".join(feature_ids[:5])
        if len(feature_ids) > 5:
            feature_part += ",..."
        message = f"{message_prefix}: iteration {iteration_number} parallel processed [{feature_part}]"
        commands = [
            ["git", "add", "AGENT_STATUS.md", "feature_list.json", "progress.log"],
            ["git", "commit", "-m", message],
        ]
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                append_progress(
                    self.root,
                    f"Git command failed: {' '.join(command)} :: {completed.stderr.strip() or completed.stdout.strip()}",
                )
                break


def load_report_json(path: str | Path) -> dict[str, object]:
    """Helper primarily for API clients/tests that store iteration reports to disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(payload)


def _find_first_failure(results):
    for result in results:
        if result.exit_code != 0:
            return result
    return None


def _format_role_identity(*, role: str, number: int) -> str:
    role_code = {
        "Orchestrator": "ORC",
        "Planner": "PLN",
        "Programmer": "PRG",
        "Operator": "OPS",
    }.get(role, "AI")
    return f"{role_code}-{number:02d}"


def _detect_hard_blocker(failure_text: str, policy: AgentPolicy) -> str | None:
    lower = failure_text.lower()
    for marker in policy.hard_blocker_patterns:
        if marker.lower() in lower:
            return marker
    return None


def _detect_codex_noop_result(results: list[CommandResult]) -> CommandResult | None:
    if not results:
        return None
    if any(item.exit_code != 0 for item in results):
        return None

    combined_output = "\n".join(
        chunk.strip()
        for chunk in [
            *[item.stdout for item in results],
            *[item.stderr for item in results],
        ]
        if chunk and chunk.strip()
    )
    if not combined_output:
        return None
    if not _looks_like_codex_noop_response(combined_output):
        return None

    return CommandResult(
        command="codex-response-guard",
        exit_code=21,
        stdout="",
        stderr="codex returned acknowledgement/no-op output without implementation evidence",
        duration_seconds=0.0,
        phase="implement-codex-guard",
    )


def _looks_like_codex_noop_response(text: str) -> bool:
    lower = text.lower()
    markers = [
        "provide the next work item",
        "send the next objective",
        "ready to run as the coding worker",
        "operating in autonomous coding mode",
        "operating mode set",
        "i'll execute tasks end-to-end",
        "i will execute tasks end-to-end",
        "send the next task",
        "share the target outcome",
    ]
    if not any(marker in lower for marker in markers):
        return False

    work_signals = [
        "files changed",
        "changed files",
        "created ",
        "updated ",
        "modified ",
        "wrote ",
        "test",
        "verification",
        "pytest",
        "unittest",
    ]
    return not any(signal in lower for signal in work_signals)


def _snapshot_workspace_files(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    excluded_files = {"AGENT_STATUS.md", "AGENT_POLICY.md", "feature_list.json", "progress.log"}
    excluded_prefixes = (".caasys/", ".git/")

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in excluded_files or rel.startswith(excluded_prefixes):
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue
        snapshot[rel] = (int(stat.st_size), int(stat.st_mtime_ns))
    return snapshot


def _detect_missing_workspace_change(
    *,
    before_snapshot: dict[str, tuple[int, int]],
    after_snapshot: dict[str, tuple[int, int]],
    verification_results: list[CommandResult],
) -> CommandResult | None:
    if before_snapshot != after_snapshot:
        return None
    if verification_results:
        return None
    return CommandResult(
        command="workspace-change-guard",
        exit_code=22,
        stdout="",
        stderr="codex run produced no repository file changes and no verification results",
        duration_seconds=0.0,
        phase="implement-codex-guard",
    )
