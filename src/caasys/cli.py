"""Command-line interface for the system."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import ContinuousEngine
from .models import Feature


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caasys", description="Continuous autonomous engineering system")
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
    run_project_parser.add_argument("--max-iterations", type=int, default=None)
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

    if args.command == "status":
        path = root / "AGENT_STATUS.md"
        if not path.exists():
            print("AGENT_STATUS.md not found. Run `caasys init` first.")
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
        report = engine.run_iteration(commit=args.commit, dry_run=args.dry_run)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "iterate-parallel":
        report = engine.run_parallel_iteration(
            team_count=args.teams,
            max_features=args.max_features,
            commit=args.commit,
            dry_run=args.dry_run,
            force_unsafe=args.force_unsafe,
        )
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0 if report.success else 2

    if args.command == "run-project":
        report = engine.run_project_loop(
            mode=args.mode,
            max_iterations=args.max_iterations,
            team_count=args.teams,
            max_features=args.max_features,
            force_unsafe=args.force_unsafe,
            commit=args.commit,
            dry_run=args.dry_run,
            browser_validate_on_stop=args.browser_validate_on_stop,
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


if __name__ == "__main__":
    raise SystemExit(main())
