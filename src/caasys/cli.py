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

    add_parser = subparsers.add_parser("add-feature", help="Add one feature to feature_list.json")
    add_parser.add_argument("--id", required=True, dest="feature_id")
    add_parser.add_argument("--category", default="functional")
    add_parser.add_argument("--description", required=True)
    add_parser.add_argument("--priority", type=int, default=100)
    add_parser.add_argument("--impl", action="append", default=[], help="Implementation command (repeatable)")
    add_parser.add_argument("--verify", default=None, help="Verification command")

    subparsers.add_parser("status", help="Print AGENT_STATUS.md")
    subparsers.add_parser("features", help="Print feature list JSON")

    iterate_parser = subparsers.add_parser("iterate", help="Run one iteration")
    iterate_parser.add_argument("--commit", action="store_true", help="Attempt git commit after iteration")
    iterate_parser.add_argument("--dry-run", action="store_true", help="Skip actual command execution")

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
        status = engine.initialize(objective=args.objective)
        print(f"Initialized objective: {status.current_objective}")
        return 0

    if args.command == "add-feature":
        feature = Feature(
            id=args.feature_id,
            category=args.category,
            description=args.description,
            priority=args.priority,
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

    if args.command == "iterate":
        report = engine.run_iteration(commit=args.commit, dry_run=args.dry_run)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "serve":
        from .server import run_server

        run_server(root=root, host=args.host, port=args.port)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
