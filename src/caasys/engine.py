"""Iteration engine implementing PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> NEXT."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .agents import OperatorAgent, ProgrammerAgent, ShellExecutor
from .models import AgentPolicy, AgentStatus, CommandResult, Feature, HygieneReport, IterationReport
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
        self.orchestrator.policy = self.policy
        self.programmer._retry_once = self.policy.retry_failed_commands_once
        self.operator._retry_once = self.policy.retry_failed_commands_once

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
        return self.policy

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

    def run_iteration(self, commit: bool = False, dry_run: bool = False) -> IterationReport:
        status = load_status(self.root)
        self.policy = load_policy(self.root)
        self.orchestrator.policy = self.policy
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

        feature = self.orchestrator.pick_next_feature(features)

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
            *self.orchestrator.build_plan(feature),
        ]
        status.in_progress = [f"Iteration {iteration_number}: {feature.id} {feature.description}"]

        if not feature.implementation_commands and not feature.verification_command:
            command_results = []
            success = False
            implementation_ok = False
            verification_results = []
        else:
            implementation_results = self.programmer.implement(feature=feature, cwd=self.root, dry_run=dry_run)
            implementation_ok = all(result.exit_code == 0 for result in implementation_results)

            verification_results = []
            if implementation_ok:
                verification_results = self.operator.verify(feature=feature, cwd=self.root, dry_run=dry_run)
            verification_ok = all(result.exit_code == 0 for result in verification_results)

            command_results = implementation_results + verification_results
            success = implementation_ok and verification_ok

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
            if not feature.implementation_commands and not feature.verification_command:
                failure_text = "Feature has no implementation_commands and no verification_command."
            else:
                failure = _find_first_failure(command_results)
                failure_text = failure.to_summary() if failure else "Feature execution failed with unknown reason."
                hard_blocker = _detect_hard_blocker(failure_text, self.policy)
                if hard_blocker:
                    failure_text = f"{failure_text} | hard_blocker={hard_blocker}"
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

        next_feature = self.orchestrator.pick_next_feature(features)
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


def load_report_json(path: str | Path) -> dict[str, object]:
    """Helper primarily for API clients/tests that store iteration reports to disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(payload)


def _find_first_failure(results):
    for result in results:
        if result.exit_code != 0:
            return result
    return None


def _detect_hard_blocker(failure_text: str, policy: AgentPolicy) -> str | None:
    lower = failure_text.lower()
    for marker in policy.hard_blocker_patterns:
        if marker.lower() in lower:
            return marker
    return None
