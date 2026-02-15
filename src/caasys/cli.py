"""Command-line interface for CodeHelm."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Event, Thread
from time import sleep, time
from typing import Callable, TypeVar

from .engine import ContinuousEngine
from .models import Feature

COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_CYAN = "\033[36m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_DIM = "\033[2m"
APP_NAME = "CodeHelm"

MODEL_PRESETS = [
    "gpt-5.3-codex",
    "gpt-5-codex",
    "gpt-5",
    "gpt-4.1",
]

REASONING_PRESETS = ["low", "medium", "high", "xhigh"]
SPINNER_FRAMES = "|/-\\"
T = TypeVar("T")

LANGUAGE_PRESETS = ["en", "zh"]
LANGUAGE_LABELS = {"en": "English", "zh": "\u4e2d\u6587"}
LANGUAGE_ALIASES = {
    "en": "en",
    "english": "en",
    "en-us": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "cn": "zh",
    "chinese": "zh",
    "\u4e2d\u6587": "zh",
    "\u6c49\u8bed": "zh",
    "\u6f22\u8a9e": "zh",
}

SLASH_COMMAND_ALIASES = {
    "\u5e2e\u52a9": "help",
    "\u8aaa\u660e": "help",
    "\u8bf4\u660e": "help",
    "\u6e05\u5c4f": "clear",
    "\u9000\u51fa": "quit",
    "\u72b6\u6001": "status",
    "\u4efb\u52d9": "tasks",
    "\u4efb\u52a1": "tasks",
    "\u529f\u80fd": "features",
    "\u7279\u6027": "features",
    "\u7b56\u7565": "policy",
    "\u914d\u7f6e": "config",
    "\u8fdb\u7a0b": "agents",
    "\u6a21\u578b": "model",
    "\u540e\u7aef": "backend",
    "\u81ea\u52a8": "auto",
    "\u653e\u5bbd": "unsafe",
    "\u95e8\u7981": "unsafe",
    "\u6a21\u5f0f": "mode",
    "\u8fd0\u884c": "run",
    "\u7ee7\u7eed": "continue",
    "\u7e7c\u7e8c": "continue",
    "\u8ba1\u5212": "plan",
    "\u5386\u53f2": "history",
    "\u6b77\u53f2": "history",
    "\u8bed\u8a00": "language",
    "\u8be6\u7ec6": "verbose",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codehelm",
        description="CodeHelm autonomous engine that steers software projects from idea to shipment",
    )
    parser.add_argument("--root", default=".", help="Project root directory (default: current directory)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize state artifacts")
    init_parser.add_argument("--objective", required=True, help="Current project objective")
    init_parser.add_argument(
        "--allow-questions",
        action="store_true",
        help="Disable zero-ask mode (default keeps zero-ask enabled).",
    )

    add_parser = subparsers.add_parser("add-feature", help="Add one feature to feature_list.json")
    add_parser.add_argument("--id", required=True, dest="feature_id")
    add_parser.add_argument("--category", default="functional")
    add_parser.add_argument("--description", required=True)
    add_parser.add_argument("--priority", type=int, default=100)
    add_parser.add_argument(
        "--parallel-safe",
        action="store_true",
        help="Mark this feature safe to execute in parallel team mode.",
    )
    add_parser.add_argument("--impl", action="append", default=[], help="Implementation command (repeatable)")
    add_parser.add_argument("--verify", default=None, help="Verification command")

    plan_task_parser = subparsers.add_parser(
        "plan-task",
        help="Use Codex planner to split one high-level task into multiple features",
    )
    plan_task_parser.add_argument("--task-id", required=True)
    plan_task_parser.add_argument("--description", required=True)
    plan_task_parser.add_argument("--max-features", type=int, default=None)
    plan_task_parser.add_argument("--category", default="functional")
    plan_task_parser.add_argument("--parallel-safe", action="store_true")
    plan_task_parser.add_argument("--model", default=None, help="Optional planner model override")
    plan_task_parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Optional planner reasoning effort override (for example: high, xhigh).",
    )
    plan_task_parser.add_argument("--dry-run", action="store_true")

    set_model_parser = subparsers.add_parser(
        "set-model",
        help="Update model/backend settings in policy",
    )
    set_model_parser.add_argument("--cli-path", default=None, help="Codex CLI executable path")
    set_model_parser.add_argument("--implementation-backend", choices=["codex", "shell", "auto"], default=None)
    set_model_parser.add_argument("--model", default=None)
    set_model_parser.add_argument("--reasoning-effort", default=None)
    set_model_parser.add_argument("--ui-language", choices=["en", "zh"], default=None)
    set_model_parser.add_argument("--sandbox", choices=["read-only", "workspace-write", "danger-full-access"], default=None)
    set_model_parser.add_argument(
        "--planner-sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default=None,
    )
    set_model_parser.add_argument("--timeout-seconds", type=int, default=None)
    set_model_parser.add_argument("--planner-max-features", type=int, default=None)
    set_model_parser.add_argument(
        "--full-auto",
        dest="full_auto",
        action="store_true",
        help="Enable Codex full-auto execution mode.",
    )
    set_model_parser.add_argument(
        "--no-full-auto",
        dest="full_auto",
        action="store_false",
        help="Disable Codex full-auto execution mode.",
    )
    set_model_parser.add_argument(
        "--skip-git-repo-check",
        dest="skip_git_repo_check",
        action="store_true",
        help="Enable --skip-git-repo-check for Codex worker calls.",
    )
    set_model_parser.add_argument(
        "--no-skip-git-repo-check",
        dest="skip_git_repo_check",
        action="store_false",
        help="Disable --skip-git-repo-check for Codex worker calls.",
    )
    set_model_parser.add_argument(
        "--ephemeral",
        dest="ephemeral",
        action="store_true",
        help="Enable --ephemeral for Codex worker calls.",
    )
    set_model_parser.add_argument(
        "--no-ephemeral",
        dest="ephemeral",
        action="store_false",
        help="Disable --ephemeral for Codex worker calls.",
    )
    set_model_parser.add_argument(
        "--planner-disable-shell-tool",
        dest="planner_disable_shell_tool",
        action="store_true",
        help="Disable Codex shell tool during task decomposition.",
    )
    set_model_parser.add_argument(
        "--planner-enable-shell-tool",
        dest="planner_disable_shell_tool",
        action="store_false",
        help="Enable Codex shell tool during task decomposition.",
    )
    set_model_parser.set_defaults(full_auto=None, skip_git_repo_check=None, ephemeral=None)
    set_model_parser.set_defaults(planner_disable_shell_tool=None)

    agents_parser = subparsers.add_parser("agents", help="List running AI-related processes")
    agents_parser.add_argument("--limit", type=int, default=30)
    agents_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all processes instead of AI-related processes only",
    )
    agents_parser.add_argument("--json", action="store_true")

    subparsers.add_parser("status", help="Print AGENT_STATUS.md")
    subparsers.add_parser("features", help="Print feature list JSON")
    subparsers.add_parser("policy", help="Print active agent policy")
    subparsers.add_parser("bootstrap", help="Run bootstrap context scan")

    gate_parser = subparsers.add_parser("quality-gate", help="Run anti-context-rot checks")
    gate_parser.add_argument("--dry-run", action="store_true", help="Skip actual smoke command execution")
    gate_parser.add_argument(
        "--no-smoke",
        action="store_true",
        help="Do not run smoke command in quality gate for this invocation",
    )

    iterate_parser = subparsers.add_parser("iterate", help="Run one iteration")
    iterate_parser.add_argument("--commit", action="store_true", help="Attempt git commit after iteration")
    iterate_parser.add_argument("--dry-run", action="store_true", help="Skip actual command execution")

    iterate_parallel_parser = subparsers.add_parser("iterate-parallel", help="Run one parallel-team iteration")
    iterate_parallel_parser.add_argument("--teams", type=int, default=None, help="Parallel team count")
    iterate_parallel_parser.add_argument(
        "--max-features",
        type=int,
        default=None,
        help="Max pending features to schedule in this round",
    )
    iterate_parallel_parser.add_argument("--force-unsafe", action="store_true")
    iterate_parallel_parser.add_argument("--commit", action="store_true", help="Attempt git commit after iteration")
    iterate_parallel_parser.add_argument("--dry-run", action="store_true", help="Skip actual command execution")

    run_project_parser = subparsers.add_parser("run-project", help="Run project loop until stop criteria")
    run_project_parser.add_argument("--mode", choices=["single", "parallel"], default="single")
    run_project_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Max full epochs (one epoch = one full pass over pending features).",
    )
    run_project_parser.add_argument("--teams", type=int, default=None)
    run_project_parser.add_argument("--max-features", type=int, default=None)
    run_project_parser.add_argument("--force-unsafe", action="store_true")
    run_project_parser.add_argument("--browser-validate-on-stop", action="store_true")
    run_project_parser.add_argument("--commit", action="store_true", help="Attempt git commit during iterations")
    run_project_parser.add_argument("--dry-run", action="store_true", help="Skip actual command execution")

    browser_parser = subparsers.add_parser("browser-validate", help="Run browser or HTTP validation checks")
    browser_parser.add_argument("--url", default=None, help="Target URL (defaults to policy browser_validation_url)")
    browser_parser.add_argument(
        "--backend",
        choices=["auto", "playwright", "system", "http"],
        default=None,
        help="Validation backend (defaults to policy setting).",
    )
    browser_parser.add_argument("--steps-file", default=None, help="JSON steps file for browser actions")
    browser_parser.add_argument("--expect-text", default=None, help="Expect text in final page/response")
    browser_parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Run browser in non-headless mode when backend supports it.",
    )
    browser_parser.add_argument(
        "--open-system-browser",
        action="store_true",
        help="Open your desktop browser after validation.",
    )
    browser_parser.add_argument("--dry-run", action="store_true")

    osworld_parser = subparsers.add_parser("osworld-run", help="Run OSWorld-style action script")
    osworld_parser.add_argument("--backend", choices=["auto", "playwright", "desktop", "http"], default=None)
    osworld_parser.add_argument("--steps-file", default=None)
    osworld_parser.add_argument("--url", default=None)
    osworld_parser.add_argument("--show-browser", action="store_true")
    osworld_parser.add_argument("--enable-desktop-control", action="store_true")
    osworld_parser.add_argument("--dry-run", action="store_true")

    interactive_parser = subparsers.add_parser(
        "interactive",
        help="Start interactive CodeHelm console (task in, plan, distribute, run)",
    )
    interactive_parser.add_argument("--mode", choices=["single", "parallel"], default="parallel")
    interactive_parser.add_argument("--teams", type=int, default=None)
    interactive_parser.add_argument("--max-iterations", type=int, default=None)
    interactive_parser.add_argument("--max-features", type=int, default=None)
    interactive_parser.add_argument(
        "--parallel-safe",
        dest="parallel_safe",
        action="store_true",
        help="Plan new features with parallel_safe=true (default).",
    )
    interactive_parser.add_argument(
        "--no-parallel-safe",
        dest="parallel_safe",
        action="store_false",
        help="Plan new features with parallel_safe=false.",
    )
    interactive_parser.set_defaults(parallel_safe=True)
    interactive_parser.add_argument("--category", default="functional")
    interactive_parser.add_argument("--no-auto-run", action="store_true")
    interactive_parser.add_argument("--dry-run", action="store_true")
    interactive_parser.add_argument("--once", default=None, help="Run one task directly and exit")
    interactive_parser.add_argument("--model", default=None, help="Override planner model for this session")
    interactive_parser.add_argument("--reasoning-effort", default=None, help="Override planner reasoning effort")
    interactive_parser.add_argument("--language", choices=["en", "zh"], default=None, help="Interactive UI language")

    serve_parser = subparsers.add_parser("serve", help="Run local HTTP control server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    engine = ContinuousEngine(root=root)

    if args.command == "init":
        status = engine.initialize(objective=args.objective, zero_ask=not args.allow_questions)
        print(f"Initialized objective: {status.current_objective}")
        return 0

    if args.command == "add-feature":
        feature = Feature(
            id=args.feature_id,
            category=args.category,
            description=args.description,
            priority=args.priority,
            parallel_safe=args.parallel_safe,
            implementation_commands=args.impl,
            verification_command=args.verify,
        )
        engine.add_feature(feature)
        print(f"Added feature {feature.id}")
        return 0

    if args.command == "plan-task":
        language = engine.get_policy().ui_language
        report = _run_with_live_activity(
            engine=engine,
            language=language,
            operation_label=_lang_text(language, "plan", "瑙勫垝"),
            run_fn=lambda: engine.plan_task(
                task_id=args.task_id,
                description=args.description,
                max_features=args.max_features,
                category=args.category,
                parallel_safe=args.parallel_safe,
                dry_run=args.dry_run,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
            ),
        )
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0 if bool(report.get("success")) else 2

    if args.command == "set-model":
        policy = engine.set_model_settings(
            cli_path=args.cli_path,
            implementation_backend=args.implementation_backend,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            ui_language=args.ui_language,
            sandbox_mode=args.sandbox,
            full_auto=args.full_auto,
            skip_git_repo_check=args.skip_git_repo_check,
            ephemeral=args.ephemeral,
            timeout_seconds=args.timeout_seconds,
            planner_sandbox_mode=args.planner_sandbox,
            planner_disable_shell_tool=args.planner_disable_shell_tool,
            planner_max_features_per_task=args.planner_max_features,
        )
        print(json.dumps(policy.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "interactive":
        return _run_interactive(
            engine=engine,
            mode=args.mode,
            team_count=args.teams,
            max_iterations=args.max_iterations,
            max_features=args.max_features,
            parallel_safe=args.parallel_safe,
            category=args.category,
            auto_run=not args.no_auto_run,
            dry_run=args.dry_run,
            once=args.once,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            language=args.language,
        )

    if args.command == "agents":
        report = _list_ai_processes(limit=args.limit, include_all=args.all)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=True))
        else:
            _print_agents_report(report, language=engine.get_policy().ui_language)
        return 0 if report["ok"] else 2

    if args.command == "status":
        path = root / "AGENT_STATUS.md"
        if not path.exists():
            print("AGENT_STATUS.md not found. Run `init` first (for example: `caasys init`).")
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "features":
        features = [item.to_dict() for item in engine.list_features()]
        print(json.dumps(features, indent=2, ensure_ascii=True))
        return 0

    if args.command == "policy":
        policy = engine.get_policy()
        print(json.dumps(policy.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "bootstrap":
        notes, command_results = engine.bootstrap_session()
        payload = {
            "notes": notes,
            "command_results": [item.to_dict() for item in command_results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return 0

    if args.command == "quality-gate":
        gate = engine.run_quality_gate(dry_run=args.dry_run, run_smoke=not args.no_smoke)
        print(json.dumps(gate.to_dict(), indent=2, ensure_ascii=True))
        return 0 if gate.ok else 2

    if args.command == "iterate":
        language = engine.get_policy().ui_language
        report = _run_with_live_activity(
            engine=engine,
            language=language,
            operation_label=_lang_text(language, "run", "\u8fd0\u884c"),
            run_fn=lambda: engine.run_iteration(commit=args.commit, dry_run=args.dry_run),
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "iterate-parallel":
        language = engine.get_policy().ui_language
        report = _run_with_live_activity(
            engine=engine,
            language=language,
            operation_label=_lang_text(language, "run", "\u8fd0\u884c"),
            run_fn=lambda: engine.run_parallel_iteration(
                team_count=args.teams,
                max_features=args.max_features,
                commit=args.commit,
                dry_run=args.dry_run,
                force_unsafe=args.force_unsafe,
            ),
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0 if report.success else 2

    if args.command == "run-project":
        language = engine.get_policy().ui_language
        report = _run_with_live_activity(
            engine=engine,
            language=language,
            operation_label=_lang_text(language, "run", "\u8fd0\u884c"),
            run_fn=lambda: engine.run_project_loop(
                mode=args.mode,
                max_iterations=args.max_iterations,
                team_count=args.teams,
                max_features=args.max_features,
                force_unsafe=args.force_unsafe,
                commit=args.commit,
                dry_run=args.dry_run,
                browser_validate_on_stop=args.browser_validate_on_stop,
            ),
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0 if report.success else 2

    if args.command == "browser-validate":
        report = engine.run_browser_validation(
            url=args.url,
            backend=args.backend,
            steps_file=args.steps_file,
            expect_text=args.expect_text,
            headless=not args.show_browser,
            open_system_browser=args.open_system_browser,
            dry_run=args.dry_run,
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0 if report.success else 2

    if args.command == "osworld-run":
        report = engine.run_osworld_mode(
            backend=args.backend,
            steps_file=args.steps_file,
            url=args.url,
            headless=not args.show_browser,
            enable_desktop_control=args.enable_desktop_control,
            dry_run=args.dry_run,
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0 if report.success else 2

    if args.command == "serve":
        from .server import run_server

        run_server(root=root, host=args.host, port=args.port)
        return 0

    parser.print_help()
    return 1


def _run_interactive(
    *,
    engine: ContinuousEngine,
    mode: str,
    team_count: int | None,
    max_iterations: int | None,
    max_features: int | None,
    parallel_safe: bool,
    category: str,
    auto_run: bool,
    dry_run: bool,
    once: str | None,
    model: str | None,
    reasoning_effort: str | None,
    language: str | None,
) -> int:
    policy = engine.get_policy()
    preferred_language = _normalize_language(language or policy.ui_language) or "en"
    if preferred_language != policy.ui_language:
        policy = engine.set_model_settings(ui_language=preferred_language)

    resolved_team_count = team_count
    if resolved_team_count is None and mode == "parallel":
        resolved_team_count = _recommended_parallel_teams(policy.default_parallel_teams)
    resolved_max_features = max_features
    if resolved_max_features is None and mode == "parallel":
        baseline = policy.max_parallel_features_per_iteration
        if isinstance(resolved_team_count, int) and resolved_team_count > 0:
            baseline = max(baseline, resolved_team_count * 2)
        resolved_max_features = baseline

    session_state: dict[str, object] = {
        "mode": mode,
        "team_count": resolved_team_count,
        "max_iterations": max_iterations,
        "max_features": resolved_max_features,
        "parallel_safe": parallel_safe,
        "category": category,
        "auto_run": auto_run,
        "dry_run": dry_run,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "language": preferred_language,
        "verbose": False,
        "force_unsafe": mode == "parallel",
        "last_run_epochs": max_iterations,
        "history_records": {},
        "history_context": "",
    }

    if once:
        return _handle_task_input(
            engine=engine,
            task_description=once,
            mode=str(session_state["mode"]),
            team_count=session_state["team_count"],  # type: ignore[arg-type]
            max_iterations=session_state["max_iterations"],  # type: ignore[arg-type]
            max_features=session_state["max_features"],  # type: ignore[arg-type]
            parallel_safe=bool(session_state["parallel_safe"]),
            category=str(session_state["category"]),
            auto_run=bool(session_state["auto_run"]),
            force_unsafe=bool(session_state.get("force_unsafe", False)),
            dry_run=bool(session_state["dry_run"]),
            model=session_state["model"],  # type: ignore[arg-type]
            reasoning_effort=session_state["reasoning_effort"],  # type: ignore[arg-type]
            language=_session_language(session_state),
            verbose=bool(session_state.get("verbose", False)),
            session_state=session_state,
        )

    _clear_screen()
    _render_builder_header(engine=engine, session_state=session_state)

    while True:
        try:
            raw = input(_styled("codehelm> ", COLOR_CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return 0

        if not raw:
            continue
        if raw.startswith("/"):
            action = _handle_slash_command(engine=engine, raw=raw, session_state=session_state)
            if action == "exit":
                return 0
            if action == "refresh":
                _clear_screen()
                _render_builder_header(engine=engine, session_state=session_state)
            continue

        code = _handle_task_input(
            engine=engine,
            task_description=raw,
            mode=str(session_state["mode"]),
            team_count=session_state["team_count"],  # type: ignore[arg-type]
            max_iterations=session_state["max_iterations"],  # type: ignore[arg-type]
            max_features=session_state["max_features"],  # type: ignore[arg-type]
            parallel_safe=bool(session_state["parallel_safe"]),
            category=str(session_state["category"]),
            auto_run=bool(session_state["auto_run"]),
            force_unsafe=bool(session_state.get("force_unsafe", False)),
            dry_run=bool(session_state["dry_run"]),
            model=session_state["model"],  # type: ignore[arg-type]
            reasoning_effort=session_state["reasoning_effort"],  # type: ignore[arg-type]
            language=_session_language(session_state),
            verbose=bool(session_state.get("verbose", False)),
            session_state=session_state,
        )
        if code != 0:
            print("Task handling failed. You can retry with a more specific description.")


def _handle_slash_command(
    *,
    engine: ContinuousEngine,
    raw: str,
    session_state: dict[str, object],
) -> str:
    line = raw[1:].strip()
    if not line:
        return "continue"
    if " " in line:
        command, arg_text = line.split(" ", 1)
    else:
        command, arg_text = line, ""
    command = _normalize_slash_command(command)
    arg_text = arg_text.strip()
    language = _session_language(session_state)

    if command in {"quit", "exit"}:
        return "exit"
    if command in {"help", "?"}:
        _print_help_panel(language=language)
        return "continue"
    if command in {"clear", "cls"}:
        return "refresh"
    if command == "status":
        print(engine.get_status().to_markdown())
        return "continue"
    if command in {"features", "tasks"}:
        print(json.dumps([item.to_dict() for item in engine.list_features()], indent=2, ensure_ascii=True))
        return "continue"
    if command in {"policy", "config"}:
        print(json.dumps(engine.get_policy().to_dict(), indent=2, ensure_ascii=True))
        return "continue"
    if command == "history":
        _handle_history_command(
            engine=engine,
            session_state=session_state,
            arg_text=arg_text,
            language=language,
        )
        return "continue"
    if command in {"agents", "ps"}:
        include_all, limit = _parse_agents_args(arg_text=arg_text, default_limit=30)
        _print_agents_report(_list_ai_processes(limit=limit, include_all=include_all), language=language)
        return "continue"
    if command in {"model", "models"}:
        if arg_text:
            result = _apply_model_from_text(
                engine=engine,
                session_state=session_state,
                arg_text=arg_text,
                language=language,
            )
            if not result:
                print(_lang_text(language, "Usage: /model [model_id] [low|medium|high|xhigh]", "\u7528\u6cd5: /model [\u6a21\u578bID] [low|medium|high|xhigh]"))
        else:
            _interactive_model_picker(engine=engine, session_state=session_state, language=language)
        return "refresh"
    if command == "language":
        if arg_text:
            if not _apply_language(engine=engine, session_state=session_state, value=arg_text):
                print(_lang_text(language, "Usage: /language [en|zh|English|\u4e2d\u6587]", "\u7528\u6cd5: /language [en|zh|English|\u4e2d\u6587]"))
        else:
            _interactive_language_picker(engine=engine, session_state=session_state)
        return "refresh"
    if command == "backend":
        backend = _normalize_backend_value(arg_text)
        if backend in {"codex", "shell", "auto"}:
            updated = engine.set_model_settings(implementation_backend=backend)
            print(f"backend={updated.implementation_backend}")
            return "refresh"
        print(_lang_text(language, "Usage: /backend codex|shell|auto", "\u7528\u6cd5: /backend codex|shell|auto"))
        return "continue"
    if command == "auto":
        lowered = _normalize_auto_value(arg_text)
        if lowered in {"on", "1", "true"}:
            session_state["auto_run"] = True
            return "refresh"
        if lowered in {"off", "0", "false"}:
            session_state["auto_run"] = False
            return "refresh"
        print(_lang_text(language, "Usage: /auto on|off", "\u7528\u6cd5: /auto on|off\uff08\u6216 \u5f00|\u5173\uff09"))
        return "continue"
    if command == "unsafe":
        lowered = _normalize_auto_value(arg_text)
        if not lowered:
            enabled = bool(session_state.get("force_unsafe", False))
            print(
                _lang_text(
                    language,
                    f"unsafe={'on' if enabled else 'off'}",
                    f"\u653e\u5bbd\u95e8\u7981={'\u5f00' if enabled else '\u5173'}",
                )
            )
            return "continue"
        if lowered in {"on", "1", "true"}:
            session_state["force_unsafe"] = True
            return "refresh"
        if lowered in {"off", "0", "false"}:
            session_state["force_unsafe"] = False
            return "refresh"
        print(
            _lang_text(
                language,
                "Usage: /unsafe on|off",
                "\u7528\u6cd5: /unsafe on|off\uff08\u6216 \u5f00|\u5173\uff09",
            )
        )
        return "continue"
    if command == "mode":
        lowered = _normalize_mode_value(arg_text)
        if lowered in {"single", "parallel"}:
            session_state["mode"] = lowered
            if lowered == "parallel":
                session_state["force_unsafe"] = True
            return "refresh"
        print("Usage: /mode single|parallel")
        return "continue"
    if command == "verbose":
        lowered = arg_text.lower().strip()
        if not lowered:
            enabled = bool(session_state.get("verbose", False))
            print(f"verbose={'on' if enabled else 'off'}")
            return "continue"
        if lowered in {"on", "1", "true"}:
            session_state["verbose"] = True
            return "refresh"
        if lowered in {"off", "0", "false"}:
            session_state["verbose"] = False
            return "refresh"
        print("Usage: /verbose on|off")
        return "continue"
    if command == "run":
        result = _run_project_from_state(engine=engine, session_state=session_state)
        if result != 0:
            print("Run completed with non-success stop reason.")
        return "continue"
    if command in {"continue", "resume"}:
        forced_epochs = None
        if arg_text:
            forced_epochs = _parse_manual_iteration_count(arg_text)
            if forced_epochs is None:
                print(
                    _lang_text(
                        language,
                        "Usage: /continue [positive_integer]",
                        "\u7528\u6cd5: /continue [\u6b63\u6574\u6570]",
                    )
                )
                return "continue"
        result = _run_project_from_state(
            engine=engine,
            session_state=session_state,
            prompt_for_iterations=False,
            forced_max_iterations=forced_epochs,
        )
        if result != 0:
            print("Run completed with non-success stop reason.")
        return "continue"
    if command == "plan":
        if not arg_text:
            print(_lang_text(language, "Usage: /plan <task description>", "\u7528\u6cd5: /plan <\u4efb\u52a1\u63cf\u8ff0>"))
            return "continue"
        result = _handle_task_input(
            engine=engine,
            task_description=arg_text,
            mode=str(session_state["mode"]),
            team_count=session_state["team_count"],  # type: ignore[arg-type]
            max_iterations=session_state["max_iterations"],  # type: ignore[arg-type]
            max_features=session_state["max_features"],  # type: ignore[arg-type]
            parallel_safe=bool(session_state["parallel_safe"]),
            category=str(session_state["category"]),
            auto_run=False,
            force_unsafe=bool(session_state.get("force_unsafe", False)),
            dry_run=bool(session_state["dry_run"]),
            model=session_state["model"],  # type: ignore[arg-type]
            reasoning_effort=session_state["reasoning_effort"],  # type: ignore[arg-type]
            language=language,
            verbose=bool(session_state.get("verbose", False)),
            session_state=session_state,
        )
        if result != 0:
            print("Task planning failed.")
        return "continue"

    print(f"Unknown command: /{command}. Use /help.")
    return "continue"


def _handle_task_input(
    *,
    engine: ContinuousEngine,
    task_description: str,
    mode: str,
    team_count: int | None,
    max_iterations: int | None,
    max_features: int | None,
    parallel_safe: bool,
    category: str,
    auto_run: bool,
    force_unsafe: bool,
    dry_run: bool,
    model: str | None,
    reasoning_effort: str | None,
    language: str = "en",
    verbose: bool = False,
    session_state: dict[str, object] | None = None,
) -> int:
    history_context = ""
    history_count = 0
    if session_state is not None:
        history_context = str(session_state.get("history_context", "") or "")
        records = session_state.get("history_records")
        if isinstance(records, dict):
            history_count = len(records)
    effective_task_description = _attach_history_context(
        task_description=task_description,
        history_context=history_context,
        language=language,
    )
    if history_count > 0:
        print(
            _styled(
                _lang_text(
                    language,
                    f"[history] attached synced file contexts: {history_count}",
                    f"[history] \u5df2\u9644\u52a0\u5386\u53f2\u4e0a\u4e0b\u6587\u6587\u4ef6\u6570: {history_count}",
                ),
                COLOR_DIM,
            )
        )
    task_id = _build_task_id(engine=engine, description=task_description)
    print(_styled(f"[plan] {task_id}", COLOR_GREEN))
    report = _run_with_live_activity(
        engine=engine,
        language=language,
        operation_label=_lang_text(language, "plan", "瑙勫垝"),
        run_fn=lambda: engine.plan_task(
            task_id=task_id,
            description=effective_task_description,
            max_features=max_features,
            category=category,
            parallel_safe=parallel_safe,
            dry_run=dry_run,
            model=model,
            reasoning_effort=reasoning_effort,
        ),
    )
    _print_plan_result(report=report, language=language, verbose=verbose)
    if not bool(report.get("success")):
        return 2
    if bool(report.get("used_fallback_plan")) and auto_run:
        if _is_placeholder_fallback_plan(report):
            print(
                _lang_text(
                    language,
                    "[run] skipped: fallback plan detected. Refine task or re-run planner, then execute /run manually.",
                    "[run] 已跳过：当前为回退模板计划。请先细化任务或重试规划，再手动执行 /run。",
                )
            )
            return 0
        print(
            _lang_text(
                language,
                "[run] note: fallback plan is executable; continuing auto-run.",
                "[run] 提示：回退计划包含可执行步骤，继续自动运行。",
            )
        )
    if not auto_run:
        return 0

    selected_max_iterations = _choose_iteration_count_for_task(
        language=language,
        default_max_iterations=max_iterations,
    )
    if session_state is not None:
        session_state["last_run_epochs"] = selected_max_iterations
    loop_report = _run_with_live_activity(
        engine=engine,
        language=language,
        operation_label=_lang_text(language, "run", "\u8fd0\u884c"),
        run_fn=lambda: engine.run_project_loop(
            mode=mode,
            max_iterations=selected_max_iterations,
            team_count=team_count,
            max_features=max_features,
            force_unsafe=force_unsafe,
            dry_run=dry_run,
        ),
    )
    _print_run_result(loop_report=loop_report, language=language, verbose=verbose)
    return 0 if loop_report.success else 2


def _run_project_from_state(
    *,
    engine: ContinuousEngine,
    session_state: dict[str, object],
    prompt_for_iterations: bool = True,
    forced_max_iterations: int | None = None,
) -> int:
    language = _session_language(session_state)
    verbose = bool(session_state.get("verbose", False))
    if prompt_for_iterations:
        selected_max_iterations = _choose_iteration_count_for_task(
            language=language,
            default_max_iterations=session_state["max_iterations"],  # type: ignore[arg-type]
        )
    else:
        if forced_max_iterations is not None:
            selected_max_iterations = max(1, forced_max_iterations)
        else:
            fallback = session_state.get("last_run_epochs")
            if isinstance(fallback, int) and fallback > 0:
                selected_max_iterations = fallback
            else:
                selected_max_iterations = session_state["max_iterations"]  # type: ignore[assignment]
                if not isinstance(selected_max_iterations, int) or selected_max_iterations <= 0:
                    selected_max_iterations = 3

    session_state["last_run_epochs"] = selected_max_iterations
    loop_report = _run_with_live_activity(
        engine=engine,
        language=language,
        operation_label=_lang_text(language, "run", "\u8fd0\u884c"),
        run_fn=lambda: engine.run_project_loop(
            mode=str(session_state["mode"]),
            max_iterations=selected_max_iterations,
            team_count=session_state["team_count"],  # type: ignore[arg-type]
            max_features=session_state["max_features"],  # type: ignore[arg-type]
            force_unsafe=bool(session_state.get("force_unsafe", False)),
            dry_run=bool(session_state["dry_run"]),
        ),
    )
    _print_run_result(loop_report=loop_report, language=language, verbose=verbose)
    return 0 if loop_report.success else 2


def _handle_history_command(
    *,
    engine: ContinuousEngine,
    session_state: dict[str, object],
    arg_text: str,
    language: str,
) -> None:
    token = arg_text.strip()
    records = session_state.get("history_records")
    if not isinstance(records, dict):
        records = {}
        session_state["history_records"] = records

    if not token or token.lower() in {"list", "ls", "show", "\u5217\u8868"}:
        if not records:
            print(
                _lang_text(
                    language,
                    "[history] no synced file history yet. Use /history <file_path>.",
                    "[history] \u6682\u65e0\u540c\u6b65\u7684\u6587\u4ef6\u5386\u53f2\uff0c\u8bf7\u4f7f\u7528 /history <\u6587\u4ef6\u8def\u5f84>\u3002",
                )
            )
            return
        print(_styled(_lang_text(language, "Synced History Files", "\u5df2\u540c\u6b65\u5386\u53f2\u6587\u4ef6"), COLOR_YELLOW))
        for path in records.keys():
            print(f"  - {path}")
        return

    lowered = token.lower()
    if lowered in {"clear", "reset", "clean", "\u6e05\u7a7a"}:
        session_state["history_records"] = {}
        session_state["history_context"] = ""
        print(_lang_text(language, "[history] cleared.", "[history] \u5df2\u6e05\u7a7a\u3002"))
        return

    resolved = _resolve_history_target(root=engine.root, raw_path=token)
    if resolved is None:
        print(
            _lang_text(
                language,
                f"[history] file not found: {token}",
                f"[history] \u6587\u4ef6\u4e0d\u5b58\u5728: {token}",
            )
        )
        return

    rel_path = resolved.relative_to(engine.root).as_posix()
    history_blob = _collect_file_history_context(root=engine.root, rel_path=rel_path, resolved_path=resolved)

    # Update insertion order: latest synced file appears later in context.
    if rel_path in records:
        records.pop(rel_path)
    records[rel_path] = history_blob
    session_state["history_records"] = records
    session_state["history_context"] = _build_history_context(records)

    preview = _trim_to_width(history_blob.replace("\n", " | "), width=_terminal_width())
    print(
        _lang_text(
            language,
            f"[history] synced: {rel_path}",
            f"[history] \u5df2\u540c\u6b65: {rel_path}",
        )
    )
    print(_styled(preview, COLOR_DIM))


def _resolve_history_target(*, root: Path, raw_path: str) -> Path | None:
    candidate = Path(raw_path.strip().strip('"').strip("'"))
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _collect_file_history_context(*, root: Path, rel_path: str, resolved_path: Path) -> str:
    sections: list[str] = [f"[file] {rel_path}"]

    commit_lines = _run_git_lines(
        root=root,
        args=[
            "log",
            "--follow",
            "--max-count=6",
            "--date=short",
            "--pretty=format:%h %ad %s",
            "--",
            rel_path,
        ],
        max_lines=8,
    )
    if commit_lines:
        sections.append("[recent_commits]")
        sections.extend(commit_lines)

    diff_lines = _run_git_lines(
        root=root,
        args=["diff", "--no-color", "--unified=1", "--", rel_path],
        max_lines=20,
    )
    if diff_lines:
        sections.append("[working_diff_excerpt]")
        sections.extend(diff_lines)

    file_lines = _tail_file_lines(path=resolved_path, max_lines=20)
    if file_lines:
        sections.append("[current_file_tail]")
        sections.extend(file_lines)

    if len(sections) == 1:
        sections.append("[note] no git history available; using file snapshot only.")
    blob = "\n".join(sections)
    if len(blob) > 6000:
        blob = blob[:5997] + "..."
    return blob


def _run_git_lines(*, root: Path, args: list[str], max_lines: int) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if completed.returncode != 0:
        return []
    lines = [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]
    return lines[: max(1, max_lines)]


def _tail_file_lines(*, path: Path, max_lines: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return []
            chunk_size = min(65536, size)
            handle.seek(-chunk_size, os.SEEK_END)
            raw = handle.read(chunk_size).decode("utf-8", errors="replace")
    except OSError:
        return []

    parts = raw.splitlines()
    if size > 65536 and parts:
        parts = parts[1:]
    lines = [line.rstrip() for line in parts if line.rstrip()]
    if not lines:
        return []
    return lines[-max(1, max_lines) :]


def _build_history_context(records: dict[str, object]) -> str:
    segments: list[str] = []
    for path, blob in records.items():
        text = str(blob).strip()
        if not text:
            continue
        segments.append(f"[history:{path}]\n{text}")
    combined = "\n\n".join(segments)
    if len(combined) > 9000:
        combined = combined[-9000:]
    return combined


def _attach_history_context(*, task_description: str, history_context: str, language: str) -> str:
    context = history_context.strip()
    if not context:
        return task_description
    marker = _lang_text(
        language,
        "Supplemental project history context (auto-synced):",
        "\u8865\u5145\u9879\u76ee\u5386\u53f2\u4e0a\u4e0b\u6587\uff08\u81ea\u52a8\u540c\u6b65\uff09:",
    )
    return f"{task_description}\n\n{marker}\n{context}"


def _print_plan_result(*, report: dict[str, object], language: str, verbose: bool) -> None:
    if verbose:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return
    if not bool(report.get("success")):
        message = str(report.get("message", "plan failed"))
        print(_lang_text(language, f"[plan] failed: {message}", f"[plan] failed: {message}"))
        failure_hint = _extract_plan_failure_hint(report)
        if failure_hint:
            print(_lang_text(language, f"[plan] detail: {failure_hint}", f"[plan] 详情: {failure_hint}"))
        return
    feature_ids = report.get("feature_ids", [])
    if isinstance(feature_ids, list):
        ids = [str(item) for item in feature_ids]
    else:
        ids = []
    preview = ", ".join(ids[:6])
    if len(ids) > 6:
        preview += ", ..."
    message = str(report.get("message", ""))
    summary = _lang_text(
        language,
        f"[plan] ok: {len(ids)} features",
        f"[plan] ok: {len(ids)} features",
    )
    if preview:
        summary += f" -> {preview}"
    if message:
        summary += f" | {message}"
    print(summary)
    failure_hint = _extract_plan_failure_hint(report)
    if bool(report.get("used_fallback_plan")) and failure_hint:
        print(_lang_text(language, f"[plan] note: fallback reason: {failure_hint}", f"[plan] 提示: 回退原因: {failure_hint}"))


def _extract_plan_failure_hint(report: dict[str, object]) -> str:
    command_results = report.get("command_results")
    if not isinstance(command_results, list) or not command_results:
        return ""
    first = command_results[0]
    if not isinstance(first, dict):
        return ""
    exit_code = int(first.get("exit_code", 0) or 0)
    text = str(first.get("stderr") or first.get("stdout") or "").strip()
    if exit_code == 0 or not text:
        return ""
    compact = " ".join(segment.strip() for segment in text.splitlines() if segment.strip())
    if len(compact) > 220:
        compact = compact[:217] + "..."
    return compact


def _is_placeholder_fallback_plan(report: dict[str, object]) -> bool:
    features = report.get("features")
    if not isinstance(features, list) or not features:
        return True

    for item in features:
        if not isinstance(item, dict):
            continue
        commands = item.get("implementation_commands")
        verify = item.get("verification_command")
        if isinstance(commands, list) and any(str(cmd).strip() for cmd in commands):
            return False
        if isinstance(verify, str) and verify.strip():
            return False
    return True


def _print_run_result(*, loop_report, language: str, verbose: bool) -> None:
    if verbose:
        print(_styled("[run]", COLOR_GREEN))
        print(json.dumps(loop_report.to_dict(), indent=2, ensure_ascii=True))
        return
    success = bool(getattr(loop_report, "success", False))
    iterations = int(getattr(loop_report, "iterations_executed", 0))
    stop_reason = str(getattr(loop_report, "stop_reason", ""))
    passed = int(getattr(loop_report, "final_passed_features", 0))
    total = int(getattr(loop_report, "total_features", 0))
    status = "ok" if success else "failed"
    print(
        _lang_text(
            language,
            f"[run] {status}: epochs={iterations} stop={stop_reason} passed={passed}/{total}",
            f"[run] {status}: \u8f6e\u6b21={iterations} stop={stop_reason} passed={passed}/{total}",
        )
    )


def _choose_iteration_count_for_task(*, language: str, default_max_iterations: int | None) -> int | None:
    if not sys.stdin.isatty():
        return default_max_iterations

    print(
        _styled(
            _lang_text(
                language,
                "Iteration mode: [1] Auto stop decision (Recommended)  [2] Manual max epochs",
                "\u8fed\u4ee3\u6a21\u5f0f: [1] \u81ea\u52a8\u5224\u5b9a\u505c\u6b62\uff08\u63a8\u8350\uff09  [2] \u624b\u52a8\u8f93\u5165\u6700\u5927\u8f6e\u6b21",
            ),
            COLOR_YELLOW,
        )
    )
    if default_max_iterations is not None:
        print(
            _lang_text(
                language,
                f"Current max_epochs={default_max_iterations}",
                f"\u5f53\u524d max_epochs={default_max_iterations}",
            )
        )

    while True:
        choice = input(
            _lang_text(
                language,
                "Choose [1/2] (Enter=1): ",
                "\u8bf7\u9009\u62e9 [1/2]\uff08\u56de\u8f66=1\uff09: ",
            )
        ).strip()
        mode = _parse_iteration_mode_choice(choice)
        if mode == "auto":
            return default_max_iterations
        if mode == "manual":
            return _prompt_manual_iteration_count(
                language=language,
                default_max_iterations=default_max_iterations,
            )
        print(
            _lang_text(
                language,
                "Invalid choice. Please enter 1 or 2.",
                "\u9009\u62e9\u65e0\u6548\uff0c\u8bf7\u8f93\u5165 1 \u6216 2\u3002",
            )
        )


def _parse_iteration_mode_choice(value: str) -> str | None:
    token = value.strip()
    if not token:
        return "auto"
    lowered = token.lower()
    if lowered in {"1", "auto", "a"}:
        return "auto"
    if lowered in {"2", "manual", "m"}:
        return "manual"
    if token in {"\u81ea\u52a8", "\u81ea\u52d5"}:
        return "auto"
    if token in {"\u624b\u52a8", "\u624b\u52d5"}:
        return "manual"
    return None


def _prompt_manual_iteration_count(*, language: str, default_max_iterations: int | None) -> int:
    while True:
        if default_max_iterations is not None:
            prompt = _lang_text(
                language,
                f"Enter max epochs (positive integer, Enter={default_max_iterations}): ",
                f"\u8f93\u5165\u6700\u5927\u8f6e\u6b21\uff08\u6b63\u6574\u6570\uff0c\u56de\u8f66={default_max_iterations}\uff09: ",
            )
        else:
            prompt = _lang_text(
                language,
                "Enter max epochs (positive integer): ",
                "\u8f93\u5165\u6700\u5927\u8f6e\u6b21\uff08\u6b63\u6574\u6570\uff09: ",
            )
        raw = input(prompt).strip()
        if not raw and default_max_iterations is not None:
            return default_max_iterations
        manual = _parse_manual_iteration_count(raw)
        if manual is not None:
            return manual
        print(
            _lang_text(
                language,
                "Invalid number. Please enter a positive integer.",
                "\u6570\u5b57\u65e0\u6548\uff0c\u8bf7\u8f93\u5165\u6b63\u6574\u6570\u3002",
            )
        )


def _parse_manual_iteration_count(value: str) -> int | None:
    token = value.strip()
    if not token:
        return None
    try:
        parsed = int(token)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _run_with_live_activity(
    *,
    engine: ContinuousEngine,
    language: str,
    operation_label: str,
    run_fn: Callable[[], T],
) -> T:
    if not sys.stdout.isatty():
        return run_fn()
    use_block_render = _supports_cursor_rewrite()
    stop_event = Event()
    render_state: dict[str, int] = {"line_count": 0}
    monitor = Thread(
        target=_live_activity_loop,
        kwargs={
            "engine": engine,
            "stop_event": stop_event,
            "language": language,
            "operation_label": operation_label,
            "render_state": render_state,
            "use_block_render": use_block_render,
        },
        daemon=True,
    )
    monitor.start()
    try:
        return run_fn()
    finally:
        stop_event.set()
        monitor.join(timeout=1.5)
        if use_block_render:
            _clear_live_activity_block(render_state.get("line_count", 0))
        else:
            _clear_live_activity_line()


def _live_activity_loop(
    *,
    engine: ContinuousEngine,
    stop_event: Event,
    language: str,
    operation_label: str,
    render_state: dict[str, int],
    use_block_render: bool,
) -> None:
    frame_index = 0
    started_at = time()
    last_rendered_lines = 0
    last_visible_length = 0
    try:
        while not stop_event.is_set():
            spinner = SPINNER_FRAMES[frame_index % len(SPINNER_FRAMES)]
            workers = engine.get_active_workers()
            elapsed_seconds = max(0, int(time() - started_at))
            if use_block_render:
                lines = _render_live_activity_panel(
                    engine=engine,
                    workers=workers,
                    language=language,
                    operation_label=operation_label,
                    spinner=spinner,
                    elapsed_seconds=elapsed_seconds,
                )
                last_rendered_lines = _paint_live_activity_block(lines=lines, previous_line_count=last_rendered_lines)
                render_state["line_count"] = last_rendered_lines
            else:
                line = _render_compact_live_activity_line(
                    workers=workers,
                    language=language,
                    operation_label=operation_label,
                    spinner=spinner,
                    elapsed_seconds=elapsed_seconds,
                )
                last_visible_length = _paint_compact_live_activity_line(
                    line=line,
                    previous_visible_length=last_visible_length,
                )
            frame_index += 1
            sleep(0.35)
    finally:
        if use_block_render:
            _clear_live_activity_block(last_rendered_lines)
            render_state["line_count"] = 0
        else:
            _clear_live_activity_line()


def _render_live_activity_panel(
    *,
    engine: ContinuousEngine,
    workers: list[dict[str, object]],
    language: str,
    operation_label: str,
    spinner: str,
    elapsed_seconds: int,
) -> list[str]:
    elapsed_text = _format_elapsed_short(seconds=elapsed_seconds)
    title = _lang_text(
        language,
        f"[{operation_label}] {spinner} running  elapsed={elapsed_text}  workers={len(workers)}",
        f"[{operation_label}] {spinner} \u8fd0\u884c\u4e2d  \u8017\u65f6={elapsed_text}  \u6267\u884c\u8005={len(workers)}",
    )

    if not workers:
        waiting = _lang_text(
            language,
            "models: waiting for AI workers...",
            "\u6a21\u578b: \u7b49\u5f85 AI \u6267\u884c\u8005...",
        )
        placeholder = _lang_text(
            language,
            "live: no active feature yet.",
            "\u5b9e\u65f6: \u6682\u65e0\u6d3b\u8dc3\u529f\u80fd\u3002",
        )
        return [title, waiting, placeholder, placeholder, placeholder]

    models: dict[str, int] = {}
    worker_chunks: list[str] = []
    policy_model = str(engine.get_policy().codex_model)
    for worker in workers:
        ai_id = str(worker.get("ai_id", "AI-??")).strip()
        role = str(worker.get("role", "Worker"))
        role_id = str(worker.get("role_id", "AI-??"))
        team_id = str(worker.get("team_id", ""))
        feature_id = str(worker.get("feature_id", ""))
        task_id = str(worker.get("task_id", ""))
        model = str(worker.get("model", ""))
        identity = f"{role_id} {role}" if not team_id else f"{role_id} {role}#{team_id}"
        subject = feature_id or task_id or "-"
        resolved_model = model or policy_model
        models[resolved_model] = models.get(resolved_model, 0) + 1
        worker_chunks.append(f"{ai_id} {identity} {subject} @{resolved_model}")

    model_line = "models: " + ", ".join(f"{name} x{count}" for name, count in sorted(models.items()))
    workers_line = "workers: " + " | ".join(worker_chunks)

    feature_map = {item.id: item for item in engine.list_features()}
    status = engine.get_status()
    progress_tail = _tail_file_lines(path=engine.root / "progress.log", max_lines=12)
    live_lines = _build_live_preview_lines(
        workers=workers,
        feature_map=feature_map,
        last_command_summary=status.last_command_summary,
        progress_tail=progress_tail,
        language=language,
    )
    return [title, model_line, workers_line, *live_lines]


def _build_live_preview_lines(
    *,
    workers: list[dict[str, object]],
    feature_map: dict[str, Feature],
    last_command_summary: list[str],
    progress_tail: list[str],
    language: str,
) -> list[str]:
    lines: list[str] = []

    primary_feature_id = ""
    for worker in workers:
        fid = str(worker.get("feature_id", "")).strip()
        if fid:
            primary_feature_id = fid
            break

    if primary_feature_id:
        feature = feature_map.get(primary_feature_id)
        if feature is not None:
            lines.append(f"live: {feature.id} | {feature.description}")
            for command in feature.implementation_commands[:2]:
                lines.append(f"live: cmd> {command}")
            if len(lines) < 3 and feature.verification_command:
                lines.append(f"live: verify> {feature.verification_command}")

    if len(lines) < 3:
        for summary in reversed(last_command_summary):
            compact = summary.strip()
            if not compact:
                continue
            lines.append(f"live: last> {compact}")
            if len(lines) >= 3:
                break

    if len(lines) < 3:
        for item in reversed(progress_tail):
            compact = item.strip()
            if not compact:
                continue
            lines.append(f"live: log> {compact}")
            if len(lines) >= 3:
                break

    if len(lines) < 3:
        filler = _lang_text(
            language,
            "live: gathering runtime details...",
            "\u5b9e\u65f6: \u6b63\u5728\u91c7\u96c6\u6267\u884c\u7ec6\u8282...",
        )
        while len(lines) < 3:
            lines.append(filler)

    return lines[:3]


def _render_compact_live_activity_line(
    *,
    workers: list[dict[str, object]],
    language: str,
    operation_label: str,
    spinner: str,
    elapsed_seconds: int,
) -> str:
    elapsed_text = _format_elapsed_short(seconds=elapsed_seconds)
    if not workers:
        return _lang_text(
            language,
            f"[{operation_label}] {spinner} running  elapsed={elapsed_text}  workers=0",
            f"[{operation_label}] {spinner} \u8fd0\u884c\u4e2d  \u8017\u65f6={elapsed_text}  \u6267\u884c\u8005=0",
        )
    return _lang_text(
        language,
        f"[{operation_label}] {spinner} running  elapsed={elapsed_text}  workers={len(workers)}",
        f"[{operation_label}] {spinner} \u8fd0\u884c\u4e2d  \u8017\u65f6={elapsed_text}  \u6267\u884c\u8005={len(workers)}",
    )


def _paint_compact_live_activity_line(*, line: str, previous_visible_length: int) -> int:
    width = _terminal_width()
    visible = _trim_to_width(line, width=width)
    padded = visible + (" " * max(0, previous_visible_length - len(visible)))
    print("\r" + _styled(padded, COLOR_DIM), end="", flush=True)
    return len(visible)


def _paint_live_activity_block(*, lines: list[str], previous_line_count: int) -> int:
    if not sys.stdout.isatty():
        return 0
    width = _terminal_width()
    if previous_line_count > 0:
        print(f"\033[{previous_line_count}F", end="")
    for line in lines:
        trimmed = _trim_to_width(line, width=width)
        print("\r\033[2K" + _styled(trimmed, COLOR_DIM))
    return len(lines)


def _clear_live_activity_block(line_count: int) -> None:
    if not sys.stdout.isatty() or line_count <= 0:
        return
    print(f"\033[{line_count}F", end="")
    for _ in range(line_count):
        print("\r\033[2K")
    print(f"\033[{line_count}F", end="", flush=True)


def _clear_live_activity_line() -> None:
    if not sys.stdout.isatty():
        return
    width = _terminal_width()
    print("\r" + (" " * max(1, width - 1)) + "\r", end="", flush=True)


def _format_elapsed_short(*, seconds: int) -> str:
    total = max(0, int(seconds))
    minutes, remaining = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"


def _trim_to_width(text: str, *, width: int) -> str:
    if width <= 0:
        return text
    if len(text) <= width - 1:
        return text
    if width <= 4:
        return text[:width]
    return text[: width - 4] + "..."


def _clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def _render_builder_header(*, engine: ContinuousEngine, session_state: dict[str, object]) -> None:
    policy = engine.get_policy()
    language = _session_language(session_state)
    active_model = str(session_state["model"] or policy.codex_model)
    active_reasoning = str(session_state["reasoning_effort"] or policy.codex_reasoning_effort)
    width = _terminal_width()
    inner = max(20, width - 4)
    border = "+" + "-" * (width - 2) + "+"
    banner = [
        "   ____          _      _   _      _           ",
        "  / ___|___   __| | ___| | | | ___| |_ __ ___  ",
        " | |   / _ \\ / _` |/ _ \\ |_| |/ _ \\ | '_ ` _ \\ ",
        " | |__| (_) | (_| |  __/  _  |  __/ | | | | | |",
        "  \\____\\___/ \\__,_|\\___|_| |_|\\___|_|_| |_| |_|",
    ]
    lines = [
        f"app={APP_NAME}",
        f"root={engine.root}",
        f"mode={session_state['mode']} parallel_safe={'on' if session_state['parallel_safe'] else 'off'} "
        f"unsafe={'on' if bool(session_state.get('force_unsafe', False)) else 'off'} "
        f"auto_run={'on' if session_state['auto_run'] else 'off'} "
        f"teams={session_state['team_count'] or '-'} max_features={session_state['max_features'] or '-'}",
        f"backend={policy.implementation_backend} model={active_model} reasoning={active_reasoning}",
        f"planner_sandbox={policy.planner_sandbox_mode} lang={language} "
        f"planner_shell_tool={'off' if policy.planner_disable_shell_tool else 'on'}",
    ]

    print(_styled(border, COLOR_CYAN))
    for item in banner:
        padded = item[:inner].center(inner)
        print(_styled(f"| {padded} |", COLOR_CYAN))
    print(_styled("| " + "".center(inner, "-") + " |", COLOR_CYAN))
    for item in lines:
        print(_styled(f"| {item[:inner].ljust(inner)} |", COLOR_CYAN))
    print(_styled(border, COLOR_CYAN))
    print(
        _styled(
            _lang_text(
                language,
                "Slash commands: /help /model /language /agents /history /unsafe /run /continue /plan /status /features /policy /clear /quit",
                "\u659c\u6760\u547d\u4ee4: /help /\u6a21\u578b /\u8bed\u8a00 /\u8fdb\u7a0b /\u5386\u53f2 /\u653e\u5bbd /\u8fd0\u884c /\u7ee7\u7eed /\u8ba1\u5212 /\u72b6\u6001 /\u4efb\u52a1 /\u7b56\u7565 /\u6e05\u5c4f /\u9000\u51fa",
            ),
            COLOR_DIM,
        )
    )
    print(
        _styled(
            _lang_text(
                language,
                "Tip: type task text directly to plan + run, e.g. 'build login and dashboard'.",
                "\u63d0\u793a: \u76f4\u63a5\u8f93\u5165\u4efb\u52a1\u6587\u672c\u5373\u53ef\u81ea\u52a8\u89c4\u5212\u5e76\u8fd0\u884c\uff0c\u4f8b\u5982\u201c\u5b8c\u6210\u767b\u5f55\u548c\u4eea\u8868\u76d8\u201d\u3002",
            ),
            COLOR_DIM,
        )
    )
    print()


def _print_help_panel(*, language: str = "en") -> None:
    if language == "zh":
        entries = [
            "/language                      \u5207\u6362\u754c\u9762\u8bed\u8a00\uff08\u4e2d/\u82f1\uff09",
            "/\u6a21\u578b                           \u6253\u5f00\u6a21\u578b\u9009\u62e9\u83dc\u5355",
            "/model <id> [reasoning]        \u76f4\u63a5\u5207\u6362\u6a21\u578b",
            "/\u8fdb\u7a0b [limit]                  \u67e5\u770b AI \u76f8\u5173\u8fdb\u7a0b",
            "/\u8fdb\u7a0b all [limit]              \u67e5\u770b\u5168\u90e8\u8fdb\u7a0b",
            "/ps                            /\u8fdb\u7a0b \u7684\u522b\u540d",
            "/\u5386\u53f2 <\u6587\u4ef6>                    \u540c\u6b65\u8be5\u6587\u4ef6\u7684 git \u5386\u53f2\u5230\u4efb\u52a1\u4e0a\u4e0b\u6587",
            "/\u5386\u53f2 list|clear               \u67e5\u770b/\u6e05\u7a7a\u5df2\u540c\u6b65\u5386\u53f2\u6587\u4ef6",
            "/\u8fd0\u884c                           \u6309\u5f53\u524d\u914d\u7f6e\u8fd0\u884c\u9879\u76ee\u5faa\u73af",
            "/\u7ee7\u7eed [n]                     \u65e0\u4ea4\u4e92\u76f4\u63a5\u7eed\u8dd1 n \u8f6e\uff08\u9ed8\u8ba4\u4e0a\u6b21\u8f6e\u6b21\uff09",
            "/\u8ba1\u5212 <\u4efb\u52a1\u6587\u672c>               \u4ec5\u89c4\u5212\uff08\u4e0d\u81ea\u52a8\u8fd0\u884c\uff09",
            "/\u6a21\u5f0f single|parallel          \u5207\u6362\u6267\u884c\u6a21\u5f0f\uff08\u6216 \u5355\u4eba|\u5e76\u884c\uff09",
            "/\u81ea\u52a8 on|off                   \u5f00\u5173\u81ea\u52a8\u8fd0\u884c\uff08\u6216 \u5f00|\u5173\uff09",
            "/\u653e\u5bbd on|off                  \u5f00\u5173 parallel_safe \u95e8\u7981\uff08/unsafe\uff09",
            "/verbose on|off                \u5207\u6362\u7b80\u7565/\u8be6\u7ec6\u8f93\u51fa",
            "/\u540e\u7aef codex|shell|auto         \u5207\u6362\u6267\u884c\u540e\u7aef",
            "/\u72b6\u6001 /\u4efb\u52a1 /\u7b56\u7565              \u72b6\u6001\u3001\u529f\u80fd\u6e05\u5355\u3001\u7b56\u7565",
            "/\u6e05\u5c4f /\u9000\u51fa",
        ]
    else:
        entries = [
            "/language                      switch UI language (en/zh)",
            "/model                         open model selection menu",
            "/model <id> [reasoning]        quick-switch model",
            "/agents [limit]                list AI-related processes",
            "/agents all [limit]            list all processes",
            "/ps                            alias of /agents",
            "/history <file>                sync this file's git history into task context",
            "/history list|clear            list/clear synced history files",
            "/run                           run project loop with current session settings",
            "/continue [n]                  continue run for n epochs (no extra prompts)",
            "/plan <task text>              plan only (no auto-run)",
            "/mode single|parallel          switch run mode",
            "/auto on|off                   toggle auto run after planning",
            "/unsafe on|off                 toggle parallel_safe gate bypass",
            "/verbose on|off                toggle compact/full report",
            "/backend codex|shell|auto",
            "/status /features(/tasks) /policy(/config)",
            "/clear /quit",
        ]
    print(_styled(_lang_text(language, "Commands", "\u547d\u4ee4\u5217\u8868"), COLOR_YELLOW))
    for item in entries:
        print(f"  {item}")


def _interactive_model_picker(
    *,
    engine: ContinuousEngine,
    session_state: dict[str, object],
    language: str = "en",
) -> None:
    policy = engine.get_policy()
    current_model = str(session_state["model"] or policy.codex_model)
    model_choices = [current_model] + [item for item in MODEL_PRESETS if item != current_model]
    print(_styled(_lang_text(language, "Model Picker", "\u6a21\u578b\u9009\u62e9"), COLOR_YELLOW))
    for idx, item in enumerate(model_choices, start=1):
        marker = "*" if item == current_model else " "
        print(f"  {idx}. [{marker}] {item}")
    print(_lang_text(language, "  c. custom model", "  c. \u81ea\u5b9a\u4e49\u6a21\u578b"))
    choice = input(_lang_text(language, "Select model (Enter to cancel): ", "\u9009\u62e9\u6a21\u578b\uff08\u56de\u8f66\u53d6\u6d88\uff09: ")).strip().lower()
    if not choice:
        return
    if choice == "c":
        selected_model = input(_lang_text(language, "Custom model id: ", "\u8f93\u5165\u81ea\u5b9a\u4e49\u6a21\u578b ID: ")).strip()
        if not selected_model:
            print(_lang_text(language, "Cancelled.", "\u5df2\u53d6\u6d88\u3002"))
            return
    elif choice.isdigit() and 1 <= int(choice) <= len(model_choices):
        selected_model = model_choices[int(choice) - 1]
    else:
        print(_lang_text(language, "Invalid selection.", "\u65e0\u6548\u9009\u62e9\u3002"))
        return

    current_reasoning = str(session_state["reasoning_effort"] or policy.codex_reasoning_effort)
    selected_reasoning = _interactive_reasoning_picker(current_reasoning=current_reasoning, language=language)
    updated = engine.set_model_settings(model=selected_model, reasoning_effort=selected_reasoning)
    session_state["model"] = updated.codex_model
    session_state["reasoning_effort"] = updated.codex_reasoning_effort
    print(f"model={updated.codex_model} reasoning={updated.codex_reasoning_effort}")


def _interactive_reasoning_picker(*, current_reasoning: str, language: str = "en") -> str:
    choices = [current_reasoning] + [item for item in REASONING_PRESETS if item != current_reasoning]
    print(_lang_text(language, "Reasoning Effort:", "\u63a8\u7406\u5f3a\u5ea6:"))
    for idx, item in enumerate(choices, start=1):
        marker = "*" if item == current_reasoning else " "
        print(f"  {idx}. [{marker}] {item}")
    choice = input(_lang_text(language, "Select reasoning (Enter to keep): ", "\u9009\u62e9\u63a8\u7406\u5f3a\u5ea6\uff08\u56de\u8f66\u4fdd\u6301\uff09: ")).strip()
    if not choice:
        return current_reasoning
    if choice.isdigit() and 1 <= int(choice) <= len(choices):
        return choices[int(choice) - 1]
    print(_lang_text(language, "Invalid selection. Keeping current.", "\u65e0\u6548\u9009\u62e9\uff0c\u4fdd\u6301\u5f53\u524d\u8bbe\u7f6e\u3002"))
    return current_reasoning


def _interactive_language_picker(*, engine: ContinuousEngine, session_state: dict[str, object]) -> None:
    language = _session_language(session_state)
    current_language = _session_language(session_state)
    print(_styled(_lang_text(language, "Language Picker", "\u8bed\u8a00\u9009\u62e9"), COLOR_YELLOW))
    for idx, item in enumerate(LANGUAGE_PRESETS, start=1):
        marker = "*" if item == current_language else " "
        print(f"  {idx}. [{marker}] {item} ({LANGUAGE_LABELS[item]})")
    choice = input(_lang_text(language, "Select language (Enter to cancel): ", "\u9009\u62e9\u8bed\u8a00\uff08\u56de\u8f66\u53d6\u6d88\uff09: ")).strip()
    if not choice:
        return
    if choice.isdigit() and 1 <= int(choice) <= len(LANGUAGE_PRESETS):
        selected = LANGUAGE_PRESETS[int(choice) - 1]
    else:
        selected = _normalize_language(choice)
        if not selected:
            print(_lang_text(language, "Invalid selection.", "\u65e0\u6548\u9009\u62e9\u3002"))
            return
    _apply_language(engine=engine, session_state=session_state, value=selected)


def _apply_language(*, engine: ContinuousEngine, session_state: dict[str, object], value: str) -> bool:
    normalized = _normalize_language(value)
    if not normalized:
        return False
    updated = engine.set_model_settings(ui_language=normalized)
    session_state["language"] = updated.ui_language
    print(
        _lang_text(
            updated.ui_language,
            f"language={updated.ui_language} ({LANGUAGE_LABELS[updated.ui_language]})",
            f"\u8bed\u8a00={updated.ui_language} ({LANGUAGE_LABELS[updated.ui_language]})",
        )
    )
    return True


def _apply_model_from_text(
    *,
    engine: ContinuousEngine,
    session_state: dict[str, object],
    arg_text: str,
    language: str = "en",
) -> bool:
    tokens = [item.strip() for item in arg_text.split() if item.strip()]
    if not tokens:
        return False
    if len(tokens) > 2:
        return False
    model = tokens[0]
    policy = engine.get_policy()
    current_reasoning = str(session_state["reasoning_effort"] or policy.codex_reasoning_effort)
    reasoning = current_reasoning
    if len(tokens) >= 2:
        candidate = tokens[1].lower()
        if candidate not in REASONING_PRESETS:
            return False
        reasoning = candidate
    updated = engine.set_model_settings(model=model, reasoning_effort=reasoning)
    session_state["model"] = updated.codex_model
    session_state["reasoning_effort"] = updated.codex_reasoning_effort
    print(
        _lang_text(
            language,
            f"model={updated.codex_model} reasoning={updated.codex_reasoning_effort}",
            f"\u6a21\u578b={updated.codex_model} \u63a8\u7406={updated.codex_reasoning_effort}",
        )
    )
    return True


def _list_ai_processes(*, limit: int = 30, include_all: bool = False) -> dict[str, object]:
    keywords = [
        "codex",
        "caasys",
        "builder",
        "codehelm",
        "openai",
        "anthropic",
        "claude",
        "gpt",
        "ollama",
        "lmstudio",
    ]
    try:
        if os.name == "nt":
            processes, source = _list_processes_windows()
        else:
            processes, source = _list_processes_posix()
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {
            "ok": False,
            "source": "none",
            "count": 0,
            "processes": [],
            "error": str(exc),
        }

    selected = []
    for item in processes:
        haystack = f"{item['name']} {item.get('command', '')}".lower()
        if any(keyword in haystack for keyword in keywords):
            selected.append(item)

    visible = processes if include_all else selected
    visible.sort(key=lambda item: (str(item.get("name", "")).lower(), int(item.get("pid", 0))))
    visible = visible[: max(1, limit)]
    return {
        "ok": True,
        "source": source,
        "count": len(visible),
        "scope": "all" if include_all else "ai",
        "matched_ai": len(selected),
        "scanned_total": len(processes),
        "processes": visible,
        "error": "",
    }


def _list_processes_windows() -> tuple[list[dict[str, object]], str]:
    cim = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if cim.returncode == 0 and cim.stdout.strip():
        payload = json.loads(cim.stdout)
        if isinstance(payload, dict):
            payload = [payload]
        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "pid": int(item.get("ProcessId") or 0),
                    "name": str(item.get("Name") or ""),
                    "command": str(item.get("CommandLine") or ""),
                }
            )
        return items, "powershell-cim"

    tasklist = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if tasklist.returncode != 0:
        raise RuntimeError(cim.stderr.strip() or tasklist.stderr.strip() or "process scan failed")
    items = []
    for raw in tasklist.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('"') and line.endswith('"'):
            parts = [part.strip().strip('"') for part in line.split('","')]
        else:
            parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        pid = int(re.sub(r"[^\d]", "", parts[1]) or "0")
        items.append({"pid": pid, "name": parts[0], "command": ""})
    return items, "tasklist"


def _list_processes_posix() -> tuple[list[dict[str, object]], str]:
    ps = subprocess.run(
        ["ps", "-ax", "-o", "pid=", "-o", "comm=", "-o", "args="],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if ps.returncode != 0:
        raise RuntimeError(ps.stderr.strip() or "ps command failed")
    items = []
    for raw in ps.stdout.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 2)
        if len(parts) < 2:
            continue
        args_text = parts[2] if len(parts) > 2 else parts[1]
        items.append({"pid": int(parts[0]), "name": parts[1], "command": args_text})
    return items, "ps"


def _print_agents_report(report: dict[str, object], *, language: str = "en") -> None:
    if not bool(report.get("ok")):
        print(
            _lang_text(
                language,
                f"Process scan failed: {report.get('error', 'unknown error')}",
                f"\u8fdb\u7a0b\u626b\u63cf\u5931\u8d25: {report.get('error', 'unknown error')}",
            )
        )
        return
    processes = report.get("processes", [])
    if not isinstance(processes, list) or not processes:
        print(_lang_text(language, "No AI-related processes found.", "\u672a\u53d1\u73b0 AI \u76f8\u5173\u8fdb\u7a0b\u3002"))
        return
    scope = str(report.get("scope", "ai"))
    source = str(report.get("source", "unknown"))
    scanned_total = int(report.get("scanned_total", 0))
    matched_ai = int(report.get("matched_ai", 0))
    if scope == "all":
        print(
            _styled(
                _lang_text(
                    language,
                    f"Processes ({source}) total={scanned_total} ai_like={matched_ai}",
                    f"\u8fdb\u7a0b\u5217\u8868 ({source}) \u603b\u6570={scanned_total} AI\u76f8\u5173={matched_ai}",
                ),
                COLOR_YELLOW,
            )
        )
    else:
        print(
            _styled(
                _lang_text(
                    language,
                    f"AI Processes ({source}) matched={matched_ai}",
                    f"AI \u8fdb\u7a0b ({source}) \u5339\u914d={matched_ai}",
                ),
                COLOR_YELLOW,
            )
        )
    print(f"{'PID':>7}  {'NAME':<24} {_lang_text(language, 'COMMAND', '\u547d\u4ee4\u884c')}")
    print("-" * 96)
    for item in processes:
        if not isinstance(item, dict):
            continue
        pid = int(item.get("pid", 0))
        name = str(item.get("name", ""))[:24]
        command = str(item.get("command", ""))[:60]
        print(f"{pid:>7}  {name:<24} {command}")


def _lang_text(language: str, en_text: str, zh_text: str) -> str:
    return zh_text if language == "zh" else en_text


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    lowered = token.lower()
    if lowered in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lowered]
    if token in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[token]
    return None


def _session_language(session_state: dict[str, object]) -> str:
    normalized = _normalize_language(str(session_state.get("language", "en")))
    return normalized or "en"


def _normalize_slash_command(command: str) -> str:
    token = command.strip().lower()
    return SLASH_COMMAND_ALIASES.get(token, token)


def _normalize_backend_value(value: str) -> str:
    token = value.strip().lower()
    if token in {"\u81ea\u52a8"}:
        return "auto"
    return token


def _normalize_auto_value(value: str) -> str:
    token = value.strip().lower()
    if token in {"\u5f00", "\u5f00\u542f", "\u662f"}:
        return "on"
    if token in {"\u5173", "\u5173\u95ed", "\u5426"}:
        return "off"
    return token


def _normalize_mode_value(value: str) -> str:
    token = value.strip().lower()
    if token in {"\u5355\u4eba", "\u5355\u7ebf\u7a0b"}:
        return "single"
    if token in {"\u5e76\u884c", "\u591a\u4eba"}:
        return "parallel"
    return token


def _parse_positive_int(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _parse_agents_args(*, arg_text: str, default_limit: int) -> tuple[bool, int]:
    include_all = False
    limit = default_limit
    if not arg_text:
        return include_all, limit
    tokens = [item.strip().lower() for item in arg_text.split() if item.strip()]
    for token in tokens:
        if token in {"all", "--all", "-a", "\u5168\u90e8", "\u6240\u6709"}:
            include_all = True
            continue
        if token in {"ai", "--ai", "\u667a\u80fd\u4f53", "\u6a21\u578b"}:
            include_all = False
            continue
        limit = _parse_positive_int(token, default=limit)
    return include_all, limit


def _recommended_parallel_teams(default_value: int) -> int:
    cpu = os.cpu_count() or default_value or 2
    suggested = min(12, max(2, cpu))
    return max(1, max(default_value, suggested))


def _terminal_width() -> int:
    if not sys.stdout.isatty():
        return 88
    try:
        columns = shutil.get_terminal_size((88, 24)).columns
    except OSError:
        columns = 88
    return max(76, min(110, columns))


def _supports_cursor_rewrite() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    return _enable_windows_virtual_terminal_mode()


def _enable_windows_virtual_terminal_mode() -> bool:
    try:
        import ctypes
    except Exception:
        return False

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    if handle in (0, -1):
        return False

    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return False
    enabled = int(mode.value) | 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    if kernel32.SetConsoleMode(handle, enabled) == 0:
        return False
    return True


def _styled(text: str, style: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{style}{text}{COLOR_RESET}"


def _build_task_id(*, engine: ContinuousEngine, description: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "-", description.strip().upper())
    prefix = prefix.strip("-")
    prefix = prefix[:20] if prefix else "TASK"
    existing = {item.id for item in engine.list_features()}
    stamp = str(int(time()))[-6:]
    base = f"T-{prefix}-{stamp}"
    candidate = base
    index = 1
    while candidate in existing:
        index += 1
        candidate = f"{base}-{index}"
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())

