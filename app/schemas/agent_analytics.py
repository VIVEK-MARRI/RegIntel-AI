"""Module 9.9 — Agent Analytics Platform schemas.

Contracts for the multi-agent analytics layer. All Pydantic v2 models
use ``extra="forbid"``. The platform REUSES the M9 observability
primitives (per-agent / per-collaboration counters) and the M9.8
orchestration service for execution data.

Public surface
--------------
* ``LeaderboardEntry``            — ranked agent entry
* ``AgentPerformance``            — per-agent performance record
* ``AgentLatencyPoint``           — single latency observation
* ``LatencyDistribution``         — aggregated latency stats
* ``CollaborationStats``          — collaboration-pair summary
* ``HealthSummary``               — ecosystem health overview
* ``CostEstimate``                — cost per agent / execution
* ``AgentUsageCount``             — usage counter
* ``AgentAnalyticsOverview``      — top-level overview payload
* ``ExecutionSummary``            — single execution summary
* ``ForecastAccuracy``            — forecast accuracy record
* ``RecommendationAccuracy``      — recommendation accuracy record
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ───────────────────────────────────────────────────────────


class HealthLevel(str, Enum):
    """Coarse health classification for an agent / the ecosystem."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ─── Core analytics models ──────────────────────────────────────────


class AgentPerformance(BaseModel):
    """Per-agent performance record."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    success_rate: float = 0.0
    average_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    average_confidence: float = 0.0
    total_evidence_shared: int = 0
    last_invocation_at: Optional[float] = None
    last_error: str = ""
    health: HealthLevel = HealthLevel.UNKNOWN


class AgentLatencyPoint(BaseModel):
    """A single latency observation."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    duration_ms: float
    status: str
    timestamp: float = Field(default_factory=time.time)


class LatencyDistribution(BaseModel):
    """Aggregated latency statistics."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    count: int = 0
    average_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0


class LeaderboardEntry(BaseModel):
    """A single entry in the agent leaderboard."""

    model_config = ConfigDict(extra="forbid")

    rank: int = 0
    agent_name: str
    score: float = 0.0
    success_rate: float = 0.0
    average_confidence: float = 0.0
    total_invocations: int = 0
    average_duration_ms: float = 0.0


class CollaborationStats(BaseModel):
    """Statistics for a single (from_agent → to_agent) collaboration pair."""

    model_config = ConfigDict(extra="forbid")

    from_agent: str
    to_agent: str
    count: int = 0
    average_duration_ms: float = 0.0
    evidence_items_shared: int = 0


class HealthSummary(BaseModel):
    """Ecosystem health overview."""

    model_config = ConfigDict(extra="forbid")

    total_agents: int = 0
    healthy_agents: int = 0
    degraded_agents: int = 0
    unhealthy_agents: int = 0
    unknown_agents: int = 0
    overall_health: HealthLevel = HealthLevel.UNKNOWN
    agents: List[AgentPerformance] = Field(default_factory=list)
    notes: str = ""


class CostEstimate(BaseModel):
    """Cost estimate for a single agent or the whole platform."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = ""  # "" = platform total
    invocations: int = 0
    tokens_used: int = 0
    cost_units: float = 0.0
    currency: str = "USD"
    cost_per_invocation: float = 0.0
    notes: str = ""


class AgentUsageCount(BaseModel):
    """A usage counter (invocations or minutes) for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    invocations: int = 0
    successful: int = 0
    failed: int = 0


class ExecutionSummary(BaseModel):
    """A summary of a single orchestration execution."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(
        default_factory=lambda: f"exec-{uuid.uuid4().hex[:12]}"
    )
    query: str = ""
    status: str = "succeeded"
    mode: str = "sequential"
    agents_used: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    final_confidence: float = 0.0
    consensus_score: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class ForecastAccuracy(BaseModel):
    """Forecast accuracy record."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    predictions: int = 0
    correct: int = 0
    accuracy: float = 0.0
    average_error: float = 0.0
    notes: str = ""


class RecommendationAccuracy(BaseModel):
    """Recommendation accuracy record."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    generated: int = 0
    accepted: int = 0
    rejected: int = 0
    acceptance_rate: float = 0.0
    notes: str = ""


class AgentAnalyticsOverview(BaseModel):
    """Top-level overview payload for the agent ecosystem."""

    model_config = ConfigDict(extra="forbid")

    total_agents: int = 0
    total_invocations: int = 0
    success_rate: float = 0.0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    total_collaborations: int = 0
    total_cost_units: float = 0.0
    health: HealthSummary = Field(default_factory=HealthSummary)
    leaderboard: List[LeaderboardEntry] = Field(default_factory=list)
    collaborations: List[CollaborationStats] = Field(
        default_factory=list
    )
    recent_executions: List[ExecutionSummary] = Field(
        default_factory=list
    )
    forecast_accuracy: List[ForecastAccuracy] = Field(
        default_factory=list
    )
    recommendation_accuracy: List[RecommendationAccuracy] = Field(
        default_factory=list
    )
    cost: CostEstimate = Field(default_factory=CostEstimate)
    generated_at: float = Field(default_factory=time.time)


__all__ = [
    "HealthLevel",
    "AgentPerformance",
    "AgentLatencyPoint",
    "LatencyDistribution",
    "LeaderboardEntry",
    "CollaborationStats",
    "HealthSummary",
    "CostEstimate",
    "AgentUsageCount",
    "ExecutionSummary",
    "ForecastAccuracy",
    "RecommendationAccuracy",
    "AgentAnalyticsOverview",
]
