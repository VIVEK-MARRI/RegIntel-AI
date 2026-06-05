"""Module 7.4 — Regulatory Impact Analysis schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────


class ImpactLevel(str, Enum):
    """Coarse-grained impact rating used for routing and dashboards."""

    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImpactDimension(str, Enum):
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    COMPLIANCE = "compliance"
    TECHNOLOGY = "technology"
    LEGAL = "legal"
    REPUTATIONAL = "reputational"
    STRATEGIC = "strategic"


class EntityType(str, Enum):
    """Kinds of regulated entities the platform can identify."""

    BANK = "bank"
    NBFC = "nbfc"
    INSURER = "insurer"
    PENSION_FUND = "pension_fund"
    AMC = "amc"
    BROKER_DEALER = "broker_dealer"
    FINTECH = "fintech"
    CUSTOMER = "customer"
    INTERMEDIARY = "intermediary"
    OTHER = "other"


class ActionPriority(str, Enum):
    P0 = "P0"  # immediate
    P1 = "P1"  # within 1 week
    P2 = "P2"  # within 1 month
    P3 = "P3"  # within 1 quarter


# ─── Sub-models ───────────────────────────────────────────────────────


class AffectedEntity(BaseModel):
    """An entity (organisation / person / system) impacted by the change."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    name: str = Field(..., min_length=1, max_length=200)
    rationale: str = Field(..., min_length=1)
    exposure_score: float = Field(0.0, ge=0.0, le=1.0)


class RequiredAction(BaseModel):
    """A concrete remediation / implementation step."""

    model_config = ConfigDict(extra="forbid")

    priority: ActionPriority
    action: str = Field(..., min_length=1, max_length=500)
    deadline: Optional[datetime] = None
    owner: Optional[str] = None
    rationale: str = Field("", max_length=1000)


class BusinessImpact(BaseModel):
    """Per-dimension impact scoring."""

    model_config = ConfigDict(extra="forbid")

    dimension: ImpactDimension
    score: float = Field(0.0, ge=0.0, le=1.0)
    description: str = Field("", max_length=1000)


class ComplianceImpact(BaseModel):
    """Compliance-side impact: obligations affected, evidence required."""

    model_config = ConfigDict(extra="forbid")

    obligations_affected: List[str] = Field(default_factory=list)
    deadline: Optional[datetime] = None
    evidence_requirements: List[str] = Field(default_factory=list)
    penalty_exposure: str = ""


class ExecutiveSummary(BaseModel):
    """A short, decision-grade summary of the impact report."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    key_points: List[str] = Field(default_factory=list, max_length=10)
    recommendation: str = ""


# ─── Report ──────────────────────────────────────────────────────────


class ImpactReport(BaseModel):
    """The top-level impact analysis output."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: f"imp-{_randhex(12)}")
    diff_id: str = Field(..., min_length=1)
    document_id: Optional[str] = None
    source: Optional[str] = None
    impact_level: ImpactLevel
    impact_score: float = Field(0.0, ge=0.0, le=1.0)
    affected_entities: List[AffectedEntity] = Field(default_factory=list)
    required_actions: List[RequiredAction] = Field(default_factory=list)
    business_impacts: List[BusinessImpact] = Field(default_factory=list)
    compliance_impact: Optional[ComplianceImpact] = None
    executive_summary: Optional[ExecutiveSummary] = None
    rationale: str = ""
    generated_at: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Request / Response ──────────────────────────────────────────────


class ImpactAnalysisRequest(BaseModel):
    """Input to the impact analysis service.

    Either ``diff_id`` (look up an existing diff) or ``diff`` (inline)
    must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    diff_id: Optional[str] = None
    diff: Optional[Dict[str, Any]] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("diff_id", "diff")
    @classmethod
    def _at_least_one(cls, v, info):  # type: ignore[no-untyped-def]
        return v


class ImpactAnalysisResult(BaseModel):
    """Wrapper returned by the analyse endpoint."""

    model_config = ConfigDict(extra="forbid")

    report: ImpactReport
    has_impact: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Filters / list / stats ──────────────────────────────────────────


class ImpactFilter(BaseModel):
    """Query filter for stored impact reports."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    source: Optional[str] = None
    min_level: Optional[ImpactLevel] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedImpacts(BaseModel):
    """Page of impact reports."""

    model_config = ConfigDict(extra="forbid")

    items: List[ImpactReport] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class ImpactAnalysisStats(BaseModel):
    """Aggregated impact analysis statistics."""

    model_config = ConfigDict(extra="forbid")

    total_reports: int = 0
    critical_impact: int = 0
    high_impact: int = 0
    medium_impact: int = 0
    low_impact: int = 0
    negligible_impact: int = 0
    average_impact_score: float = 0.0
    affected_entities_total: int = 0
    actions_recommended_total: int = 0
    by_source: Dict[str, int] = Field(default_factory=dict)
    by_level: Dict[str, int] = Field(default_factory=dict)


# ─── Helpers ──────────────────────────────────────────────────────────


def _randhex(n: int) -> str:
    import secrets

    return secrets.token_hex(n // 2)
