"""Domain models for autonomous iteration state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Feature:
    """A single feature item tracked by the autonomous loop."""

    id: str
    category: str
    description: str
    priority: int = 100
    passes: bool = False
    parallel_safe: bool = False
    implementation_commands: list[str] = field(default_factory=list)
    verification_command: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Feature":
        return cls(
            id=str(payload["id"]),
            category=str(payload.get("category", "functional")),
            description=str(payload["description"]),
            priority=int(payload.get("priority", 100)),
            passes=bool(payload.get("passes", False)),
            parallel_safe=bool(payload.get("parallel_safe", False)),
            implementation_commands=list(payload.get("implementation_commands", [])),
            verification_command=payload.get("verification_command"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentPolicy:
    """Shared runtime policy applied to all local agents."""

    zero_ask: bool = True
    auto_resolve_duplicate_feature_ids: bool = True
    retry_failed_commands_once: bool = True
    run_smoke_before_iteration: bool = True
    smoke_test_command: str | None = 'python -m unittest discover -s tests -p "test_*.py" -v'
    enable_parallel_teams: bool = True
    default_parallel_teams: int = 2
    max_parallel_features_per_iteration: int = 4
    require_parallel_safe_flag: bool = True
    hard_blocker_patterns: list[str] = field(
        default_factory=lambda: [
            "permission denied",
            "access is denied",
            "api key",
            "credential",
            "network is unreachable",
        ]
    )
    fallback_chain: list[str] = field(
        default_factory=lambda: [
            "retry_once",
            "record_blocker",
            "continue_to_next_feature",
        ]
    )
    required_context_files: list[str] = field(
        default_factory=lambda: ["AGENT_STATUS.md", "feature_list.json", "progress.log"]
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentPolicy":
        return cls(
            zero_ask=bool(payload.get("zero_ask", True)),
            auto_resolve_duplicate_feature_ids=bool(payload.get("auto_resolve_duplicate_feature_ids", True)),
            retry_failed_commands_once=bool(payload.get("retry_failed_commands_once", True)),
            run_smoke_before_iteration=bool(payload.get("run_smoke_before_iteration", True)),
            smoke_test_command=payload.get("smoke_test_command"),
            enable_parallel_teams=bool(payload.get("enable_parallel_teams", True)),
            default_parallel_teams=int(payload.get("default_parallel_teams", 2)),
            max_parallel_features_per_iteration=int(payload.get("max_parallel_features_per_iteration", 4)),
            require_parallel_safe_flag=bool(payload.get("require_parallel_safe_flag", True)),
            hard_blocker_patterns=list(payload.get("hard_blocker_patterns", []))
            or [
                "permission denied",
                "access is denied",
                "api key",
                "credential",
                "network is unreachable",
            ],
            fallback_chain=list(payload.get("fallback_chain", []))
            or ["retry_once", "record_blocker", "continue_to_next_feature"],
            required_context_files=list(payload.get("required_context_files", []))
            or ["AGENT_STATUS.md", "feature_list.json", "progress.log"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        rows = [
            "# AGENT_POLICY",
            "",
            "## Mode",
            f"- zero_ask: `{str(self.zero_ask).lower()}`",
            f"- auto_resolve_duplicate_feature_ids: `{str(self.auto_resolve_duplicate_feature_ids).lower()}`",
            f"- retry_failed_commands_once: `{str(self.retry_failed_commands_once).lower()}`",
            f"- enable_parallel_teams: `{str(self.enable_parallel_teams).lower()}`",
            f"- default_parallel_teams: `{self.default_parallel_teams}`",
            f"- max_parallel_features_per_iteration: `{self.max_parallel_features_per_iteration}`",
            f"- require_parallel_safe_flag: `{str(self.require_parallel_safe_flag).lower()}`",
            "",
            "## Quality Gate",
            f"- run_smoke_before_iteration: `{str(self.run_smoke_before_iteration).lower()}`",
            f"- smoke_test_command: `{self.smoke_test_command or 'None'}`",
            "",
            "## Hard Blocker Patterns",
            *_render_list(self.hard_blocker_patterns),
            "",
            "## Fallback Chain",
            *_render_list(self.fallback_chain),
            "",
            "## Required Context Files",
            *_render_list(self.required_context_files),
            "",
        ]
        return "\n".join(rows)


@dataclass
class CommandResult:
    """Execution result from one shell command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    phase: str

    def to_summary(self) -> str:
        status = "ok" if self.exit_code == 0 else f"failed({self.exit_code})"
        compact = self.stdout.strip() or self.stderr.strip() or "<no output>"
        compact = compact.replace("\n", " ")
        if len(compact) > 160:
            compact = compact[:157] + "..."
        return f"[{self.phase}] {self.command} -> {status}: {compact}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentStatus:
    """Persistent status artifact mirrored into AGENT_STATUS.md."""

    current_objective: str
    done: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    last_command_summary: list[str] = field(default_factory=list)
    last_test_summary: str = "No tests executed yet."
    iteration: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentStatus":
        return cls(
            current_objective=str(payload.get("current_objective", "")),
            done=list(payload.get("done", [])),
            in_progress=list(payload.get("in_progress", [])),
            blockers=list(payload.get("blockers", [])),
            next_steps=list(payload.get("next_steps", [])),
            last_command_summary=list(payload.get("last_command_summary", [])),
            last_test_summary=str(payload.get("last_test_summary", "No tests executed yet.")),
            iteration=int(payload.get("iteration", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# AGENT_STATUS",
                "",
                "## Current Objective",
                self.current_objective or "Not set.",
                "",
                "## Done",
                *_render_list(self.done),
                "",
                "## In Progress",
                *_render_list(self.in_progress),
                "",
                "## Blockers",
                *_render_list(self.blockers),
                "",
                "## Next Steps",
                *_render_list(self.next_steps),
                "",
                "## Last Command Summary",
                *_render_list(self.last_command_summary),
                "",
                "## Last Test Summary",
                self.last_test_summary or "No tests executed yet.",
                "",
                "## Iteration",
                str(self.iteration),
                "",
            ]
        )


@dataclass
class HygieneReport:
    """Audit result used to detect context drift/corruption before iteration."""

    ok: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


@dataclass
class IterationReport:
    """Structured output of one PLAN->IMPLEMENT->RUN->OBSERVE cycle."""

    iteration_number: int
    goal: str
    plan: list[str]
    feature_id: str | None
    success: bool
    result: str
    next_step: str
    quality_gate_ok: bool | None = None
    bootstrap_notes: list[str] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


@dataclass
class TeamExecutionResult:
    """Execution result for one team handling one feature."""

    team_id: str
    feature_id: str
    success: bool
    message: str
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


@dataclass
class ParallelIterationReport:
    """Structured output of one parallel team iteration."""

    iteration_number: int
    team_count: int
    selected_feature_ids: list[str]
    success: bool
    result: str
    next_step: str
    quality_gate_ok: bool
    bootstrap_notes: list[str] = field(default_factory=list)
    team_results: list[TeamExecutionResult] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["team_results"] = [item.to_dict() for item in self.team_results]
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


def _render_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
