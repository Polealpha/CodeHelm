"""Orchestration logic for choosing next feature and agent delegation."""

from __future__ import annotations

from .models import Feature


class Orchestrator:
    """Coordinates feature selection and role delegation."""

    def pick_next_feature(self, features: list[Feature]) -> Feature | None:
        pending = [feature for feature in features if not feature.passes]
        if not pending:
            return None
        pending.sort(key=lambda feature: (feature.priority, feature.id))
        return pending[0]

    def build_plan(self, feature: Feature) -> list[str]:
        plan = [
            f"PLAN: choose feature {feature.id} ({feature.description})",
            "IMPLEMENT: delegate implementation commands to ProgrammerAgent",
            "RUN: delegate verification command to OperatorAgent",
            "OBSERVE: inspect command exit codes and output",
            "FIX: capture blockers when failures occur",
            "NEXT: queue next pending feature by priority",
        ]
        return plan
