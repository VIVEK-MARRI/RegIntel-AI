"""Module 9.7 — Audit Agent schemas.

Contracts for the audit-intelligence agent. All Pydantic v2 models use
``extra="forbid"``. The agent REUSES the existing Governance, Audit,
Knowledge Graph, Compliance and Recommendation services — it does not
re-implement audit or compliance logic.

Public surface
--------------
* ``AuditStatus`` / ``AuditTaskKind``  — enums
* ``AuditViolation``        — a single policy / regulatory violation
* ``AuditEvidenceItem``     — a single evidence artifact
* ``AuditLineageNode``      — a node in a decision-lineage DAG
* ``AuditAgentRequest``     — payload to invoke the audit agent
* ``AuditAgentResult``      — final output of the audit agent
* ``AuditAgentHealth``      — health snapshot
* ``AuditMetricsSummary``   — aggregate audit-agent metrics
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────────────


class AuditStatus(str, Enum):
    """Overall compliance / audit verdict."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    UNKNOWN = "unknown"
    INCONCLUSIVE = "inconclusive"


class AuditTaskKind(str, Enum):
    """The kinds of audit task the agent can perform."""

    COMPLIANCE_VERIFICATION = "compliance_verification"
    AUDIT_TRAIL_ANALYSIS = "audit_trail_analysis"
    EVIDENCE_COLLECTION = "evidence_collection"
    POLICY_VERIFICATION = "policy_verification"
    GOVERNANCE_VALIDATION = "governance_validation"
    REGULATORY_REPORTING = "regulatory_reporting"
    LINEAGE_ANALYSIS = "lineage_analysis"


class AuditViolationSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Models ────────────────────────────────────────────────────────────


class AuditViolation(BaseModel):
    """A single compliance / governance violation detected."""

    model_config = ConfigDict(extra="forbid")

    violation_id: str = Field(default_factory=lambda: f"avl-{secrets.token_hex(4)}")
    title: str
    description: str = ""
    severity: AuditViolationSeverity = AuditViolationSeverity.MEDIUM
    source: str = ""  # "policy" | "regulation" | "governance" | "audit"
    policy_id: str = ""
    citation_ids: List[str] = Field(default_factory=list)
    remediation: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditEvidenceItem(BaseModel):
    """A single evidence artifact collected by the agent."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"evi-{secrets.token_hex(4)}")
    title: str
    evidence_kind: str = (
        "document"  # "document" | "policy" | "rule" | "record" | "kg_node"
    )
    source: str = ""
    content_hash: str = ""
    citation_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditLineageNode(BaseModel):
    """A node in a decision-lineage DAG."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(default_factory=lambda: f"lin-{secrets.token_hex(4)}")
    kind: str  # "audit_record" | "governance_decision" | "recommendation" | "policy"
    label: str
    subject_id: str = ""
    actor: str = ""
    timestamp: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditAgentRequest(BaseModel):
    """Payload to invoke the audit agent."""

    model_config = ConfigDict(extra="forbid")

    task_kind: AuditTaskKind = AuditTaskKind.COMPLIANCE_VERIFICATION
    query: str = Field(..., min_length=3, max_length=2000)
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    subject_id: str = ""  # entity the audit is performed against
    include_evidence: bool = True
    include_lineage: bool = True
    max_violations: int = Field(50, ge=1, le=500)
    max_evidence: int = Field(50, ge=0, le=500)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditAgentResult(BaseModel):
    """Final structured output of the audit agent."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"ares-{uuid.uuid4().hex[:12]}")
    agent: str = "audit"
    agent_id: str = ""
    task_kind: AuditTaskKind
    query: str
    audit_status: AuditStatus = AuditStatus.UNKNOWN
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    summary: str = ""
    violations: List[AuditViolation] = Field(default_factory=list)
    evidence: List[AuditEvidenceItem] = Field(default_factory=list)
    lineage: List[AuditLineageNode] = Field(default_factory=list)
    policies_evaluated: List[Dict[str, Any]] = Field(default_factory=list)
    chain_verified: Optional[bool] = None
    chain_break_at: str = ""
    affected_areas: List[str] = Field(default_factory=list)
    recommendation_ids: List[str] = Field(default_factory=list)
    audit_record_ids: List[str] = Field(default_factory=list)
    decision_ids: List[str] = Field(default_factory=list)
    report_markdown: str = ""
    duration_ms: float = 0.0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditAgentHealth(BaseModel):
    """Health snapshot of the audit agent."""

    model_config = ConfigDict(extra="forbid")

    agent: str = "audit"
    healthy: bool = True
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    last_invocation_at: Optional[float] = None
    last_error: str = ""


class AuditMetricsSummary(BaseModel):
    """Process-wide audit-agent metrics."""

    model_config = ConfigDict(extra="forbid")

    total_invocations: int = 0
    total_successful: int = 0
    total_failed: int = 0
    by_task_kind: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    total_violations: int = 0
    total_evidence: int = 0
    total_lineage_nodes: int = 0
    chain_verifications: int = 0
    chain_failures: int = 0
    average_confidence: float = 0.0
    average_duration_ms: float = 0.0
    last_reset_at: float = Field(default_factory=time.time)


__all__ = [
    "AuditStatus",
    "AuditTaskKind",
    "AuditViolationSeverity",
    "AuditViolation",
    "AuditEvidenceItem",
    "AuditLineageNode",
    "AuditAgentRequest",
    "AuditAgentResult",
    "AuditAgentHealth",
    "AuditMetricsSummary",
]
