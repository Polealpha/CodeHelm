# Continuous Autonomous Engineering System

This project implements a local, runnable system for long-running autonomous software development loops inspired by:

- `lunwen` (Effective harnesses for long-running agents, 2025-11-26)
- `2508.03923v2.pdf` (CoAct-1: Computer-using Agents with Coding as Actions)

The system follows a strict cycle:

`PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> COMMIT -> NEXT`

Default runtime mode is `Zero-Ask`: agents do not pause for human questions and instead apply a fallback chain.

## Architecture Sketch

- `Orchestrator` (`src/caasys/orchestrator.py`): selects the highest-priority pending feature and generates a per-iteration plan.
- `ProgrammerAgent` (`src/caasys/agents.py`): executes implementation commands for the selected feature.
- `OperatorAgent` (`src/caasys/agents.py`): executes verification commands and returns operational results.
- `ContinuousEngine` (`src/caasys/engine.py`): coordinates one full iteration and updates durable memory artifacts.
- `Parallel Team Runner` (`src/caasys/engine.py`): dispatches multiple pending features to concurrent teams while each team still uses role-based execution.
- `Storage Layer` (`src/caasys/storage.py`): persists `AGENT_STATUS.md`, `feature_list.json`, `.caasys/state.json`, and `progress.log`.
- `Interfaces`:
  - CLI (`src/caasys/cli.py`)
  - Local HTTP API (`src/caasys/server.py`)
- `Policy + Hygiene`:
  - shared policy (`AGENT_POLICY.md`, `.caasys/policy.json`)
  - quality gate (`caasys quality-gate`) to prevent context rot

## Milestones

1. Bootstrap durable artifacts and package layout.
2. Implement orchestrator + dual-agent execution core.
3. Expose CLI and local deployment API.
4. Add smoke tests and verify iteration behavior.
5. Finalize docs and reproducible startup workflow.

## MVP Definition

Minimum viable completion requires:

- local initialization (`init`);
- feature backlog management (`add-feature`, `features`);
- one-click iteration execution (`iterate`);
- optional parallel team execution (`iterate-parallel`);
- persistent status/memory artifacts;
- local API server with health/status/iterate endpoints;
- smoke tests for pass/fail/guard flows.

## Risks

- Environment permissions can block git and pip temp directories.
- Features without executable commands can be falsely marked as done.
- Command-driven implementation is flexible but requires careful command curation.

Mitigations in this repo:

- explicit blocker capture in `AGENT_STATUS.md`;
- guard that rejects feature completion when both implementation and verification commands are missing;
- guard that restricts parallel mode to `parallel_safe=true` features by default;
- frequent small commits and append-only progress logs.

## Core Ideas

- Initializer creates durable project memory and repeatable startup scripts.
- Iterations are incremental and feature-driven (single pending feature at a time).
- Separate responsibilities for orchestration, coding actions, and operation/testing actions.
- Each iteration leaves a clean, auditable trail (`AGENT_STATUS.md`, `progress.log`, git history).

## Project Layout

```text
.
|- src/caasys/
|  |- agents.py
|  |- cli.py
|  |- engine.py
|  |- models.py
|  |- orchestrator.py
|  |- server.py
|  `- storage.py
|- tests/
|- AGENT_STATUS.md
|- feature_list.json
`- progress.log
```

## Quick Start

```bash
$env:PYTHONPATH='src'
python -m caasys.cli --root . init --objective "Build my project autonomously"
python -m caasys.cli --root . policy
python -m caasys.cli --root . quality-gate --dry-run
python -m caasys.cli --root . add-feature --id F-100 --description "Run first task" --parallel-safe --impl "echo implement" --verify "echo verify"
python -m caasys.cli --root . iterate
python -m caasys.cli --root . iterate-parallel --teams 2 --max-features 2
python -m caasys.cli --root . status
```

Parallel mode notes:

- By default, only features marked with `parallel_safe=true` are scheduled in parallel.
- Use `--force-unsafe` only when you accept potential conflicts.
- Each parallel team still executes `Programmer -> Operator` flow for its assigned feature.

## Local Deployment

```bash
$env:PYTHONPATH='src'
python -m caasys.cli --root . serve --host 127.0.0.1 --port 8787
```

API endpoints:

- `GET /health`
- `GET /status`
- `GET /policy`
- `GET /quality-gate`
- `POST /iterate`
- `POST /iterate-parallel`

## Testing

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
