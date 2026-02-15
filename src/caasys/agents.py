"""Agent role definitions (programmer/operator)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .models import CommandResult, Feature


class ShellExecutor:
    """Thin shell wrapper used by both coding and operation agents."""

    def run(self, command: str, cwd: Path, phase: str, timeout_seconds: int = 120) -> CommandResult:
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.perf_counter() - started
        return CommandResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
            phase=phase,
        )


class ProgrammerAgent:
    """Executes implementation commands for one feature."""

    def __init__(self, executor: ShellExecutor | None = None, retry_once: bool = True) -> None:
        self._executor = executor or ShellExecutor()
        self._retry_once = retry_once

    def implement(self, feature: Feature, cwd: Path, dry_run: bool = False) -> list[CommandResult]:
        results: list[CommandResult] = []
        for command in feature.implementation_commands:
            if dry_run:
                results.append(
                    CommandResult(
                        command=command,
                        exit_code=0,
                        stdout="dry-run: command skipped",
                        stderr="",
                        duration_seconds=0.0,
                        phase="implement",
                    )
                )
                continue

            result = self._executor.run(command=command, cwd=cwd, phase="implement")
            results.append(result)
            if result.exit_code != 0 and self._retry_once:
                retry_result = self._executor.run(command=command, cwd=cwd, phase="implement-retry")
                results.append(retry_result)
                if retry_result.exit_code != 0:
                    break
                continue
            if result.exit_code != 0:
                break
        return results


class CodexProgrammerAgent:
    """Executes feature implementation by calling Codex CLI directly."""

    def __init__(
        self,
        *,
        cli_path: str = "codex",
        model: str = "gpt-5.3-codex",
        reasoning_effort: str = "xhigh",
        sandbox_mode: str = "workspace-write",
        full_auto: bool = True,
        skip_git_repo_check: bool = False,
        ephemeral: bool = False,
        timeout_seconds: int = 1800,
        retry_once: bool = True,
    ) -> None:
        self._cli_path = cli_path
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._sandbox_mode = sandbox_mode
        self._full_auto = full_auto
        self._skip_git_repo_check = skip_git_repo_check
        self._ephemeral = ephemeral
        self._timeout_seconds = timeout_seconds
        self._retry_once = retry_once

    def implement(
        self,
        feature: Feature,
        cwd: Path,
        dry_run: bool = False,
        *,
        objective: str | None = None,
        team_id: str | None = None,
        iteration_number: int | None = None,
    ) -> list[CommandResult]:
        prompt = self._build_prompt(
            feature=feature,
            objective=objective,
            team_id=team_id,
            iteration_number=iteration_number,
        )
        prompt = _normalize_prompt_for_codex_exec(prompt)
        command = self._build_command(cwd=cwd, prompt=prompt)
        command_text = _format_command(command)

        if dry_run:
            return [
                CommandResult(
                    command=command_text,
                    exit_code=0,
                    stdout="dry-run: codex implementation skipped",
                    stderr="",
                    duration_seconds=0.0,
                    phase="implement-codex",
                )
            ]

        first = self._run_codex(command=command, command_text=command_text, cwd=cwd, phase="implement-codex")
        if first.exit_code == 0 or not self._retry_once:
            return [first]

        retry = self._run_codex(
            command=command,
            command_text=command_text,
            cwd=cwd,
            phase="implement-codex-retry",
        )
        return [first, retry]

    def _build_command(self, *, cwd: Path, prompt: str) -> list[str]:
        command = [
            _normalize_cli_path(self._cli_path),
            "exec",
            "-m",
            self._model,
            "-c",
            f"model_reasoning_effort={json.dumps(self._reasoning_effort)}",
            "-C",
            str(cwd),
            "-s",
            self._sandbox_mode,
        ]
        if self._full_auto:
            command.append("--full-auto")
        if self._skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if self._ephemeral:
            command.append("--ephemeral")
        command.append(prompt)
        return command

    def _build_prompt(
        self,
        *,
        feature: Feature,
        objective: str | None,
        team_id: str | None,
        iteration_number: int | None,
    ) -> str:
        lines = [
            "You are a coding worker in an autonomous engineering loop.",
            "Implement exactly one feature in the current repository.",
            "Do not ask interactive questions. Choose pragmatic defaults and continue.",
            "Do not reply with readiness text like 'provide next task'; execute this feature now.",
            "Make concrete filesystem changes for this feature (create/update/delete files as needed).",
            "If the repository is empty, scaffold minimal runnable files first, then implement the feature.",
            "Do not run git commit or create branches. The outer system manages commits.",
            "After changes, run relevant checks/tests and fix obvious failures before finishing.",
            "",
            f"Feature ID: {feature.id}",
            f"Feature Category: {feature.category}",
            f"Feature Priority: {feature.priority}",
            f"Feature Description: {feature.description}",
        ]
        if objective:
            lines.append(f"Project Objective: {objective}")
        if iteration_number is not None:
            lines.append(f"Iteration: {iteration_number}")
        if team_id:
            lines.append(f"Assigned Team: {team_id}")

        if feature.implementation_commands:
            lines.extend(
                [
                    "",
                    "Implementation constraints/instructions from backlog item:",
                    *[f"- {item}" for item in feature.implementation_commands],
                ]
            )

        if feature.verification_command:
            lines.extend(
                [
                    "",
                    "A separate verification phase will run this command after your step:",
                    f"- {feature.verification_command}",
                ]
            )

        lines.extend(
            [
                "",
                "Output a short summary that includes:",
                "- files changed",
                "- checks run",
                "- remaining risks",
            ]
        )
        return "\n".join(lines)

    def _run_codex(
        self,
        *,
        command: list[str],
        command_text: str,
        cwd: Path,
        phase: str,
    ) -> CommandResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
            return CommandResult(
                command=command_text,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )
        except FileNotFoundError:
            return CommandResult(
                command=command_text,
                exit_code=127,
                stdout="",
                stderr="codex CLI not found in PATH",
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return CommandResult(
                command=command_text,
                exit_code=124,
                stdout=stdout,
                stderr=(stderr + "; timed out").strip("; "),
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )


class CodexPlannerAgent:
    """Splits one high-level task into multiple executable feature items."""

    def __init__(
        self,
        *,
        cli_path: str = "codex",
        model: str = "gpt-5.3-codex",
        reasoning_effort: str = "xhigh",
        sandbox_mode: str = "read-only",
        full_auto: bool = True,
        skip_git_repo_check: bool = False,
        ephemeral: bool = False,
        disable_shell_tool: bool = True,
        timeout_seconds: int = 1800,
    ) -> None:
        self._cli_path = cli_path
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._sandbox_mode = sandbox_mode
        self._full_auto = full_auto
        self._skip_git_repo_check = skip_git_repo_check
        self._ephemeral = ephemeral
        self._disable_shell_tool = disable_shell_tool
        self._timeout_seconds = timeout_seconds

    def plan_task(
        self,
        *,
        task_id: str,
        task_description: str,
        cwd: Path,
        max_features: int,
        default_category: str,
        parallel_safe_default: bool,
        objective: str | None = None,
        dry_run: bool = False,
    ) -> tuple[list[Feature], CommandResult, str, bool]:
        normalized_max_features = max(1, max_features)
        docker_available = _is_docker_compose_available(cwd)
        if dry_run:
            features = self._fallback_plan(
                task_id=task_id,
                task_description=task_description,
                max_features=normalized_max_features,
                default_category=default_category,
                parallel_safe_default=parallel_safe_default,
            )
            return (
                features,
                CommandResult(
                    command="codex planner dry-run",
                    exit_code=0,
                    stdout="dry-run: task decomposition skipped; fallback plan generated",
                    stderr="",
                    duration_seconds=0.0,
                    phase="plan-codex",
                ),
                json.dumps({"features": [item.to_dict() for item in features]}, ensure_ascii=True),
                True,
            )

        prompt = self._build_prompt(
            task_id=task_id,
            task_description=task_description,
            max_features=normalized_max_features,
            default_category=default_category,
            parallel_safe_default=parallel_safe_default,
            objective=objective,
        )
        prompt = _normalize_prompt_for_codex_exec(prompt)
        output_path = self._new_output_path(cwd)
        schema_path = self._new_schema_path(cwd=cwd, max_features=normalized_max_features)
        command = self._build_command(
            cwd=cwd,
            prompt=prompt,
            output_path=output_path,
            output_schema_path=schema_path,
        )
        command_text = _format_command(command)
        result = self._run_codex(command=command, command_text=command_text, cwd=cwd, phase="plan-codex")
        planner_output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        try:
            if output_path.exists():
                output_path.unlink()
            if schema_path.exists():
                schema_path.unlink()
        except OSError:
            pass

        if result.exit_code != 0:
            fallback_features = self._fallback_plan(
                task_id=task_id,
                task_description=task_description,
                max_features=normalized_max_features,
                default_category=default_category,
                parallel_safe_default=parallel_safe_default,
            )
            failure_output = planner_output or result.stderr or result.stdout
            return fallback_features, result, failure_output, True

        features = self._parse_features_from_output(
            task_id=task_id,
            planner_output=planner_output or result.stdout,
            max_features=normalized_max_features,
            default_category=default_category,
            parallel_safe_default=parallel_safe_default,
            docker_available=docker_available,
        )
        if len(features) == 1 and normalized_max_features > 1:
            fallback_features = self._fallback_plan(
                task_id=task_id,
                task_description=task_description,
                max_features=normalized_max_features,
                default_category=default_category,
                parallel_safe_default=parallel_safe_default,
            )
            return fallback_features, result, planner_output, True
        if features:
            return features, result, planner_output, False

        fallback_features = self._fallback_plan(
            task_id=task_id,
            task_description=task_description,
            max_features=normalized_max_features,
            default_category=default_category,
            parallel_safe_default=parallel_safe_default,
        )
        return fallback_features, result, planner_output, True

    def _new_output_path(self, cwd: Path) -> Path:
        state_dir = cwd / ".caasys"
        state_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="planner-output-",
            suffix=".txt",
            dir=str(state_dir),
            delete=False,
            encoding="utf-8",
        ) as handle:
            return Path(handle.name)

    def _build_command(
        self,
        *,
        cwd: Path,
        prompt: str,
        output_path: Path,
        output_schema_path: Path,
    ) -> list[str]:
        command = [
            _normalize_cli_path(self._cli_path),
            "exec",
            "-m",
            self._model,
            "-c",
            f"model_reasoning_effort={json.dumps(self._reasoning_effort)}",
            "-C",
            str(cwd),
            "-s",
            self._sandbox_mode,
            "-o",
            str(output_path),
            "--output-schema",
            str(output_schema_path),
        ]
        if self._full_auto:
            command.append("--full-auto")
        if self._skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if self._ephemeral:
            command.append("--ephemeral")
        if self._disable_shell_tool:
            command.extend(["--disable", "shell_tool"])
        command.append(prompt)
        return command

    def _build_prompt(
        self,
        *,
        task_id: str,
        task_description: str,
        max_features: int,
        default_category: str,
        parallel_safe_default: bool,
        objective: str | None,
    ) -> str:
        lines = [
            "You are a backlog decomposition engine.",
            "The full task text is provided inline below between TASK_DESCRIPTION_START and TASK_DESCRIPTION_END.",
            "Never claim the task is missing. Never ask for clarification.",
            "Infer pragmatic defaults from the provided task text and continue.",
            "Do not inspect workspace files. Do not call tools.",
            "Return valid JSON only. No markdown. No explanation. No role acknowledgement.",
            "",
            f"Task ID: {task_id}",
            "TASK_DESCRIPTION_START",
            task_description,
            "TASK_DESCRIPTION_END",
            f"Project Objective: {objective or 'Not provided'}",
            f"Max Features: {max_features}",
            f"Default Category: {default_category}",
            f"Default Parallel Safe: {str(parallel_safe_default).lower()}",
            "",
            "JSON schema:",
            "{",
            '  "features": [',
            "    {",
            '      "description": "string (required)",',
            '      "priority": 1,',
            '      "category": "string",',
            '      "parallel_safe": false,',
            '      "implementation_commands": ["string"],',
            '      "verification_command": "string or null"',
            "    }",
            "  ]",
            "}",
            "",
            "Constraints:",
            f"- Output between 2 and {max_features} features; prefer exactly {max_features}.",
            "- Keep feature descriptions concrete and implementation-ready.",
            "- Prefer small, testable increments.",
            "- Include verification_command whenever possible.",
            "- Do not output coordination-only or acknowledgement-only items.",
            "- Do not output blocker/clarification-only items.",
        ]
        return "\n".join(lines)

    def _new_schema_path(self, *, cwd: Path, max_features: int) -> Path:
        state_dir = cwd / ".caasys"
        state_dir.mkdir(parents=True, exist_ok=True)
        schema = {
            "type": "object",
            "properties": {
                "features": {
                    "type": "array",
                    "maxItems": max_features,
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "priority": {"type": "integer"},
                            "category": {"type": "string"},
                            "parallel_safe": {"type": "boolean"},
                            "implementation_commands": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "verification_command": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                            },
                        },
                        "required": [
                            "description",
                            "priority",
                            "category",
                            "parallel_safe",
                            "implementation_commands",
                            "verification_command",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["features"],
            "additionalProperties": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="planner-schema-",
            suffix=".json",
            dir=str(state_dir),
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(schema, ensure_ascii=True))
            return Path(handle.name)

    def _run_codex(
        self,
        *,
        command: list[str],
        command_text: str,
        cwd: Path,
        phase: str,
    ) -> CommandResult:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
            return CommandResult(
                command=command_text,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )
        except FileNotFoundError:
            return CommandResult(
                command=command_text,
                exit_code=127,
                stdout="",
                stderr="codex CLI not found in PATH",
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return CommandResult(
                command=command_text,
                exit_code=124,
                stdout=stdout,
                stderr=(stderr + "; timed out").strip("; "),
                duration_seconds=time.perf_counter() - started,
                phase=phase,
            )

    def _parse_features_from_output(
        self,
        *,
        task_id: str,
        planner_output: str,
        max_features: int,
        default_category: str,
        parallel_safe_default: bool,
        docker_available: bool,
    ) -> list[Feature]:
        payload = _extract_json_payload(planner_output)
        if payload is None:
            return []

        raw_items: list[Any] = []
        if isinstance(payload, dict):
            features_value = payload.get("features")
            if isinstance(features_value, list):
                raw_items = features_value
        elif isinstance(payload, list):
            raw_items = payload

        features: list[Feature] = []
        for idx, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                continue
            description = str(raw.get("description") or raw.get("title") or "").strip()
            if not description:
                continue
            if _looks_like_planner_acknowledgement(description):
                continue
            raw_impl = raw.get("implementation_commands")
            implementation_commands = _normalize_string_list(raw_impl)
            verification_value = raw.get("verification_command")
            if verification_value is None:
                verification_value = raw.get("verify")
            verification_command = (
                str(verification_value).strip() if isinstance(verification_value, str) else None
            )
            if verification_command == "":
                verification_command = None
            if verification_command:
                verification_command = _adapt_verification_command_for_environment(
                    verification_command,
                    docker_available=docker_available,
                )
            features.append(
                Feature(
                    id=f"{task_id}-{idx:02d}",
                    category=str(raw.get("category") or default_category),
                    description=description,
                    priority=_safe_int(raw.get("priority"), idx),
                    parallel_safe=bool(raw.get("parallel_safe", parallel_safe_default)),
                    implementation_commands=implementation_commands,
                    verification_command=verification_command,
                )
            )
            if len(features) >= max_features:
                break
        return features

    def _fallback_plan(
        self,
        *,
        task_id: str,
        task_description: str,
        max_features: int,
        default_category: str,
        parallel_safe_default: bool,
    ) -> list[Feature]:
        verify_scaffold = (
            'python -c "from pathlib import Path; import sys; entry=[Path(p) for p in '
            '(\'app/main.py\',\'src/main.py\',\'main.py\',\'app.py\')]; '
            'ok=Path(\'README.md\').exists() and any(p.exists() for p in entry); sys.exit(0 if ok else 1)"'
        )
        verify_provider = (
            'python -c "from pathlib import Path; import sys; '
            'mods=[p for p in Path(\'.\').rglob(\'*.py\') if any(k in p.stem.lower() for k in '
            '(\'provider\',\'quote\',\'market\',\'stock\',\'data\'))]; sys.exit(0 if mods else 1)"'
        )
        verify_analysis = (
            'python -c "from pathlib import Path; import sys; '
            'txt=\'\\n\'.join(p.read_text(encoding=\'utf-8\', errors=\'ignore\').lower() '
            'for p in Path(\'.\').rglob(\'*.py\')); '
            'ok=(\'analy\' in txt or \'analysis\' in txt) and \'disclaimer\' in txt; '
            'sys.exit(0 if ok else 1)"'
        )
        verify_tests = (
            'python -c "from pathlib import Path; import sys; '
            'tests=list(Path(\'.\').rglob(\'test_*.py\')); sys.exit(0 if tests else 1)"'
        )

        is_stock_task = _looks_like_stock_task(task_description)
        if is_stock_task:
            templates = [
                {
                    "description": f"Scaffold a Python API project and architecture docs for: {task_description}",
                    "implementation_commands": [
                        "Create a FastAPI-based project scaffold with app/, app/services/, app/providers/, and tests/.",
                        "Write README.md with architecture, data flow, and API contract summary.",
                        "Add .env.example with placeholders for market-data provider key and model key.",
                    ],
                    "verification_command": verify_scaffold,
                },
                {
                    "description": "Implement A-share market data ingestion and a normalized quote endpoint.",
                    "implementation_commands": [
                        "Implement a provider adapter for Chinese A-share data (for example AkShare/Tushare with a mock fallback).",
                        "Expose a quote endpoint that returns symbol, latest price, volume, change ratio, and trend/kline data.",
                        "Support common symbol formats such as 600519 and sh600519.",
                    ],
                    "verification_command": verify_provider,
                },
                {
                    "description": "Implement model-driven analysis pipeline based on live quote payload.",
                    "implementation_commands": [
                        "Create an analysis service that combines quote data and user question into a model prompt.",
                        "Expose an analyze endpoint that fetches latest quote data before model inference.",
                        "Return structured analysis fields and include a clear non-investment-advice disclaimer.",
                    ],
                    "verification_command": verify_analysis,
                },
                {
                    "description": "Add tests and usage documentation for quote and analysis workflows.",
                    "implementation_commands": [
                        "Add unit tests for symbol normalization and provider response mapping.",
                        "Add API tests for quote/analyze endpoints with mocked provider and model calls.",
                        "Update README with setup, run commands, and sample API requests.",
                    ],
                    "verification_command": verify_tests,
                },
            ]
        else:
            templates = [
                {
                    "description": f"Scaffold project structure and baseline docs for: {task_description}",
                    "implementation_commands": [
                        "Create an executable project skeleton with clear source and test directories.",
                        "Write README.md describing objective, architecture, and quick-start commands.",
                        "Add .env.example if external services or credentials are needed.",
                    ],
                    "verification_command": verify_scaffold,
                },
                {
                    "description": f"Implement the first core workflow for: {task_description}",
                    "implementation_commands": [
                        "Implement core domain logic and expose a minimal callable API/entrypoint.",
                        "Handle invalid input paths and return explicit error messages.",
                        "Keep logic modular for follow-up integration and testing.",
                    ],
                    "verification_command": verify_provider,
                },
                {
                    "description": f"Implement integration and orchestration layer for: {task_description}",
                    "implementation_commands": [
                        "Wire core workflow with service orchestration and request/response models.",
                        "Add configuration loading and dependency boundaries.",
                        "Add user-facing safety/disclaimer text where recommendations are generated.",
                    ],
                    "verification_command": verify_analysis,
                },
                {
                    "description": f"Add tests, validation checks, and runbook for: {task_description}",
                    "implementation_commands": [
                        "Add unit tests for critical logic and error handling branches.",
                        "Add smoke/integration tests for main API or CLI path.",
                        "Document test/run steps and expected outputs in README.",
                    ],
                    "verification_command": verify_tests,
                },
            ]

        features: list[Feature] = []
        selected = templates[: max(1, max_features)]
        for idx, item in enumerate(selected, start=1):
            features.append(
                Feature(
                    id=f"{task_id}-{idx:02d}",
                    category=default_category,
                    description=str(item["description"]),
                    priority=idx,
                    parallel_safe=parallel_safe_default,
                    implementation_commands=[str(entry) for entry in item["implementation_commands"]],
                    verification_command=str(item["verification_command"]),
                )
            )
        return features


class OperatorAgent:
    """Runs operational verification checks after implementation."""

    def __init__(self, executor: ShellExecutor | None = None, retry_once: bool = True) -> None:
        self._executor = executor or ShellExecutor()
        self._retry_once = retry_once

    def verify(self, feature: Feature, cwd: Path, dry_run: bool = False) -> list[CommandResult]:
        if not feature.verification_command:
            return []

        if dry_run:
            return [
                CommandResult(
                    command=feature.verification_command,
                    exit_code=0,
                    stdout="dry-run: verification skipped",
                    stderr="",
                    duration_seconds=0.0,
                    phase="verify",
                )
            ]

        result = self._executor.run(command=feature.verification_command, cwd=cwd, phase="verify")
        if result.exit_code == 0 or not self._retry_once:
            return [result]

        if _is_missing_docker_binary_error(result.stderr or result.stdout):
            fallback_command = _adapt_verification_command_for_environment(
                feature.verification_command,
                docker_available=False,
            )
            if fallback_command and fallback_command != feature.verification_command:
                fallback_result = self._executor.run(
                    command=fallback_command,
                    cwd=cwd,
                    phase="verify-no-docker",
                )
                if fallback_result.exit_code == 0:
                    notice = CommandResult(
                        command="verify-env-adapter",
                        exit_code=0,
                        stdout=(
                            "docker compose unavailable; switched to environment-compatible "
                            f"verification: {fallback_command}"
                        ),
                        stderr="",
                        duration_seconds=0.0,
                        phase="verify",
                    )
                    return [notice, fallback_result]
                retry_fallback = self._executor.run(
                    command=fallback_command,
                    cwd=cwd,
                    phase="verify-no-docker-retry",
                )
                if retry_fallback.exit_code == 0:
                    notice = CommandResult(
                        command="verify-env-adapter",
                        exit_code=0,
                        stdout=(
                            "docker compose unavailable; switched to environment-compatible "
                            f"verification: {fallback_command}"
                        ),
                        stderr="",
                        duration_seconds=0.0,
                        phase="verify",
                    )
                    return [notice, retry_fallback]
                return [result, fallback_result, retry_fallback]

        retry_result = self._executor.run(command=feature.verification_command, cwd=cwd, phase="verify-retry")
        return [result, retry_result]


def _is_docker_compose_available(cwd: Path) -> bool:
    try:
        completed = subprocess.run(
            ["docker", "compose", "version"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        return completed.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _is_missing_docker_binary_error(text: str) -> bool:
    lower = (text or "").lower()
    markers = [
        "'docker' is not recognized",
        "docker: command not found",
        "no such file or directory: 'docker'",
        "docker-compose: command not found",
    ]
    return any(marker in lower for marker in markers)


def _adapt_verification_command_for_environment(command: str, *, docker_available: bool) -> str:
    normalized = command.strip()
    if not normalized:
        return normalized
    if docker_available:
        return normalized

    lower = normalized.lower()
    if "docker compose" not in lower and "docker-compose" not in lower:
        return normalized

    segments = [item.strip() for item in normalized.split("&&") if item.strip()]
    kept = [item for item in segments if not _is_docker_compose_segment(item)]
    if kept:
        return " && ".join(kept)
    return 'python -c "print(\'docker unavailable, skipped docker-only verification\')"'


def _is_docker_compose_segment(command_segment: str) -> bool:
    lowered = command_segment.strip().lower()
    return "docker compose" in lowered or "docker-compose" in lowered


def _format_command(parts: list[str]) -> str:
    rendered: list[str] = []
    for part in parts:
        if not part or any(ch in part for ch in [' ', '"', "\t"]):
            escaped = part.replace('"', '\\"')
            rendered.append(f'"{escaped}"')
        else:
            rendered.append(part)
    return " ".join(rendered)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_json_payload(text: str) -> Any | None:
    candidate = text.strip()
    if not candidate:
        return None

    direct = _try_json_loads(candidate)
    if direct is not None:
        return direct

    fenced = _strip_markdown_fence(candidate)
    if fenced and fenced != candidate:
        parsed = _try_json_loads(fenced)
        if parsed is not None:
            return parsed

    for start_char, end_char in (("{", "}"), ("[", "]")):
        fragment = _extract_balanced_fragment(candidate, start_char=start_char, end_char=end_char)
        if not fragment:
            continue
        parsed = _try_json_loads(fragment)
        if parsed is not None:
            return parsed
    return None


def _try_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _strip_markdown_fence(value: str) -> str:
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) < 3:
        return value
    if not lines[-1].strip().startswith("```"):
        return value
    return "\n".join(lines[1:-1]).strip()


def _extract_balanced_fragment(value: str, *, start_char: str, end_char: str) -> str:
    start_index = value.find(start_char)
    if start_index < 0:
        return ""
    depth = 0
    for idx in range(start_index, len(value)):
        ch = value[idx]
        if ch == start_char:
            depth += 1
        elif ch == end_char:
            depth -= 1
            if depth == 0:
                return value[start_index : idx + 1]
    return ""


def _normalize_cli_path(cli_path: str) -> str:
    if os.name == "nt" and cli_path.strip().lower() == "codex":
        return "codex.cmd"
    return cli_path


def _normalize_prompt_for_codex_exec(prompt: str) -> str:
    # codex v0.101.0 in exec mode can behave as if only the first line is used.
    # Flattening keeps full intent in a single line and avoids "waiting for task" replies.
    segments = [segment.strip() for segment in prompt.splitlines() if segment.strip()]
    compact = " | ".join(segments)
    return compact if compact else prompt.strip()


def _looks_like_planner_acknowledgement(description: str) -> bool:
    lower = description.lower()
    markers = [
        "ready to act as",
        "share the target outcome",
        "i will return",
        "provide the first task",
        "planning worker",
        "operating in backlog decomposition mode",
        "share your backlog",
        "share your product goal",
        "awaiting backlog input",
        "task specification is missing",
        "missing task details",
        "clarify the missing task statement",
        "blocked on missing task",
    ]
    return any(marker in lower for marker in markers)


def _looks_like_stock_task(task_description: str) -> bool:
    lower = task_description.lower()
    markers = [
        "stock",
        "a-share",
        "a股",
        "股票",
        "quote",
        "kline",
        "market data",
        "行情",
        "成交量",
    ]
    return any(marker in lower for marker in markers)
