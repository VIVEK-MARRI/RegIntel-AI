"""Module 7.7 — Agentic Regulatory Research schemas."""

from __future__ import annotations

import secrets
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────


class ResearchKind(str, Enum):
    GENERAL = "general"
    MULTI_HOP = "multi_hop"
    CROSS_DOCUMENT = "cross_document"
    TIMELINE = "timeline"
    COMPARATIVE = "comparative"


class ResearchStepType(str, Enum):
    PLAN = "plan"
    RETRIEVE = "retrieve"
    COMPARE = "compare"
    REASON = "reason"
    SUMMARIZE = "summarize"


class ResearchStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CitationSource(str, Enum):
    MONITORING = "monitoring"
    INGESTION = "ingestion"
    CHANGE_DETECTION = "change_detection"
    IMPACT_ANALYSIS = "impact_analysis"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    SEARCH = "search"
    COPILOT = "copilot"


# ─── Sub-models ───────────────────────────────────────────────────────


class ResearchContext(BaseModel):
    """Optional context to bias retrieval / comparison."""

    model_config = ConfigDict(extra="forbid")

    sources: List[str] = Field(default_factory=list)
    document_ids: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    start_date: Optional[float] = None
    end_date: Optional[float] = None
    severity_filter: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchStep(BaseModel):
    """A single step in a research plan."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: f"step-{secrets.token_hex(6)}")
    step_type: ResearchStepType
    description: str
    status: ResearchStepStatus = ResearchStepStatus.PENDING
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0


class ResearchCitation(BaseModel):
    """A citation in the final research report."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(
        default_factory=lambda: f"cit-{secrets.token_hex(6)}"
    )
    source: CitationSource
    title: str
    reference: str
    url: Optional[str] = None
    score: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchPlan(BaseModel):
    """The research plan: ordered list of steps."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: f"plan-{secrets.token_hex(6)}")
    query: str
    kind: ResearchKind = ResearchKind.GENERAL
    steps: List[ResearchStep] = Field(default_factory=list)
    context: ResearchContext = Field(default_factory=ResearchContext)
    created_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchReport(BaseModel):
    """The final research output."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: f"rpt-{secrets.token_hex(6)}")
    plan_id: str
    query: str
    kind: ResearchKind
    summary: str
    key_findings: List[str] = Field(default_factory=list, max_length=20)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[ResearchCitation] = Field(default_factory=list)
    steps: List[ResearchStep] = Field(default_factory=list)
    generated_at: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Requests / Responses ─────────────────────────────────────────────


class ResearchRequest(BaseModel):
    """Request payload to run a research task."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=1000)
    kind: ResearchKind = ResearchKind.GENERAL
    context: ResearchContext = Field(default_factory=ResearchContext)
    max_steps: int = Field(8, ge=1, le=20)


class ResearchFilter(BaseModel):
    """Query filter for stored research reports."""

    model_config = ConfigDict(extra="forbid")

    kind: Optional[ResearchKind] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)


class PaginatedResearchReports(BaseModel):
    """Page of research reports."""

    model_config = ConfigDict(extra="forbid")

    items: List[ResearchReport] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_more: bool = False


class ResearchStats(BaseModel):
    """Aggregate research statistics."""

    model_config = ConfigDict(extra="forbid")

    total_reports: int = 0
    plans_generated: int = 0
    steps_total: int = 0
    average_steps_per_plan: float = 0.0
    average_duration_ms: float = 0.0
    by_kind: Dict[str, int] = Field(default_factory=dict)
    last_report_at: Optional[float] = None


__all__ = [
    "ResearchKind",
    "ResearchStepType",
    "ResearchStepStatus",
    "CitationSource",
    "ResearchContext",
    "ResearchStep",
    "ResearchCitation",
    "ResearchPlan",
    "ResearchReport",
    "ResearchRequest",
    "ResearchFilter",
    "PaginatedResearchReports",
    "ResearchStats",
]
