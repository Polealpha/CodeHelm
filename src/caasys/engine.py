"""Iteration engine implementing PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> NEXT."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .agents import OperatorAgent, ProgrammerAgent
from .models import AgentStatus, Feature, IterationReport
from .orchestrator import Orchestrator
from .storage import append_progress, load_features, load_status, save_features, save_status


class ContinuousEngine:
    """Main entry point for initializing and running autonomous iterations."""

    def __init__(
        self,
        root: str | Path,
        orchestrator: Orchestrator | None = None,
        programmer: ProgrammerAgent | None = None,
        operator: OperatorAgent | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.orchestrator = orchestrator or Orchestrator()
        self.programmer = programmer or ProgrammerAgent()
        self.operator = operator or OperatorAgent()

    def initialize(self, objective: str) -> AgentStatus:
        self.root.mkdir(parents=True, exist_ok=True)
        status = load_status(self.root)
        status.current_objective = objective.strip()
        status.in_progress = ["System initialized and ready for Iteration 1."]
        status.next_steps = ["Add or review feature_list.json, then run `caasys iterate`."]
        status.last_command_summary = ["Initialization completed."]
        status.last_test_summary = "No tests executed yet."
        save_status(self.root, status)

        if not (self.root / "feature_list.json").exists():
            save_features(self.root, [])
        append_progress(self.root, f"Initialized objective: {status.current_objective}")
        return status

    def add_feature(self, feature: Feature) -> Feature:
        features = load_features(self.root)
        existing_ids = {item.id for item in features}
        if feature.id in existing_ids:
            raise ValueError(f"Feature '{feature.id}' already exists")
        features.append(feature)
        save_features(self.root, features)
        append_progress(self.root, f"Feature added: {feature.id}")
        return feature

    def list_features(self) -> list[Feature]:
        return load_features(self.root)

    def get_status(self) -> AgentStatus:
        return load_status(self.root)

    def run_iteration(self, commit: bool = False, dry_run: bool = False) -> IterationReport:
        status = load_status(self.root)
        features = load_features(self.root)
        feature = self.orchestrator.pick_next_feature(features)

        if feature is None:
            status.in_progress = []
            status.next_steps = ["No pending features. Add new features to continue."]
            status.last_command_summary = ["No iteration executed: all features already pass."]
            status.last_test_summary = "No pending verification."
            save_status(self.root, status)
            append_progress(self.root, "Iteration skipped: no pending features")
            return IterationReport(
                iteration_number=status.iteration,
                goal="No pending features",
                plan=["Nothing to execute"],
                feature_id=None,
                success=True,
                result="All features already pass.",
                next_step="Add new features if more work is needed.",
                command_results=[],
            )

        status.iteration += 1
        iteration_number = status.iteration
        plan = self.orchestrator.build_plan(feature)
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

        if success:
            feature.passes = True
            status.done.append(f"Iteration {iteration_number}: completed {feature.id}")
            result = f"Feature {feature.id} completed successfully."
            test_summary = "Verification passed." if verification_results else "No verification command configured."
        else:
            if not feature.implementation_commands and not feature.verification_command:
                failure_text = "Feature has no implementation_commands and no verification_command."
            else:
                failure = _find_first_failure(command_results)
                failure_text = failure.to_summary() if failure else "Feature execution failed with unknown reason."
            status.blockers.append(f"Iteration {iteration_number} {feature.id}: {failure_text}")
            result = f"Feature {feature.id} failed. Blocker recorded."
            test_summary = "Verification failed." if verification_results else "Implementation failed before verification."

        status.in_progress = []
        status.last_command_summary = [item.to_summary() for item in command_results] or [
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
            command_results=command_results,
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
