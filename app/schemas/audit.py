"""Module 8.7 — Audit & Compliance Platform contracts.

Pydantic v2 with ``extra="forbid"`` for all models. The Audit Platform
captures an *immutable, hash-chained* record of every meaningful action
in RegIntel AI and provides the building blocks for explainability,
end-to-end traceability and regulatory reporting.

Public surface
--------------
* ``AuditAction`` / ``AuditSeverity`` / ``ReportStatus`` — enums
* ``AuditRecord`` (hash-chained) / ``AuditEvidence``
* ``DecisionLineage`` / ``LineageNode`` / ``LineageEdge``
* ``ComplianceReport`` / ``ReportSection``
* ``AuditFilter`` / ``PaginatedAuditRecords`` / ``AuditStats``
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────────


class AuditAction(str, Enum):
    """The kinds of actions that generate audit records."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    POLICY_CHECK = "policy_check"
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    REPORT_GENERATE = "report_generate"
    CONFIG_CHANGE = "config_change"
    RBAC_GRANT = "rbac_grant"
    RBAC_REVOKE = "rbac_revoke"
    OTHER = "other"


class AuditSeverity(str, Enum):
    """Severity of an audit record (drives alerting + retention)."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReportStatus(str, Enum):
    """Lifecycle states for a compliance report."""

    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    ARCHIVED = "archived"


class ReportKind(str, Enum):
    """Kinds of compliance reports that can be produced."""

    REGULATORY_SUBMISSION = "regulatory_submission"
    INTERNAL_AUDIT = "internal_audit"
    POLICY_ATTESTATION = "policy_attestation"
    INCIDENT_SUMMARY = "incident_summary"
    EVIDENCE_BUNDLE = "evidence_bundle"
    CUSTOM = "custom"


class EvidenceKind(str, Enum):
    """What kind of evidence an :class:`AuditEvidence` represents."""

    DOCUMENT = "document"
    SCREENSHOT = "screenshot"
    LOG = "log"
    CITATION = "citation"
    DECISION = "decision"
    APPROVAL = "approval"
    POLICY = "policy"
    CONFIG = "config"
    OTHER = "other"


# ─── Audit records (hash-chained) ──────────────────────────────────


class AuditRecord(BaseModel):
    """An immutable audit record with a SHA-256 hash chain."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(
        default_factory=lambda: f"aud-{uuid.uuid4().hex[:12]}"
    )
    timestamp: float = Field(default_factory=time.time)
    actor: str = "system"
    actor_role: str = ""
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO
    subject_type: str = ""
    subject_id: str = ""
    description: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    source_module: str = ""
    # Hash chain fields
    prev_hash: str = ""
    record_hash: str = ""
    sequence: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditEvidence(BaseModel):
    """A piece of evidence attached to one or more audit records."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        default_factory=lambda: f"evd-{uuid.uuid4().hex[:12]}"
    )
    record_id: str = ""
    kind: EvidenceKind = EvidenceKind.OTHER
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    collected_by: str = "system"
    collected_at: float = Field(default_factory=time.time)
    source_uri: str = ""
    tags: List[str] = Field(default_factory=list)


# ─── Lineage / traceability ──────────────────────────────────────


class LineageNode(BaseModel):
    """A single node in a decision lineage DAG."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(
        default_factory=lambda: f"nde-{secrets.token_hex(4)}"
    )
    kind: str  # "decision" | "policy" | "evidence" | "review" | "workflow" | ...
    label: str
    ref_id: str = ""
    timestamp: float = Field(default_factory=time.time)
    parent_ids: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class LineageEdge(BaseModel):
    """A directed edge in a decision lineage DAG."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(
        default_factory=lambda: f"edg-{secrets.token_hex(4)}"
    )
    from_node: str
    to_node: str
    relation: str = "derived_from"
    description: str = ""


class DecisionLineage(BaseModel):
    """An end-to-end lineage DAG for a single decision."""

    model_config = ConfigDict(extra="forbid")

    lineage_id: str = Field(
        default_factory=lambda: f"lin-{uuid.uuid4().hex[:12]}"
    )
    root_decision_id: str = ""
    subject_type: str = ""
    subject_id: str = ""
    nodes: List[LineageNode] = Field(default_factory=list)
    edges: List[LineageEdge] = Field(default_factory=list)
    depth: int = 0
    node_count: int = 0
    edge_count: int = 0
    built_at: float = Field(default_factory=time.time)


# ─── Compliance reporting ────────────────────────────────────────


class ReportSection(BaseModel):
    """A single section within a compliance report."""

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(
        default_factory=lambda: f"sec-{secrets.token_hex(4)}"
    )
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    order: int = 0


class ComplianceReport(BaseModel):
    """A regulatory / internal compliance report."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(
        default_factory=lambda: f"rpt-{uuid.uuid4().hex[:12]}"
    )
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    kind: ReportKind = ReportKind.INTERNAL_AUDIT
    status: ReportStatus = ReportStatus.DRAFT
    regulator: str = ""
    period_start: float = 0.0
    period_end: float = 0.0
    generated_by: str = "system"
    generated_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    sections: List[ReportSection] = Field(default_factory=list)
    record_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    attestation: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Filter / pagination / stats ─────────────────────────────────


class AuditFilter(BaseModel):
    """Query filter for the audit log."""

    model_config = ConfigDict(extra="forbid")

    action: Optional[AuditAction] = None
    severity: Optional[AuditSeverity] = None
    actor: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    source_module: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    text_query: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedAuditRecords(BaseModel):
    """A page of audit records."""

    model_config = ConfigDict(extra="forbid")

    items: List[AuditRecord] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class AuditStats(BaseModel):
    """Aggregate metrics about audit activity."""

    model_config = ConfigDict(extra="forbid")

    total_records: int = 0
    by_action: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_actor: Dict[str, int] = Field(default_factory=dict)
    by_module: Dict[str, int] = Field(default_factory=dict)
    by_subject_type: Dict[str, int] = Field(default_factory=dict)
    chain_length: int = 0
    last_chain_hash: str = ""
    chain_integrity: bool = True
    last_record_at: Optional[float] = None
    oldest_record_at: Optional[float] = None


# ─── Request payloads ─────────────────────────────────────────────


class AuditRecordCreateRequest(BaseModel):
    """Request to create a new audit record."""

    model_config = ConfigDict(extra="forbid")

    actor: str = "system"
    actor_role: str = ""
    action: AuditAction
    severity: AuditSeverity = AuditSeverity.INFO
    subject_type: str = ""
    subject_id: str = ""
    description: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    source_module: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditEvidenceCreateRequest(BaseModel):
    """Request to attach evidence to an audit record."""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    kind: EvidenceKind = EvidenceKind.OTHER
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    collected_by: str = "system"
    source_uri: str = ""
    tags: List[str] = Field(default_factory=list)


class ComplianceReportCreateRequest(BaseModel):
    """Request to create / generate a compliance report."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    kind: ReportKind = ReportKind.INTERNAL_AUDIT
    regulator: str = ""
    period_start: float = 0.0
    period_end: float = 0.0
    generated_by: str = "system"
    section_titles: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AuditAction",
    "AuditSeverity",
    "ReportStatus",
    "ReportKind",
    "EvidenceKind",
    "AuditRecord",
    "AuditEvidence",
    "LineageNode",
    "LineageEdge",
    "DecisionLineage",
    "ReportSection",
    "ComplianceReport",
    "AuditFilter",
    "PaginatedAuditRecords",
    "AuditStats",
    "AuditRecordCreateRequest",
    "AuditEvidenceCreateRequest",
    "ComplianceReportCreateRequest",
]
