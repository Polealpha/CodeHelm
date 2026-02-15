"""Orchestration logic for choosing next feature and agent delegation."""

from __future__ import annotations

from .models import AgentPolicy, Feature


class Orchestrator:
    """Coordinates feature selection and role delegation."""

    def __init__(self, policy: AgentPolicy | None = None) -> None:
        self.policy = policy or AgentPolicy()

    def pick_next_feature(
        self,
        features: list[Feature],
        *,
        exclude_feature_ids: set[str] | None = None,
    ) -> Feature | None:
        excluded = exclude_feature_ids or set()
        pending = [feature for feature in features if not feature.passes and feature.id not in excluded]
        if not pending:
            return None
        pending.sort(key=lambda feature: (feature.priority, feature.id))
        return pending[0]

    def pick_next_features(
        self,
        features: list[Feature],
        count: int,
        *,
        exclude_feature_ids: set[str] | None = None,
    ) -> list[Feature]:
        excluded = exclude_feature_ids or set()
        pending = [feature for feature in features if not feature.passes and feature.id not in excluded]
        pending.sort(key=lambda feature: (feature.priority, feature.id))
        return pending[:count]

    def build_plan(self, feature: Feature) -> list[str]:
        plan = [
            f"PLAN: choose feature {feature.id} ({feature.description})",
            "IMPLEMENT: delegate implementation commands to ProgrammerAgent",
            "RUN: delegate verification command to OperatorAgent",
            "OBSERVE: inspect command exit codes and output",
            "FIX: capture blockers when failures occur",
            "NEXT: queue next pending feature by priority",
        ]
        if self.policy.zero_ask:
            plan.append("POLICY: zero-ask enabled, use fallback chain instead of interactive questions")
        return plan
