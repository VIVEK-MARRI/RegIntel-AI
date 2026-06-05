"""Module 5.8 — Answer Analytics Platform schemas.

The analytics layer is the *production monitor* for the full Milestone
5 pipeline.  It records every orchestrator response, computes running
aggregates (faithfulness distribution, hallucination rate, citation
coverage, attribution coverage, confidence distribution, latency, cost)
and exposes them via the dashboard APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class AnalyticsWindow(str, Enum):
    """Time window for aggregation."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    ALL = "all"


class HealthStatus(str, Enum):
    """Health probe status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ─── Event record ─────────────────────────────────────────────────────────


class AnswerAnalyticsEvent(BaseModel):
    """A single orchestrator-response record stored by the platform."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str = Field(..., description="The orchestrator request_id.")
    query: str = Field(..., min_length=1)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_level: str
    faithfulness_score: float = Field(..., ge=0.0, le=1.0)
    hallucination_detected: bool
    hallucination_risk_level: str
    attribution_coverage_ratio: float = Field(..., ge=0.0, le=1.0)
    citation_coverage_ratio: float = Field(0.0, ge=0.0, le=1.0)
    source_count: int = Field(0, ge=0)
    latency_ms: float = Field(0.0, ge=0.0)
    total_tokens: int = Field(0, ge=0)
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    step_results: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ─── Aggregates ───────────────────────────────────────────────────────────


class ConfidenceDistribution(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0


class FaithfulnessDistribution(BaseModel):
    """Bucketed faithfulness distribution (4 buckets of 0.25 width)."""

    bucket_0_25: int = 0  # < 0.25
    bucket_25_50: int = 0
    bucket_50_75: int = 0
    bucket_75_100: int = 0  # >= 0.75


class HallucinationBuckets(BaseModel):
    """Counts of events that detected / didn't detect hallucination."""

    detected: int = 0
    not_detected: int = 0


class LatencyStats(BaseModel):
    """Latency percentiles in milliseconds."""

    count: int = 0
    average_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0


class TokenUsageStats(BaseModel):
    """Token usage and model usage counts."""

    total_tokens: int = 0
    average_tokens: float = 0.0
    models: Dict[str, int] = Field(default_factory=dict)
    providers: Dict[str, int] = Field(default_factory=dict)


class AnswerAnalyticsSnapshot(BaseModel):
    """Point-in-time aggregate of all recorded events."""

    model_config = ConfigDict(extra="forbid")

    window: AnalyticsWindow = AnalyticsWindow.ALL
    total_responses: int = 0
    average_faithfulness: float = 0.0
    average_confidence: float = 0.0
    average_attribution_coverage: float = 0.0
    average_citation_coverage: float = 0.0
    hallucination_rate: float = 0.0
    answer_quality: float = 0.0
    confidence_distribution: ConfidenceDistribution = Field(default_factory=ConfidenceDistribution)
    faithfulness_distribution: FaithfulnessDistribution = Field(
        default_factory=FaithfulnessDistribution
    )
    hallucination_buckets: HallucinationBuckets = Field(default_factory=HallucinationBuckets)
    latency: LatencyStats = Field(default_factory=LatencyStats)
    token_usage: TokenUsageStats = Field(default_factory=TokenUsageStats)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Health ────────────────────────────────────────────────────────────────


class AnswerHealthReport(BaseModel):
    """Health probe for the analytics platform itself."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus = HealthStatus.HEALTHY
    total_responses: int = 0
    average_faithfulness: float = 0.0
    hallucination_rate: float = 0.0
    citation_coverage: float = 0.0
    average_latency_ms: float = 0.0
    degraded_reasons: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "AnalyticsWindow",
    "AnswerAnalyticsEvent",
    "AnswerAnalyticsSnapshot",
    "AnswerHealthReport",
    "ConfidenceDistribution",
    "FaithfulnessDistribution",
    "HallucinationBuckets",
    "HealthStatus",
    "LatencyStats",
    "TokenUsageStats",
]
