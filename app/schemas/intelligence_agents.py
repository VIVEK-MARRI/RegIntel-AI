"""Module 9.4-9.6 — Intelligence Agent Layer schemas.

Specialised agents (Research, Compliance, Risk) that build on top of the
generic Module 9 multi-agent framework. These are *domain-specialised*
agents that REUSE the existing platform services (research, knowledge
graph, compliance risk, recommendations, forecasting, governance,
monitoring, impact analysis).

Public surface
--------------
* ``ResearchMode`` / ``ResearchFinding`` / ``ResearchPlanStep`` /
  ``ResearchAgentResult`` / ``ResearchAgentRequest`` / ``ResearchAgentHealth``
* ``ComplianceObligation`` / ``ComplianceGapDetail`` / ``ComplianceActionItem`` /
  ``ComplianceAgentResult`` / ``ComplianceAgentRequest`` /
  ``ComplianceAgentHealth``
* ``ScenarioType`` / ``RiskScenario`` / ``RiskProjection`` /
  ``RiskAgentResult`` / ``RiskAgentRequest`` / ``RiskAgentHealth``
* ``AgentCollaboration`` / ``IntelligenceAgentMetrics`` / ``AgentMetricsSummary``
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Research Agent (Module 9.4) ────────────────────────────────────────


class ResearchMode(str, Enum):
    """Kinds of research the agent can perform."""

    MULTI_HOP = "multi_hop"
    CROSS_DOCUMENT = "cross_document"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    TIMELINE = "timeline"
    COMPARATIVE = "comparative"
    TREND = "trend"
    HISTORICAL = "historical"
    GENERAL = "general"


class ResearchPlanStep(BaseModel):
    """A single research step executed by the research agent."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: f"rstep-{secrets.token_hex(4)}")
    action: str  # "plan" | "retrieve" | "compare" | "reason" | "summarize"
    description: str
    capability: str = "retrieval"  # mapped to CapabilityKind
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""


class ResearchFinding(BaseModel):
    """A single structured finding produced by the research agent."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(default_factory=lambda: f"find-{secrets.token_hex(4)}")
    statement: str
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    sources: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchAgentRequest(BaseModel):
    """Request payload to run the research agent."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=2000)
    mode: ResearchMode = ResearchMode.GENERAL
    context: Dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(5, ge=1, le=20)
    max_steps: int = Field(8, ge=1, le=20)
    document_ids: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    start_date: Optional[float] = None
    end_date: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchAgentResult(BaseModel):
    """The structured output of the research agent."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"rres-{uuid.uuid4().hex[:12]}")
    agent: str = "research"
    agent_id: str = ""
    query: str
    mode: ResearchMode
    summary: str
    findings: List[ResearchFinding] = Field(default_factory=list)
    plan: List[ResearchPlanStep] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    knowledge_graph_insights: List[Dict[str, Any]] = Field(default_factory=list)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    duration_ms: float = 0.0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchAgentHealth(BaseModel):
    """Health snapshot of the research agent."""

    model_config = ConfigDict(extra="forbid")

    agent: str = "research"
    healthy: bool = True
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    last_invocation_at: Optional[float] = None
    last_error: str = ""


# ─── Compliance Agent (Module 9.5) ──────────────────────────────────────


class ComplianceObligationStatus(str, Enum):
    PENDING = "pending"
    MAPPED = "mapped"
    IN_PROGRESS = "in_progress"
    SATISFIED = "satisfied"
    AT_RISK = "at_risk"
    NON_COMPLIANT = "non_compliant"


class ComplianceObligation(BaseModel):
    """A regulatory obligation the agent has identified."""

    model_config = ConfigDict(extra="forbid")

    obligation_id: str = Field(default_factory=lambda: f"obl-{secrets.token_hex(4)}")
    title: str
    source: str = ""  # regulator / circular / policy
    description: str = ""
    status: ComplianceObligationStatus = ComplianceObligationStatus.PENDING
    affected_areas: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)
    due_date: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComplianceGapDetail(BaseModel):
    """A compliance gap surfaced by the agent."""

    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(default_factory=lambda: f"gap-{secrets.token_hex(4)}")
    title: str
    description: str
    risk_level: str = "medium"  # mapped to RiskLevel values
    affected_areas: List[str] = Field(default_factory=list)
    root_cause: str = ""
    citation_ids: List[str] = Field(default_factory=list)
    related_obligation_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComplianceActionItem(BaseModel):
    """A remediation action produced by the compliance agent."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(default_factory=lambda: f"cait-{secrets.token_hex(4)}")
    title: str
    description: str
    priority: str = "medium"
    affected_areas: List[str] = Field(default_factory=list)
    target_completion_days: int = Field(30, ge=0, le=365)
    addresses_gap_ids: List[str] = Field(default_factory=list)
    recommendation_id: str = ""
    citation_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComplianceAgentRequest(BaseModel):
    """Request payload to run the compliance agent."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=2000)
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    focus_areas: List[str] = Field(default_factory=list)
    max_gaps: int = Field(20, ge=1, le=100)
    include_recommendations: bool = True
    include_obligations: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComplianceAgentResult(BaseModel):
    """The structured output of the compliance agent."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"cres-{uuid.uuid4().hex[:12]}")
    agent: str = "compliance"
    agent_id: str = ""
    query: str
    summary: str
    risk_level: str = "medium"
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    obligations: List[ComplianceObligation] = Field(default_factory=list)
    gaps: List[ComplianceGapDetail] = Field(default_factory=list)
    actions: List[ComplianceActionItem] = Field(default_factory=list)
    policy_evaluations: List[Dict[str, Any]] = Field(default_factory=list)
    affected_areas: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)
    recommendation_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    duration_ms: float = 0.0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComplianceAgentHealth(BaseModel):
    """Health snapshot of the compliance agent."""

    model_config = ConfigDict(extra="forbid")

    agent: str = "compliance"
    healthy: bool = True
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    last_invocation_at: Optional[float] = None
    last_error: str = ""


# ─── Risk Intelligence Agent (Module 9.6) ──────────────────────────────


class RiskScenarioKind(str, Enum):
    BASELINE = "baseline"
    BEST_CASE = "best_case"
    WORST_CASE = "worst_case"
    STRESS = "stress"
    TAIL_RISK = "tail_risk"


class RiskScenario(BaseModel):
    """A scenario evaluated by the risk agent."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(default_factory=lambda: f"scn-{secrets.token_hex(4)}")
    name: str
    kind: RiskScenarioKind = RiskScenarioKind.BASELINE
    description: str = ""
    predicted_score: float = Field(0.5, ge=0.0, le=1.0)
    predicted_level: str = "medium"
    adjustments: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RiskProjection(BaseModel):
    """A forward-looking projection point."""

    model_config = ConfigDict(extra="forbid")

    horizon_days: int = Field(ge=1, le=365)
    predicted_score: float = Field(0.5, ge=0.0, le=1.0)
    lower_bound: float = Field(0.0, ge=0.0, le=1.0)
    upper_bound: float = Field(1.0, ge=0.0, le=1.0)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    method: str = "linear_regression"


class RiskAgentRequest(BaseModel):
    """Request payload to run the risk intelligence agent."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=2000)
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    horizon_days: int = Field(90, ge=1, le=365)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    scenario_kinds: List[RiskScenarioKind] = Field(
        default_factory=lambda: [
            RiskScenarioKind.BEST_CASE,
            RiskScenarioKind.BASELINE,
            RiskScenarioKind.WORST_CASE,
        ]
    )
    include_scenarios: bool = True
    include_recommendations: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RiskAgentResult(BaseModel):
    """The structured output of the risk agent."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: f"riskres-{uuid.uuid4().hex[:12]}")
    agent: str = "risk"
    agent_id: str = ""
    query: str
    summary: str
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: str = "medium"
    forecast: List[RiskProjection] = Field(default_factory=list)
    scenarios: List[RiskScenario] = Field(default_factory=list)
    trends: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_actions: List[Dict[str, Any]] = Field(default_factory=list)
    drift_detected: bool = False
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    duration_ms: float = 0.0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RiskAgentHealth(BaseModel):
    """Health snapshot of the risk agent."""

    model_config = ConfigDict(extra="forbid")

    agent: str = "risk"
    healthy: bool = True
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    last_invocation_at: Optional[float] = None
    last_error: str = ""


# ─── Cross-agent collaboration + metrics ────────────────────────────────


class AgentCollaboration(BaseModel):
    """Record of an agent-to-agent call inside a single run."""

    model_config = ConfigDict(extra="forbid")

    collaboration_id: str = Field(
        default_factory=lambda: f"collab-{secrets.token_hex(4)}"
    )
    from_agent: str  # "research" | "compliance" | "risk"
    to_agent: str
    request_kind: str
    evidence_keys: List[str] = Field(default_factory=list)
    result_keys: List[str] = Field(default_factory=list)
    shared_context_keys: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    created_at: float = Field(default_factory=time.time)


class AgentMetricsSummary(BaseModel):
    """Per-agent metric summary."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    total_invocations: int = 0
    successful: int = 0
    failed: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    last_invocation_at: Optional[float] = None


class IntelligenceAgentMetrics(BaseModel):
    """Aggregate metrics across all three intelligence agents."""

    model_config = ConfigDict(extra="forbid")

    total_invocations: int = 0
    total_successful: int = 0
    total_failed: int = 0
    total_collaborations: int = 0
    research: AgentMetricsSummary = Field(
        default_factory=lambda: AgentMetricsSummary(agent="research")
    )
    compliance: AgentMetricsSummary = Field(
        default_factory=lambda: AgentMetricsSummary(agent="compliance")
    )
    risk: AgentMetricsSummary = Field(
        default_factory=lambda: AgentMetricsSummary(agent="risk")
    )
    by_mode: Dict[str, int] = Field(default_factory=dict)
    by_scenario_kind: Dict[str, int] = Field(default_factory=dict)
    average_confidence: float = 0.0
    last_reset_at: float = Field(default_factory=time.time)


__all__ = [
    # Research agent
    "ResearchMode",
    "ResearchPlanStep",
    "ResearchFinding",
    "ResearchAgentRequest",
    "ResearchAgentResult",
    "ResearchAgentHealth",
    # Compliance agent
    "ComplianceObligationStatus",
    "ComplianceObligation",
    "ComplianceGapDetail",
    "ComplianceActionItem",
    "ComplianceAgentRequest",
    "ComplianceAgentResult",
    "ComplianceAgentHealth",
    # Risk agent
    "RiskScenarioKind",
    "RiskScenario",
    "RiskProjection",
    "RiskAgentRequest",
    "RiskAgentResult",
    "RiskAgentHealth",
    # Collaboration
    "AgentCollaboration",
    "AgentMetricsSummary",
    "IntelligenceAgentMetrics",
]
