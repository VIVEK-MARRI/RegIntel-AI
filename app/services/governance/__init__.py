"""Module 8.6 — AI Governance Layer.

Public surface
--------------
* ``GovernanceEngine``   — evaluates a decision against enabled policies
* ``PolicyManager``      — CRUD for policies
* ``DecisionRegistry``   — captures AI decisions + verdicts
* ``GovernanceRepository``— search / stats over decisions
* ``InMemoryGovernanceStore``
* ``GovernanceService``  — DI facade
* ``build_default_governance_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.governance import (
    ApprovalPolicy,
    ApprovalPolicyCreateRequest,
    DecisionRegistryFilter,
    DecisionType,
    GovernanceDecision,
    GovernanceDecisionCreateRequest,
    GovernancePolicy,
    GovernancePolicyCreateRequest,
    GovernanceStats,
    PaginatedDecisions,
    PolicyAction,
    PolicyCheckResult,
    PolicyRule,
    PolicyRuleKind,
    PolicySeverity,
    PolicyScope,
    PolicyViolation,
)
from app.services.observability import (
    get_governance_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Risk-level ordering (used for ceiling checks) ────────────────


_RISK_LEVEL_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


# ─── GovernanceEngine ─────────────────────────────────────────────


class GovernanceEngine:
    """Evaluates a decision against enabled policies.

    The engine is intentionally rule-based and dependency-free so that
    it remains deterministic and easy to test.
    """

    def check(
        self,
        decision: GovernanceDecision,
        policies: List[GovernancePolicy],
    ) -> PolicyCheckResult:
        """Run ``decision`` through every enabled rule in ``policies``."""
        with track_request(
            endpoint="/api/v1/governance/check",
            strategy="policy_check",
        ):
            violations: List[PolicyViolation] = []
            required_actions: List[PolicyAction] = []
            evaluated = 0
            evaluated_policies: List[str] = []
            notes: List[str] = []

            for policy in policies:
                if not policy.enabled:
                    continue
                evaluated_policies.append(policy.policy_id)
                for rule in policy.rules:
                    if not rule.enabled:
                        continue
                    evaluated += 1
                    violation = self._evaluate_rule(rule, policy, decision)
                    if violation is not None:
                        violations.append(violation)
                        if violation.action not in required_actions:
                            required_actions.append(violation.action)
                        if violation.action == PolicyAction.BLOCK:
                            notes.append(
                                f"blocked by {policy.name} :: {rule.name}"
                            )

            blocking = any(
                v.action == PolicyAction.BLOCK for v in violations
            )
            compliant = not blocking

            result = PolicyCheckResult(
                decision_id=decision.decision_id,
                policy_compliant=compliant,
                violations=violations,
                required_actions=required_actions,
                evaluated_policies=evaluated_policies,
                evaluated_rules=evaluated,
                notes="; ".join(notes) if notes else "",
            )
            # Bookkeeping
            metrics = get_governance_metrics()
            metrics.record_check(compliant=compliant, violation_count=len(violations))
            for v in violations:
                metrics.record_violation(
                    severity=v.severity, action=v.action
                )
            return result

    # ─── rule evaluators ─────────────────────────────────────────

    def _evaluate_rule(
        self,
        rule: PolicyRule,
        policy: GovernancePolicy,
        decision: GovernanceDecision,
    ) -> Optional[PolicyViolation]:
        kind = rule.kind
        params = rule.parameters or {}

        if kind == PolicyRuleKind.CONFIDENCE_THRESHOLD:
            min_conf = float(params.get("min_confidence", 0.7))
            if decision.confidence < min_conf:
                return self._make_violation(
                    rule,
                    policy,
                    message=(
                        f"confidence {decision.confidence:.2f} below "
                        f"threshold {min_conf:.2f}"
                    ),
                    details={"min_confidence": min_conf},
                )

        elif kind == PolicyRuleKind.HUMAN_IN_LOOP:
            categories = params.get("categories", []) or []
            if not categories or decision.decision_type.value in categories:
                if not decision.approved_by:
                    return self._make_violation(
                        rule,
                        policy,
                        message=(
                            "human-in-the-loop approval required but no "
                            "approver recorded"
                        ),
                        details={"required_categories": categories},
                    )

        elif kind == PolicyRuleKind.APPROVAL_REQUIRED:
            min_approvers = int(params.get("min_approvers", 1))
            if len(decision.approved_by) < min_approvers:
                return self._make_violation(
                    rule,
                    policy,
                    message=(
                        f"requires {min_approvers} approval(s); "
                        f"got {len(decision.approved_by)}"
                    ),
                    details={"min_approvers": min_approvers},
                )

        elif kind == PolicyRuleKind.MODEL_BLACKLIST:
            blocked = [m.lower() for m in params.get("blocked_models", []) or []]
            if decision.model_id and decision.model_id.lower() in blocked:
                return self._make_violation(
                    rule,
                    policy,
                    message=f"model '{decision.model_id}' is blacklisted",
                    details={"blocked_models": blocked},
                )

        elif kind == PolicyRuleKind.RISK_LEVEL_CEILING:
            max_level = str(params.get("max_risk_level", "high")).lower()
            max_rank = _RISK_LEVEL_ORDER.get(max_level, 2)
            actual_rank = _RISK_LEVEL_ORDER.get(decision.risk_level.lower(), 0)
            if actual_rank > max_rank:
                return self._make_violation(
                    rule,
                    policy,
                    message=(
                        f"risk level '{decision.risk_level}' exceeds "
                        f"ceiling '{max_level}'"
                    ),
                    details={"max_risk_level": max_level},
                )

        elif kind == PolicyRuleKind.CATEGORY_RESTRICTION:
            blocked_cats = {
                c.lower() for c in params.get("blocked_categories", []) or []
            }
            for cat in decision.categories:
                if cat.lower() in blocked_cats:
                    return self._make_violation(
                        rule,
                        policy,
                        message=f"category '{cat}' is restricted",
                        details={"blocked_categories": list(blocked_cats)},
                    )

        elif kind == PolicyRuleKind.DATA_RESIDENCY:
            allowed = {
                r.lower() for r in params.get("allowed_regions", []) or []
            }
            region = str(params.get("region_key", "region")).lower()
            actual = str(decision.metadata.get(region, "")).lower()
            if allowed and actual and actual not in allowed:
                return self._make_violation(
                    rule,
                    policy,
                    message=(
                        f"data residency violation: '{actual}' not in "
                        f"allowed regions"
                    ),
                    details={"allowed_regions": list(allowed)},
                )

        elif kind == PolicyRuleKind.PII_PROHIBITION:
            if decision.metadata.get("contains_pii"):
                return self._make_violation(
                    rule,
                    policy,
                    message="PII present in decision inputs/outputs",
                    details={"pii_flag": True},
                )

        elif kind == PolicyRuleKind.EXPLAINABILITY_REQUIRED:
            if not decision.outputs.get("explanation"):
                return self._make_violation(
                    rule,
                    policy,
                    message="explainability required: no 'explanation' in outputs",
                    details={"required": "outputs.explanation"},
                )

        return None

    def _make_violation(
        self,
        rule: PolicyRule,
        policy: GovernancePolicy,
        message: str,
        details: Dict[str, Any],
    ) -> PolicyViolation:
        return PolicyViolation(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            policy_id=policy.policy_id,
            policy_name=policy.name,
            kind=rule.kind,
            action=rule.action,
            severity=rule.severity,
            message=message,
            details=details,
        )


# ─── PolicyManager ───────────────────────────────────────────────


class PolicyManager:
    """CRUD + lookup for policies and approval policies."""

    def __init__(self, store: "InMemoryGovernanceStore") -> None:
        self._store = store

    # ─── GovernancePolicy ─────────────────────────────────────

    def create_policy(
        self, request: GovernancePolicyCreateRequest
    ) -> GovernancePolicy:
        with track_request(
            endpoint="/api/v1/governance/policies/create",
            strategy="policy_create",
        ):
            policy = GovernancePolicy(
                name=request.name,
                description=request.description,
                version=request.version,
                scope=request.scope,
                scope_value=request.scope_value,
                rules=request.rules,
                enabled=request.enabled,
                tags=request.tags,
            )
            self._store.add_policy(policy)
            get_governance_metrics().record_policy_created(
                rule_count=len(policy.rules)
            )
            return policy

    def get_policy(self, policy_id: str) -> Optional[GovernancePolicy]:
        return self._store.get_policy(policy_id)

    def list_policies(
        self,
        *,
        scope: Optional[PolicyScope] = None,
        enabled_only: bool = False,
    ) -> List[GovernancePolicy]:
        return self._store.list_policies(scope=scope, enabled_only=enabled_only)

    def update_policy(
        self,
        policy_id: str,
        *,
        enabled: Optional[bool] = None,
        rules: Optional[List[PolicyRule]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[GovernancePolicy]:
        policy = self._store.get_policy(policy_id)
        if policy is None:
            return None
        if enabled is not None:
            policy.enabled = enabled
        if rules is not None:
            policy.rules = rules
        if name is not None:
            policy.name = name
        if description is not None:
            policy.description = description
        policy.updated_at = time.time()
        self._store.update_policy(policy)
        return policy

    def delete_policy(self, policy_id: str) -> bool:
        return self._store.delete_policy(policy_id)

    def policies_for_decision(
        self,
        decision: GovernanceDecision,
    ) -> List[GovernancePolicy]:
        """Return the enabled policies that apply to ``decision``."""
        out: List[GovernancePolicy] = []
        for policy in self._store.list_policies(enabled_only=True):
            if self._policy_applies(policy, decision):
                out.append(policy)
        return out

    @staticmethod
    def _policy_applies(
        policy: GovernancePolicy, decision: GovernanceDecision
    ) -> bool:
        if policy.scope == PolicyScope.GLOBAL:
            return True
        if policy.scope == PolicyScope.MODEL and policy.scope_value:
            return decision.model_id == policy.scope_value
        if policy.scope == PolicyScope.REGULATOR and policy.scope_value:
            return (
                str(decision.metadata.get("regulator", "")).lower()
                == policy.scope_value.lower()
            )
        if policy.scope == PolicyScope.WORKFLOW and policy.scope_value:
            return decision.subject_id == policy.scope_value
        if policy.scope == PolicyScope.DOCUMENT and policy.scope_value:
            return decision.subject_id == policy.scope_value
        return True

    # ─── ApprovalPolicy ───────────────────────────────────────

    def create_approval_policy(
        self, request: ApprovalPolicyCreateRequest
    ) -> ApprovalPolicy:
        policy = ApprovalPolicy(
            name=request.name,
            description=request.description,
            decision_types=request.decision_types,
            min_risk_level=request.min_risk_level,
            required_roles=request.required_roles,
            min_approvers=request.min_approvers,
            applies_to=request.applies_to,
            enabled=request.enabled,
        )
        self._store.add_approval_policy(policy)
        return policy

    def get_approval_policy(
        self, policy_id: str
    ) -> Optional[ApprovalPolicy]:
        return self._store.get_approval_policy(policy_id)

    def list_approval_policies(self) -> List[ApprovalPolicy]:
        return self._store.list_approval_policies()

    def matching_approval_policies(
        self, decision: GovernanceDecision
    ) -> List[ApprovalPolicy]:
        out: List[ApprovalPolicy] = []
        for policy in self._store.list_approval_policies():
            if not policy.enabled:
                continue
            if (
                policy.decision_types
                and decision.decision_type not in policy.decision_types
            ):
                continue
            if policy.min_risk_level:
                min_rank = _RISK_LEVEL_ORDER.get(
                    policy.min_risk_level.lower(), 0
                )
                actual_rank = _RISK_LEVEL_ORDER.get(
                    decision.risk_level.lower(), 0
                )
                if actual_rank < min_rank:
                    continue
            out.append(policy)
        return out

    def delete_approval_policy(self, policy_id: str) -> bool:
        return self._store.delete_approval_policy(policy_id)


# ─── DecisionRegistry ────────────────────────────────────────────


class DecisionRegistry:
    """Captures and retrieves AI decisions."""

    def __init__(self, store: "InMemoryGovernanceStore") -> None:
        self._store = store

    def register(
        self,
        request: GovernanceDecisionCreateRequest,
        *,
        check_policies: bool = True,
        policies: Optional[List[GovernancePolicy]] = None,
    ) -> GovernanceDecision:
        with track_request(
            endpoint="/api/v1/governance/decisions/register",
            strategy="decision_register",
        ):
            decision = GovernanceDecision(
                decision_type=request.decision_type,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                model_id=request.model_id,
                model_version=request.model_version,
                decision=request.decision,
                confidence=request.confidence,
                risk_level=request.risk_level,
                categories=request.categories,
                inputs=request.inputs,
                outputs=request.outputs,
                actor=request.actor,
                metadata=request.metadata,
            )
            if check_policies:
                engine = GovernanceEngine()
                result = engine.check(decision, policies or [])
                decision.policy_result = result
            self._store.add_decision(decision)
            get_governance_metrics().record_decision(decision)
            return decision

    def get(self, decision_id: str) -> Optional[GovernanceDecision]:
        return self._store.get_decision(decision_id)

    def search(
        self, flt: DecisionRegistryFilter
    ) -> PaginatedDecisions:
        items = self._store.list_decisions(flt)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        page_items = items[start:end]
        return PaginatedDecisions(
            items=page_items,
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def list_all(self) -> List[GovernanceDecision]:
        return self._store.list_decisions(DecisionRegistryFilter(page=1, page_size=10000))


# ─── GovernanceRepository ────────────────────────────────────────


class GovernanceRepository:
    """Aggregate-level queries over the governance data set."""

    def __init__(self, store: "InMemoryGovernanceStore") -> None:
        self._store = store

    def stats(self) -> GovernanceStats:
        decisions = self._store.list_decisions_unfiltered()
        policies = self._store.list_policies()
        total_rules = sum(len(p.rules) for p in policies)
        compliant = 0
        non_compliant = 0
        total_violations = 0
        blocking = 0
        by_dt: Dict[str, int] = {}
        by_sev: Dict[str, int] = {}
        by_act: Dict[str, int] = {}
        by_model: Dict[str, int] = {}
        for d in decisions:
            by_dt[d.decision_type.value] = by_dt.get(d.decision_type.value, 0) + 1
            if d.model_id:
                by_model[d.model_id] = by_model.get(d.model_id, 0) + 1
            if d.policy_result is None:
                continue
            if d.policy_result.policy_compliant:
                compliant += 1
            else:
                non_compliant += 1
            for v in d.policy_result.violations:
                total_violations += 1
                if v.action == PolicyAction.BLOCK:
                    blocking += 1
                by_sev[v.severity.value] = by_sev.get(v.severity.value, 0) + 1
                by_act[v.action.value] = by_act.get(v.action.value, 0) + 1
        rate = (
            compliant / max(1, compliant + non_compliant)
        )
        avg_v = total_violations / max(1, len(decisions))
        return GovernanceStats(
            total_policies=len(policies),
            total_rules=total_rules,
            total_decisions=len(decisions),
            compliant_decisions=compliant,
            non_compliant_decisions=non_compliant,
            total_violations=total_violations,
            blocking_violations=blocking,
            average_violations_per_decision=round(avg_v, 3),
            compliance_rate=round(rate, 4),
            by_decision_type=by_dt,
            by_severity=by_sev,
            by_action=by_act,
            by_model=by_model,
            last_decision_at=max(
                (d.timestamp for d in decisions), default=None
            ),
        )


# ─── InMemoryGovernanceStore ──────────────────────────────────────


class GovernanceStore(ABC):
    """Abstract storage for governance data."""

    @abstractmethod
    def add_policy(self, policy: GovernancePolicy) -> None: ...
    @abstractmethod
    def get_policy(self, policy_id: str) -> Optional[GovernancePolicy]: ...
    @abstractmethod
    def list_policies(
        self,
        *,
        scope: Optional[PolicyScope] = None,
        enabled_only: bool = False,
    ) -> List[GovernancePolicy]: ...
    @abstractmethod
    def update_policy(self, policy: GovernancePolicy) -> None: ...
    @abstractmethod
    def delete_policy(self, policy_id: str) -> bool: ...

    @abstractmethod
    def add_approval_policy(self, policy: ApprovalPolicy) -> None: ...
    @abstractmethod
    def get_approval_policy(
        self, policy_id: str
    ) -> Optional[ApprovalPolicy]: ...
    @abstractmethod
    def list_approval_policies(self) -> List[ApprovalPolicy]: ...
    @abstractmethod
    def delete_approval_policy(self, policy_id: str) -> bool: ...

    @abstractmethod
    def add_decision(self, decision: GovernanceDecision) -> None: ...
    @abstractmethod
    def get_decision(
        self, decision_id: str
    ) -> Optional[GovernanceDecision]: ...
    @abstractmethod
    def list_decisions(
        self, flt: DecisionRegistryFilter
    ) -> List[GovernanceDecision]: ...
    @abstractmethod
    def list_decisions_unfiltered(self) -> List[GovernanceDecision]: ...


class InMemoryGovernanceStore(GovernanceStore):
    """Thread-safe in-memory store with optional JSONL persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._policies: Dict[str, GovernancePolicy] = {}
        self._approval_policies: Dict[str, ApprovalPolicy] = {}
        self._decisions: Dict[str, GovernanceDecision] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if persist_path:
            self._load()

    # ─── policies ─────────────────────────────────────────────

    def add_policy(self, policy: GovernancePolicy) -> None:
        with self._lock:
            self._policies[policy.policy_id] = policy
            self._persist()

    def get_policy(
        self, policy_id: str
    ) -> Optional[GovernancePolicy]:
        with self._lock:
            return self._policies.get(policy_id)

    def list_policies(
        self,
        *,
        scope: Optional[PolicyScope] = None,
        enabled_only: bool = False,
    ) -> List[GovernancePolicy]:
        with self._lock:
            items = list(self._policies.values())
        if scope is not None:
            items = [p for p in items if p.scope == scope]
        if enabled_only:
            items = [p for p in items if p.enabled]
        return sorted(items, key=lambda p: p.created_at)

    def update_policy(self, policy: GovernancePolicy) -> None:
        with self._lock:
            self._policies[policy.policy_id] = policy
            self._persist()

    def delete_policy(self, policy_id: str) -> bool:
        with self._lock:
            existed = policy_id in self._policies
            self._policies.pop(policy_id, None)
            self._persist()
            return existed

    # ─── approval policies ───────────────────────────────────

    def add_approval_policy(self, policy: ApprovalPolicy) -> None:
        with self._lock:
            self._approval_policies[policy.policy_id] = policy
            self._persist()

    def get_approval_policy(
        self, policy_id: str
    ) -> Optional[ApprovalPolicy]:
        with self._lock:
            return self._approval_policies.get(policy_id)

    def list_approval_policies(self) -> List[ApprovalPolicy]:
        with self._lock:
            return sorted(
                self._approval_policies.values(),
                key=lambda p: p.created_at,
            )

    def delete_approval_policy(self, policy_id: str) -> bool:
        with self._lock:
            existed = policy_id in self._approval_policies
            self._approval_policies.pop(policy_id, None)
            self._persist()
            return existed

    # ─── decisions ───────────────────────────────────────────

    def add_decision(self, decision: GovernanceDecision) -> None:
        with self._lock:
            self._decisions[decision.decision_id] = decision
            self._persist()

    def get_decision(
        self, decision_id: str
    ) -> Optional[GovernanceDecision]:
        with self._lock:
            return self._decisions.get(decision_id)

    def list_decisions(
        self, flt: DecisionRegistryFilter
    ) -> List[GovernanceDecision]:
        with self._lock:
            items = list(self._decisions.values())
        if flt.decision_type is not None:
            items = [d for d in items if d.decision_type == flt.decision_type]
        if flt.model_id is not None:
            items = [d for d in items if d.model_id == flt.model_id]
        if flt.subject_type is not None:
            items = [d for d in items if d.subject_type == flt.subject_type]
        if flt.subject_id is not None:
            items = [d for d in items if d.subject_id == flt.subject_id]
        if flt.risk_level is not None:
            items = [d for d in items if d.risk_level.lower() == flt.risk_level.lower()]
        if flt.actor is not None:
            items = [d for d in items if d.actor == flt.actor]
        if flt.policy_compliant is not None:
            items = [
                d for d in items
                if d.policy_result is not None
                and d.policy_result.policy_compliant == flt.policy_compliant
            ]
        if flt.after is not None:
            items = [d for d in items if d.timestamp >= flt.after]
        if flt.before is not None:
            items = [d for d in items if d.timestamp <= flt.before]
        return sorted(items, key=lambda d: d.timestamp)

    def list_decisions_unfiltered(self) -> List[GovernanceDecision]:
        with self._lock:
            items = list(self._decisions.values())
        return sorted(items, key=lambda d: d.timestamp)

    # ─── persistence ─────────────────────────────────────────

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            payload = {
                "policies": [
                    json.loads(p.model_dump_json())
                    for p in self._policies.values()
                ],
                "approval_policies": [
                    json.loads(p.model_dump_json())
                    for p in self._approval_policies.values()
                ],
                "decisions": [
                    json.loads(d.model_dump_json())
                    for d in self._decisions.values()
                ],
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception:  # pragma: no cover - best effort
            logger.exception("Failed to persist governance store")

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            for raw in payload.get("policies", []):
                self._policies[raw["policy_id"]] = GovernancePolicy(**raw)
            for raw in payload.get("approval_policies", []):
                self._approval_policies[raw["policy_id"]] = ApprovalPolicy(**raw)
            for raw in payload.get("decisions", []):
                self._decisions[raw["decision_id"]] = GovernanceDecision(**raw)
        except Exception:  # pragma: no cover - best effort
            logger.exception("Failed to load governance store")


# ─── Default policies (seeded on first use) ─────────────────────


def _seed_default_policies(
    store: InMemoryGovernanceStore,
) -> List[GovernancePolicy]:
    """Populate a small set of baseline governance policies."""
    seeds: List[GovernancePolicy] = [
        GovernancePolicy(
            name="High-Confidence Baseline",
            description=(
                "All AI decisions must meet a minimum confidence threshold."
            ),
            scope=PolicyScope.GLOBAL,
            rules=[
                PolicyRule(
                    name="Min confidence 0.7",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.BLOCK,
                    severity=PolicySeverity.MEDIUM,
                    parameters={"min_confidence": 0.7},
                )
            ],
        ),
        GovernancePolicy(
            name="High-Risk Human-in-the-Loop",
            description=(
                "Decisions classified as high or critical must be human-"
                "approved before becoming effective."
            ),
            scope=PolicyScope.GLOBAL,
            rules=[
                PolicyRule(
                    name="Human approval for high/critical",
                    kind=PolicyRuleKind.HUMAN_IN_LOOP,
                    action=PolicyAction.REQUIRE_HUMAN_REVIEW,
                    severity=PolicySeverity.HIGH,
                    parameters={"categories": []},
                )
            ],
        ),
        GovernancePolicy(
            name="Explainability Required",
            description=(
                "All decisions must include a human-readable explanation."
            ),
            scope=PolicyScope.GLOBAL,
            rules=[
                PolicyRule(
                    name="outputs.explanation required",
                    kind=PolicyRuleKind.EXPLAINABILITY_REQUIRED,
                    action=PolicyAction.WARN,
                    severity=PolicySeverity.MEDIUM,
                    parameters={},
                )
            ],
        ),
    ]
    for p in seeds:
        if not store.get_policy(p.policy_id):
            store.add_policy(p)
    return seeds


# ─── GovernanceService (DI facade) ──────────────────────────────


class GovernanceService:
    """Single point of entry for governance operations."""

    def __init__(self, store: InMemoryGovernanceStore) -> None:
        self.store = store
        self.engine = GovernanceEngine()
        self.policy_manager = PolicyManager(store)
        self.registry = DecisionRegistry(store)
        self.repository = GovernanceRepository(store)
        # Seed default policies
        self._default_policies = _seed_default_policies(store)

    # ─── policies ─────────────────────────────────────────────

    def create_policy(
        self, request: GovernancePolicyCreateRequest
    ) -> GovernancePolicy:
        return self.policy_manager.create_policy(request)

    def get_policy(
        self, policy_id: str
    ) -> Optional[GovernancePolicy]:
        return self.policy_manager.get_policy(policy_id)

    def list_policies(
        self,
        scope: Optional[PolicyScope] = None,
        enabled_only: bool = False,
    ) -> List[GovernancePolicy]:
        return self.policy_manager.list_policies(
            scope=scope, enabled_only=enabled_only
        )

    def update_policy(
        self,
        policy_id: str,
        *,
        enabled: Optional[bool] = None,
        rules: Optional[List[PolicyRule]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[GovernancePolicy]:
        return self.policy_manager.update_policy(
            policy_id,
            enabled=enabled,
            rules=rules,
            name=name,
            description=description,
        )

    def delete_policy(self, policy_id: str) -> bool:
        return self.policy_manager.delete_policy(policy_id)

    def create_approval_policy(
        self, request: ApprovalPolicyCreateRequest
    ) -> ApprovalPolicy:
        return self.policy_manager.create_approval_policy(request)

    def list_approval_policies(self) -> List[ApprovalPolicy]:
        return self.policy_manager.list_approval_policies()

    def get_approval_policy(
        self, policy_id: str
    ) -> Optional[ApprovalPolicy]:
        return self.policy_manager.get_approval_policy(policy_id)

    def delete_approval_policy(self, policy_id: str) -> bool:
        return self.policy_manager.delete_approval_policy(policy_id)

    def matching_approval_policies(
        self, decision: GovernanceDecision
    ) -> List[ApprovalPolicy]:
        return self.policy_manager.matching_approval_policies(decision)

    # ─── decisions ───────────────────────────────────────────

    def register_decision(
        self, request: GovernanceDecisionCreateRequest
    ) -> GovernanceDecision:
        policies = self.policy_manager.policies_for_decision(
            GovernanceDecision(
                decision_type=request.decision_type,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                model_id=request.model_id,
                risk_level=request.risk_level,
                categories=request.categories,
                metadata=request.metadata,
            )
        ) if request.check_policies else []
        return self.registry.register(
            request,
            check_policies=request.check_policies,
            policies=policies,
        )

    def check_decision(
        self,
        decision: GovernanceDecision,
    ) -> PolicyCheckResult:
        policies = self.policy_manager.policies_for_decision(decision)
        return self.engine.check(decision, policies)

    def get_decision(
        self, decision_id: str
    ) -> Optional[GovernanceDecision]:
        return self.registry.get(decision_id)

    def search_decisions(
        self, flt: DecisionRegistryFilter
    ) -> PaginatedDecisions:
        return self.registry.search(flt)

    # ─── stats ───────────────────────────────────────────────

    def stats(self) -> GovernanceStats:
        return self.repository.stats()

    # ─── audit hook ──────────────────────────────────────────

    def record_audit(
        self,
        audit_service: Any = None,
        actor: str = "system",
        action: str = "governance.decision",
    ) -> None:
        """Best-effort: forward a record to the audit service if provided."""
        if audit_service is None:
            return
        try:
            from app.schemas.audit import (
                AuditAction,
                AuditRecordCreateRequest,
                AuditSeverity,
            )

            audit_service.create_record(
                AuditRecordCreateRequest(
                    actor=actor,
                    action=AuditAction.POLICY_CHECK,
                    severity=AuditSeverity.INFO,
                    subject_type="governance",
                    subject_id="",
                    description=action,
                    source_module="governance",
                )
            )
        except Exception:  # pragma: no cover - non-fatal
            logger.exception("Failed to forward governance audit event")


# ─── Default factory ────────────────────────────────────────────


def build_default_governance_service() -> GovernanceService:
    """Build a default :class:`GovernanceService` with a JSONL-backed store."""
    persist_path = os.path.join(
        settings.STORAGE_ROOT, "governance", "governance.jsonl"
    )
    store = InMemoryGovernanceStore(persist_path=persist_path)
    return GovernanceService(store)


__all__ = [
    "GovernanceEngine",
    "PolicyManager",
    "DecisionRegistry",
    "GovernanceRepository",
    "GovernanceStore",
    "InMemoryGovernanceStore",
    "GovernanceService",
    "build_default_governance_service",
]
