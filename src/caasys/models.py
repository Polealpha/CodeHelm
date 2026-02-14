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
            implementation_commands=list(payload.get("implementation_commands", [])),
            verification_command=payload.get("verification_command"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
class IterationReport:
    """Structured output of one PLAN->IMPLEMENT->RUN->OBSERVE cycle."""

    iteration_number: int
    goal: str
    plan: list[str]
    feature_id: str | None
    success: bool
    result: str
    next_step: str
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


def _render_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
