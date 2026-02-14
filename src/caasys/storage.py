"""Persistence utilities for status, feature lists, and logs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import AgentPolicy, AgentStatus, Feature

STATUS_MD = "AGENT_STATUS.md"
POLICY_MD = "AGENT_POLICY.md"
FEATURES_JSON = "feature_list.json"
PROGRESS_LOG = "progress.log"
STATE_DIR = ".caasys"
STATE_FILE = "state.json"
POLICY_FILE = "policy.json"


def ensure_state_dir(root: Path) -> Path:
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_features(root: Path) -> list[Feature]:
    path = root / FEATURES_JSON
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Feature.from_dict(item) for item in payload]


def save_features(root: Path, features: list[Feature]) -> None:
    path = root / FEATURES_JSON
    serialized = [item.to_dict() for item in features]
    serialized.sort(key=lambda item: (item["passes"], item["priority"], item["id"]))
    path.write_text(json.dumps(serialized, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_status(root: Path) -> AgentStatus:
    state_path = ensure_state_dir(root) / STATE_FILE
    if state_path.exists():
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return AgentStatus.from_dict(payload)

    # Fallback when only AGENT_STATUS.md exists from manual edits.
    md_path = root / STATUS_MD
    if md_path.exists():
        return AgentStatus(current_objective=_extract_current_objective(md_path.read_text(encoding="utf-8")))
    return AgentStatus(current_objective="")


def load_policy(root: Path) -> AgentPolicy:
    policy_path = ensure_state_dir(root) / POLICY_FILE
    if policy_path.exists():
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
        return AgentPolicy.from_dict(payload)
    return AgentPolicy()


def save_status(root: Path, status: AgentStatus) -> None:
    state_dir = ensure_state_dir(root)
    (state_dir / STATE_FILE).write_text(
        json.dumps(status.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (root / STATUS_MD).write_text(status.to_markdown(), encoding="utf-8")


def save_policy(root: Path, policy: AgentPolicy) -> None:
    state_dir = ensure_state_dir(root)
    (state_dir / POLICY_FILE).write_text(
        json.dumps(policy.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (root / POLICY_MD).write_text(policy.to_markdown(), encoding="utf-8")


def append_progress(root: Path, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    path = root / PROGRESS_LOG
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + f"{prefix}{ts} {message}\n", encoding="utf-8")


def read_progress_tail(root: Path, lines: int = 10) -> list[str]:
    path = root / PROGRESS_LOG
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8").splitlines()
    return content[-lines:] if len(content) > lines else content


def _extract_current_objective(markdown: str) -> str:
    lines = markdown.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## current objective":
            for next_line in lines[idx + 1 :]:
                candidate = next_line.strip()
                if candidate:
                    return candidate
            break
    return ""
