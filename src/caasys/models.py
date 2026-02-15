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
    implementation_backend: str = "codex"
    planner_max_features_per_task: int = 4
    auto_resolve_duplicate_feature_ids: bool = True
    retry_failed_commands_once: bool = True
    run_smoke_before_iteration: bool = False
    smoke_test_command: str | None = 'python -m unittest discover -s tests -p "test_*.py" -v'
    codex_cli_path: str = "codex"
    codex_model: str = "gpt-5.3-codex"
    codex_reasoning_effort: str = "xhigh"
    ui_language: str = "en"
    codex_sandbox_mode: str = "workspace-write"
    codex_full_auto: bool = True
    codex_skip_git_repo_check: bool = True
    codex_ephemeral: bool = False
    codex_timeout_seconds: int = 1800
    planner_sandbox_mode: str = "read-only"
    planner_disable_shell_tool: bool = True
    enable_parallel_teams: bool = True
    default_parallel_teams: int = 4
    max_parallel_features_per_iteration: int = 8
    require_parallel_safe_flag: bool = False
    max_iterations_per_run: int = 20
    max_no_progress_iterations: int = 3
    stop_when_all_features_pass: bool = True
    stop_on_quality_gate_failure: bool = False
    require_browser_validation_before_stop: bool = False
    browser_validation_enabled: bool = False
    browser_validation_backend: str = "auto"
    browser_validation_url: str | None = None
    browser_validation_steps_file: str = ".caasys/browser_steps.json"
    browser_validation_headless: bool = True
    browser_validation_open_system_browser: bool = False
    osworld_mode_enabled: bool = True
    osworld_action_backend: str = "auto"
    osworld_steps_file: str = ".caasys/osworld_steps.json"
    osworld_headless: bool = True
    osworld_screenshot_dir: str = ".caasys/osworld_artifacts"
    osworld_enable_desktop_control: bool = False
    auto_handoff_enabled: bool = True
    handoff_after_iterations: int = 4
    handoff_on_no_progress_iterations: int = 2
    handoff_context_char_threshold: int = 16000
    handoff_max_tail_lines: int = 20
    handoff_summary_file: str = ".caasys/handoff_summary.json"
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
            implementation_backend=str(payload.get("implementation_backend", "codex")),
            planner_max_features_per_task=int(payload.get("planner_max_features_per_task", 4)),
            auto_resolve_duplicate_feature_ids=bool(payload.get("auto_resolve_duplicate_feature_ids", True)),
            retry_failed_commands_once=bool(payload.get("retry_failed_commands_once", True)),
            run_smoke_before_iteration=bool(payload.get("run_smoke_before_iteration", False)),
            smoke_test_command=payload.get("smoke_test_command"),
            codex_cli_path=str(payload.get("codex_cli_path", "codex")),
            codex_model=str(payload.get("codex_model", "gpt-5.3-codex")),
            codex_reasoning_effort=str(payload.get("codex_reasoning_effort", "xhigh")),
            ui_language=str(payload.get("ui_language", "en")),
            codex_sandbox_mode=str(payload.get("codex_sandbox_mode", "workspace-write")),
            codex_full_auto=bool(payload.get("codex_full_auto", True)),
            codex_skip_git_repo_check=bool(payload.get("codex_skip_git_repo_check", True)),
            codex_ephemeral=bool(payload.get("codex_ephemeral", False)),
            codex_timeout_seconds=int(payload.get("codex_timeout_seconds", 1800)),
            planner_sandbox_mode=str(payload.get("planner_sandbox_mode", "read-only")),
            planner_disable_shell_tool=bool(payload.get("planner_disable_shell_tool", True)),
            enable_parallel_teams=bool(payload.get("enable_parallel_teams", True)),
            default_parallel_teams=int(payload.get("default_parallel_teams", 4)),
            max_parallel_features_per_iteration=int(payload.get("max_parallel_features_per_iteration", 8)),
            require_parallel_safe_flag=bool(payload.get("require_parallel_safe_flag", False)),
            max_iterations_per_run=int(payload.get("max_iterations_per_run", 20)),
            max_no_progress_iterations=int(payload.get("max_no_progress_iterations", 3)),
            stop_when_all_features_pass=bool(payload.get("stop_when_all_features_pass", True)),
            stop_on_quality_gate_failure=bool(payload.get("stop_on_quality_gate_failure", False)),
            require_browser_validation_before_stop=bool(
                payload.get("require_browser_validation_before_stop", False)
            ),
            browser_validation_enabled=bool(payload.get("browser_validation_enabled", False)),
            browser_validation_backend=str(payload.get("browser_validation_backend", "auto")),
            browser_validation_url=payload.get("browser_validation_url"),
            browser_validation_steps_file=str(
                payload.get("browser_validation_steps_file", ".caasys/browser_steps.json")
            ),
            browser_validation_headless=bool(payload.get("browser_validation_headless", True)),
            browser_validation_open_system_browser=bool(
                payload.get("browser_validation_open_system_browser", False)
            ),
            osworld_mode_enabled=bool(payload.get("osworld_mode_enabled", True)),
            osworld_action_backend=str(payload.get("osworld_action_backend", "auto")),
            osworld_steps_file=str(payload.get("osworld_steps_file", ".caasys/osworld_steps.json")),
            osworld_headless=bool(payload.get("osworld_headless", True)),
            osworld_screenshot_dir=str(payload.get("osworld_screenshot_dir", ".caasys/osworld_artifacts")),
            osworld_enable_desktop_control=bool(payload.get("osworld_enable_desktop_control", False)),
            auto_handoff_enabled=bool(payload.get("auto_handoff_enabled", True)),
            handoff_after_iterations=int(payload.get("handoff_after_iterations", 4)),
            handoff_on_no_progress_iterations=int(payload.get("handoff_on_no_progress_iterations", 2)),
            handoff_context_char_threshold=int(payload.get("handoff_context_char_threshold", 16000)),
            handoff_max_tail_lines=int(payload.get("handoff_max_tail_lines", 20)),
            handoff_summary_file=str(payload.get("handoff_summary_file", ".caasys/handoff_summary.json")),
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
            f"- implementation_backend: `{self.implementation_backend}`",
            f"- planner_max_features_per_task: `{self.planner_max_features_per_task}`",
            f"- auto_resolve_duplicate_feature_ids: `{str(self.auto_resolve_duplicate_feature_ids).lower()}`",
            f"- retry_failed_commands_once: `{str(self.retry_failed_commands_once).lower()}`",
            f"- enable_parallel_teams: `{str(self.enable_parallel_teams).lower()}`",
            f"- default_parallel_teams: `{self.default_parallel_teams}`",
            f"- max_parallel_features_per_iteration: `{self.max_parallel_features_per_iteration}`",
            f"- require_parallel_safe_flag: `{str(self.require_parallel_safe_flag).lower()}`",
            "",
            "## Codex Execution",
            f"- codex_cli_path: `{self.codex_cli_path}`",
            f"- codex_model: `{self.codex_model}`",
            f"- codex_reasoning_effort: `{self.codex_reasoning_effort}`",
            f"- ui_language: `{self.ui_language}`",
            f"- codex_sandbox_mode: `{self.codex_sandbox_mode}`",
            f"- codex_full_auto: `{str(self.codex_full_auto).lower()}`",
            f"- codex_skip_git_repo_check: `{str(self.codex_skip_git_repo_check).lower()}`",
            f"- codex_ephemeral: `{str(self.codex_ephemeral).lower()}`",
            f"- codex_timeout_seconds: `{self.codex_timeout_seconds}`",
            f"- planner_sandbox_mode: `{self.planner_sandbox_mode}`",
            f"- planner_disable_shell_tool: `{str(self.planner_disable_shell_tool).lower()}`",
            "",
            "## Stop Criteria",
            f"- max_iterations_per_run: `{self.max_iterations_per_run}`",
            f"- max_no_progress_iterations: `{self.max_no_progress_iterations}`",
            f"- stop_when_all_features_pass: `{str(self.stop_when_all_features_pass).lower()}`",
            f"- stop_on_quality_gate_failure: `{str(self.stop_on_quality_gate_failure).lower()}`",
            f"- require_browser_validation_before_stop: `{str(self.require_browser_validation_before_stop).lower()}`",
            "",
            "## Browser Validation",
            f"- browser_validation_enabled: `{str(self.browser_validation_enabled).lower()}`",
            f"- browser_validation_backend: `{self.browser_validation_backend}`",
            f"- browser_validation_url: `{self.browser_validation_url or 'None'}`",
            f"- browser_validation_steps_file: `{self.browser_validation_steps_file}`",
            f"- browser_validation_headless: `{str(self.browser_validation_headless).lower()}`",
            f"- browser_validation_open_system_browser: "
            f"`{str(self.browser_validation_open_system_browser).lower()}`",
            "",
            "## OSWorld Mode",
            f"- osworld_mode_enabled: `{str(self.osworld_mode_enabled).lower()}`",
            f"- osworld_action_backend: `{self.osworld_action_backend}`",
            f"- osworld_steps_file: `{self.osworld_steps_file}`",
            f"- osworld_headless: `{str(self.osworld_headless).lower()}`",
            f"- osworld_screenshot_dir: `{self.osworld_screenshot_dir}`",
            f"- osworld_enable_desktop_control: `{str(self.osworld_enable_desktop_control).lower()}`",
            "",
            "## Auto Handoff",
            f"- auto_handoff_enabled: `{str(self.auto_handoff_enabled).lower()}`",
            f"- handoff_after_iterations: `{self.handoff_after_iterations}`",
            f"- handoff_on_no_progress_iterations: `{self.handoff_on_no_progress_iterations}`",
            f"- handoff_context_char_threshold: `{self.handoff_context_char_threshold}`",
            f"- handoff_max_tail_lines: `{self.handoff_max_tail_lines}`",
            f"- handoff_summary_file: `{self.handoff_summary_file}`",
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
    skipped_feature_ids: list[str] = field(default_factory=list)
    bootstrap_notes: list[str] = field(default_factory=list)
    team_results: list[TeamExecutionResult] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["team_results"] = [item.to_dict() for item in self.team_results]
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


@dataclass
class BrowserValidationReport:
    """Result of browser-based or HTTP-based validation checks."""

    success: bool
    backend: str
    url: str
    message: str
    checks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


@dataclass
class StopDecision:
    """Decision output for determining whether a project loop should stop."""

    should_stop: bool
    reason: str
    success: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectRunReport:
    """Summary of a full autonomous project loop run."""

    mode: str
    iterations_executed: int
    success: bool
    stop_reason: str
    final_passed_features: int
    total_features: int
    reports: list[dict[str, Any]] = field(default_factory=list)
    quality_gate_failures: int = 0
    no_progress_iterations: int = 0
    browser_validation: BrowserValidationReport | None = None
    handoff_events: list[dict[str, Any]] = field(default_factory=list)
    osworld_runs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.browser_validation:
            payload["browser_validation"] = self.browser_validation.to_dict()
        return payload


@dataclass
class HandoffReport:
    """Snapshot emitted when automatic handoff is triggered."""

    triggered: bool
    reason: str
    iteration: int
    context_chars: int
    summary_file: str
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OSWorldActionResult:
    """One action execution result in OSWorld mode."""

    action: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OSWorldRunReport:
    """Report from OSWorld-style browser/desktop task execution."""

    success: bool
    backend: str
    message: str
    actions: list[OSWorldActionResult] = field(default_factory=list)
    command_results: list[CommandResult] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [item.to_dict() for item in self.actions]
        payload["command_results"] = [item.to_dict() for item in self.command_results]
        return payload


def _render_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
