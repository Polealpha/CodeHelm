# Continuous Autonomous Engineering System

This project implements a local, runnable system for long-running autonomous software development loops inspired by:

- `lunwen` (Effective harnesses for long-running agents, 2025-11-26)
- `2508.03923v2.pdf` (CoAct-1: Computer-using Agents with Coding as Actions)

The system follows a strict cycle:

`PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> COMMIT -> NEXT`

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
python -m venv .venv
. .venv/Scripts/activate
pip install -e .
caasys init --objective "Build my project autonomously"
caasys status
caasys iterate
```

## Local Deployment

```bash
caasys serve --host 127.0.0.1 --port 8787
```

API endpoints:

- `GET /health`
- `GET /status`
- `POST /iterate`

## Testing

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
