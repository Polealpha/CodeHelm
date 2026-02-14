"""Agent role definitions (programmer/operator)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

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

    def __init__(self, executor: ShellExecutor | None = None) -> None:
        self._executor = executor or ShellExecutor()

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
            if result.exit_code != 0:
                break
        return results


class OperatorAgent:
    """Runs operational verification checks after implementation."""

    def __init__(self, executor: ShellExecutor | None = None) -> None:
        self._executor = executor or ShellExecutor()

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

        return [self._executor.run(command=feature.verification_command, cwd=cwd, phase="verify")]
