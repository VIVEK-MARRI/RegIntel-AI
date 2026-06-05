"""Module 8.1 — Compliance Risk Intelligence schemas."""

from __future__ import annotations

import secrets
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskCategory(str, Enum):
    REGULATORY_EXPOSURE = "regulatory_exposure"
    COMPLIANCE_GAP = "compliance_gap"
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    REPUTATIONAL = "reputational"
    STRATEGIC = "strategic"
    TECHNOLOGY = "technology"
    LEGAL = "legal"


class AffectedArea(str, Enum):
    KYC = "kyc"
    AML = "aml"
    CAPITAL_ADEQUACY = "capital_adequacy"
    REPORTING = "reporting"
    CYBER_SECURITY = "cyber_security"
    DATA_PRIVACY = "data_privacy"
    OUTSOURCING = "outsourcing"
    RISK_MANAGEMENT = "risk_management"
    CUSTOMER_PROTECTION = "customer_protection"
    GOVERNANCE = "governance"
    FRAUD_PREVENTION = "fraud_prevention"
    OTHER = "other"


class RecommendedActionType(str, Enum):
    IMMEDIATE_REVIEW = "immediate_review"
    POLICY_UPDATE = "policy_update"
    PROCESS_CHANGE = "process_change"
    TRAINING = "training"
    REPORTING_UPDATE = "reporting_update"
    TECHNOLOGY_UPGRADE = "technology_upgrade"
    STAKEHOLDER_ESCALATION = "stakeholder_escalation"
    EXTERNAL_ADVISORY = "external_advisory"
    MONITORING_ENHANCEMENT = "monitoring_enhancement"
    DOCUMENTATION = "documentation"


# ─── Sub-models ───────────────────────────────────────────────────────


class RiskFactor(BaseModel):
    """A single input factor contributing to the risk score."""

    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(default_factory=lambda: f"fac-{secrets.token_hex(4)}")
    name: str
    category: RiskCategory
    weight: float = Field(1.0, ge=0.0, le=10.0)
    raw_value: float = 0.0
    contribution: float = 0.0
    explanation: str = ""
    source: str = ""


class AffectedAreaRecord(BaseModel):
    """A compliance area affected by the risk."""

    model_config = ConfigDict(extra="forbid")

    area: AffectedArea
    exposure_score: float = Field(0.0, ge=0.0, le=1.0)
    rationale: str = ""
    related_changes: int = 0


class RecommendedAction(BaseModel):
    """An action recommended to mitigate the risk."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        default_factory=lambda: f"act-{secrets.token_hex(4)}"
    )
    action_type: RecommendedActionType
    title: str
    description: str
    priority: RiskLevel
    rationale: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    estimated_effort_hours: float = 0.0


class ComplianceGap(BaseModel):
    """A detected compliance gap."""

    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(default_factory=lambda: f"gap-{secrets.token_hex(4)}")
    area: AffectedArea
    severity: RiskLevel
    description: str
    regulatory_basis: str = ""
    remediation_action_id: Optional[str] = None


class RiskExplanation(BaseModel):
    """An explainable breakdown of a risk score."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    top_factors: List[RiskFactor] = Field(default_factory=list, max_length=20)
    scoring_method: str = "weighted_aggregate"
    confidence: float = Field(0.5, ge=0.0, le=1.0)


# ─── Top-level risk report ───────────────────────────────────────────


class RiskAssessment(BaseModel):
    """A single compliance risk assessment."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(
        default_factory=lambda: f"rsk-{secrets.token_hex(6)}"
    )
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    source: str = "manual"
    risk_level: RiskLevel
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_categories: List[RiskCategory] = Field(default_factory=list)
    affected_areas: List[AffectedAreaRecord] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
    compliance_gaps: List[ComplianceGap] = Field(default_factory=list)
    explanation: RiskExplanation = Field(default_factory=RiskExplanation)
    regulatory_exposure: float = Field(0.0, ge=0.0, le=1.0)
    historical_risk_score: Optional[float] = None
    trend: str = "flat"
    generated_at: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Requests / Filters / Stats ─────────────────────────────────────


class RiskAssessmentRequest(BaseModel):
    """Request payload to generate a risk assessment."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    source: str = "manual"
    context: Dict[str, Any] = Field(default_factory=dict)


class RiskFilter(BaseModel):
    """Query filter for risk assessments."""

    model_config = ConfigDict(extra="forbid")

    risk_level: Optional[RiskLevel] = None
    category: Optional[RiskCategory] = None
    document_id: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedRiskAssessments(BaseModel):
    """Page of risk assessments."""

    model_config = ConfigDict(extra="forbid")

    items: List[RiskAssessment] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class RiskTrendPoint(BaseModel):
    """A single point on a risk trend series."""

    model_config = ConfigDict(extra="forbid")

    timestamp: float
    risk_score: float
    risk_level: RiskLevel


class RiskTrend(BaseModel):
    """A trend series of risk scores."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    source: Optional[str] = None
    points: List[RiskTrendPoint] = Field(default_factory=list)
    direction: str = "flat"
    delta: float = 0.0


class RiskStats(BaseModel):
    """Aggregate risk statistics."""

    model_config = ConfigDict(extra="forbid")

    total_assessments: int = 0
    critical_risks: int = 0
    high_risks: int = 0
    medium_risks: int = 0
    low_risks: int = 0
    average_risk_score: float = 0.0
    by_category: Dict[str, int] = Field(default_factory=dict)
    by_source: Dict[str, int] = Field(default_factory=dict)
    by_affected_area: Dict[str, int] = Field(default_factory=dict)
    total_recommended_actions: int = 0
    total_compliance_gaps: int = 0
    last_assessment_at: Optional[float] = None


__all__ = [
    "RiskLevel",
    "RiskCategory",
    "AffectedArea",
    "RecommendedActionType",
    "RiskFactor",
    "AffectedAreaRecord",
    "RecommendedAction",
    "ComplianceGap",
    "RiskExplanation",
    "RiskAssessment",
    "RiskAssessmentRequest",
    "RiskFilter",
    "PaginatedRiskAssessments",
    "RiskTrendPoint",
    "RiskTrend",
    "RiskStats",
]
