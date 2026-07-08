"""Module 8.6 — AI Governance Layer contracts.

Pydantic v2 with ``extra="forbid"`` for all models. The Governance Layer
sits above the Risk, Recommendation, Workflow and Review modules and is
the authoritative place to:

* register AI model decisions and the policy verdicts they received
* manage approval policies and risk-control rules
* expose a single ``PolicyCheckResult`` shape for downstream consumers

Public surface
--------------
* ``PolicyRuleKind`` / ``PolicyAction`` / ``PolicySeverity`` — enums
* ``PolicyRule``, ``PolicyViolation`` — atomic rule + outcome
* ``GovernancePolicy`` — versioned, scoped policy document
* ``ApprovalPolicy`` — who/what may approve which decision
* ``GovernanceDecision`` — captured AI decision with verdict
* ``PolicyCheckResult`` — output of :class:`GovernanceEngine.check`
* ``DecisionRegistryFilter`` / ``PaginatedDecisions`` / ``GovernanceStats``
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────────


class PolicyRuleKind(str, Enum):
    """Kinds of governance rules the engine understands."""

    CONFIDENCE_THRESHOLD = "confidence_threshold"
    HUMAN_IN_LOOP = "human_in_loop"
    APPROVAL_REQUIRED = "approval_required"
    MODEL_BLACKLIST = "model_blacklist"
    RISK_LEVEL_CEILING = "risk_level_ceiling"
    CATEGORY_RESTRICTION = "category_restriction"
    DATA_RESIDENCY = "data_residency"
    PII_PROHIBITION = "pii_prohibition"
    EXPLAINABILITY_REQUIRED = "explainability_required"


class PolicyAction(str, Enum):
    """Action prescribed by a policy rule on a match."""

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    ESCALATE = "escalate"


class PolicySeverity(str, Enum):
    """How serious a violation is."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyScope(str, Enum):
    """Scope at which a policy applies."""

    GLOBAL = "global"
    REGULATOR = "regulator"
    DOCUMENT = "document"
    WORKFLOW = "workflow"
    MODEL = "model"


class DecisionType(str, Enum):
    """Types of AI decision the registry can capture."""

    ANSWER = "answer"
    RECOMMENDATION = "recommendation"
    RISK_ASSESSMENT = "risk_assessment"
    FORECAST = "forecast"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"
    OTHER = "other"


# ─── Atomic policy primitives ──────────────────────────────────────


class PolicyRule(BaseModel):
    """A single rule within a :class:`GovernancePolicy`."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(default_factory=lambda: f"rule-{secrets.token_hex(4)}")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    kind: PolicyRuleKind
    action: PolicyAction = PolicyAction.WARN
    severity: PolicySeverity = PolicySeverity.MEDIUM
    # Free-form conditions evaluated by the engine; keys depend on
    # ``kind``. Examples:
    #   {"min_confidence": 0.7}
    #   {"max_risk_level": "high"}
    #   {"blocked_models": ["gpt-3.5-turbo"]}
    #   {"categories": ["DATA_PRIVACY", "OUTSOURCING"]}
    parameters: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PolicyViolation(BaseModel):
    """A single violation emitted by a policy check."""

    model_config = ConfigDict(extra="forbid")

    violation_id: str = Field(default_factory=lambda: f"vio-{secrets.token_hex(4)}")
    rule_id: str
    rule_name: str
    policy_id: str
    policy_name: str
    kind: PolicyRuleKind
    action: PolicyAction
    severity: PolicySeverity
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


# ─── Policy documents ─────────────────────────────────────────────


class GovernancePolicy(BaseModel):
    """A versioned, scoped policy document containing one or more rules."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(default_factory=lambda: f"pol-{uuid.uuid4().hex[:12]}")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    version: str = "1.0.0"
    scope: PolicyScope = PolicyScope.GLOBAL
    scope_value: str = ""  # e.g. regulator name, model id, workflow id
    rules: List[PolicyRule] = Field(default_factory=list)
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    tags: List[str] = Field(default_factory=list)


class ApprovalPolicy(BaseModel):
    """An approval policy binding roles to decision types / risk levels."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(default_factory=lambda: f"aprv-{uuid.uuid4().hex[:12]}")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    decision_types: List[DecisionType] = Field(default_factory=list)
    min_risk_level: Optional[str] = None  # "low" | "medium" | "high" | "critical"
    required_roles: List[str] = Field(default_factory=list)
    min_approvers: int = Field(1, ge=1, le=10)
    applies_to: str = "global"  # "global" | decision_type
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)


# ─── Decision registry ────────────────────────────────────────────


class GovernanceDecision(BaseModel):
    """A captured AI decision with its policy verdict attached."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:12]}")
    decision_type: DecisionType
    subject_type: str = ""  # "document" | "workflow" | "task" | "recommendation" | ...
    subject_id: str = ""
    model_id: str = ""
    model_version: str = ""
    decision: str = ""  # free-form: "approved" | "rejected" | "allow" | "block" | ...
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: str = ""  # "low" | "medium" | "high" | "critical"
    categories: List[str] = Field(default_factory=list)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"
    timestamp: float = Field(default_factory=time.time)
    # The verdict produced by the governance engine at the time of the
    # decision. ``None`` means the decision was not checked.
    policy_result: Optional["PolicyCheckResult"] = None
    approved_by: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionRegistryFilter(BaseModel):
    """Query filter for the decision registry."""

    model_config = ConfigDict(extra="forbid")

    decision_type: Optional[DecisionType] = None
    model_id: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    risk_level: Optional[str] = None
    policy_compliant: Optional[bool] = None
    actor: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedDecisions(BaseModel):
    """A page of governance decisions."""

    model_config = ConfigDict(extra="forbid")

    items: List[GovernanceDecision] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# ─── Check result ────────────────────────────────────────────────


class PolicyCheckResult(BaseModel):
    """The verdict of running a decision through the policy engine."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"chk-{secrets.token_hex(6)}")
    decision_id: str = ""
    policy_compliant: bool = True
    violations: List[PolicyViolation] = Field(default_factory=list)
    required_actions: List[PolicyAction] = Field(default_factory=list)
    evaluated_policies: List[str] = Field(default_factory=list)
    evaluated_rules: int = 0
    timestamp: float = Field(default_factory=time.time)
    notes: str = ""

    @property
    def has_blocking_violation(self) -> bool:
        return any(v.action == PolicyAction.BLOCK for v in self.violations)

    @property
    def highest_severity(self) -> PolicySeverity:
        order = {
            PolicySeverity.INFO: 0,
            PolicySeverity.LOW: 1,
            PolicySeverity.MEDIUM: 2,
            PolicySeverity.HIGH: 3,
            PolicySeverity.CRITICAL: 4,
        }
        if not self.violations:
            return PolicySeverity.INFO
        return max(
            (v.severity for v in self.violations),
            key=lambda s: order.get(s, 0),
        )


# ─── Stats ────────────────────────────────────────────────────────


class GovernanceStats(BaseModel):
    """Aggregate metrics about governance activity."""

    model_config = ConfigDict(extra="forbid")

    total_policies: int = 0
    total_rules: int = 0
    total_decisions: int = 0
    compliant_decisions: int = 0
    non_compliant_decisions: int = 0
    total_violations: int = 0
    blocking_violations: int = 0
    average_violations_per_decision: float = 0.0
    compliance_rate: float = 0.0
    by_decision_type: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_action: Dict[str, int] = Field(default_factory=dict)
    by_model: Dict[str, int] = Field(default_factory=dict)
    last_decision_at: Optional[float] = None


# Resolve the forward reference so model rebuild works.
GovernanceDecision.model_rebuild()


# ─── Request payloads ─────────────────────────────────────────────


class GovernanceDecisionCreateRequest(BaseModel):
    """Request payload to register a new AI decision."""

    model_config = ConfigDict(extra="forbid")

    decision_type: DecisionType
    subject_type: str = ""
    subject_id: str = ""
    model_id: str = ""
    model_version: str = ""
    decision: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: str = ""
    categories: List[str] = Field(default_factory=list)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"
    check_policies: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GovernancePolicyCreateRequest(BaseModel):
    """Request to create a new policy document."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    version: str = "1.0.0"
    scope: PolicyScope = PolicyScope.GLOBAL
    scope_value: str = ""
    rules: List[PolicyRule] = Field(default_factory=list)
    enabled: bool = True
    tags: List[str] = Field(default_factory=list)


class ApprovalPolicyCreateRequest(BaseModel):
    """Request to create a new approval policy."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    decision_types: List[DecisionType] = Field(default_factory=list)
    min_risk_level: Optional[str] = None
    required_roles: List[str] = Field(default_factory=list)
    min_approvers: int = Field(1, ge=1, le=10)
    applies_to: str = "global"
    enabled: bool = True


__all__ = [
    "PolicyRuleKind",
    "PolicyAction",
    "PolicySeverity",
    "PolicyScope",
    "DecisionType",
    "PolicyRule",
    "PolicyViolation",
    "GovernancePolicy",
    "ApprovalPolicy",
    "GovernanceDecision",
    "DecisionRegistryFilter",
    "PaginatedDecisions",
    "PolicyCheckResult",
    "GovernanceStats",
    "GovernanceDecisionCreateRequest",
    "GovernancePolicyCreateRequest",
    "ApprovalPolicyCreateRequest",
]
