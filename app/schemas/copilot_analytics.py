"""Module 6.7 — Copilot Analytics schemas.

Aggregations of copilot activity: conversation count, length, memory
usage, query categories, follow-up rate, satisfaction, latency, cost,
and token usage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class AnalyticsWindow(str, Enum):
    """Time window for analytics aggregations."""

    LAST_HOUR = "last_hour"
    LAST_DAY = "last_day"
    LAST_WEEK = "last_week"
    LAST_MONTH = "last_month"
    ALL = "all"


class QueryCategory(str, Enum):
    """Top-level query category (mirrors Module 6.4 QueryType where useful)."""

    DEFINITION = "definition"
    FACTUAL = "factual"
    PROCEDURAL = "procedural"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    CHANGE = "change"
    CROSS_DOC = "cross_doc"
    MULTI_STEP = "multi_step"
    OTHER = "other"


# ─── Aggregations ──────────────────────────────────────────────────────────


class ConversationMetrics(BaseModel):
    """Per-conversation metrics."""

    model_config = ConfigDict(extra="forbid")

    total_conversations: int = 0
    active_conversations: int = 0
    archived_conversations: int = 0
    avg_messages_per_conversation: float = 0.0
    avg_conversation_length_tokens: float = 0.0
    multi_turn_conversations: int = 0
    multi_turn_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="multi_turn / total."
    )
    follow_up_rate: float = Field(
        0.0, ge=0.0, le=1.0, description="follow-up questions per session."
    )


class MemoryUsageMetrics(BaseModel):
    """Memory layer usage metrics."""

    model_config = ConfigDict(extra="forbid")

    total_memories: int = 0
    short_term: int = 0
    long_term: int = 0
    retrieval: int = 0
    pinned: int = 0
    avg_relevance_score: float = 0.0
    memory_used_in_requests: int = 0
    memory_used_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="Fraction of requests that used memory."
    )


class QueryCategoryMetrics(BaseModel):
    """Breakdown of queries by category."""

    model_config = ConfigDict(extra="forbid")

    by_category: Dict[QueryCategory, int] = Field(default_factory=dict)
    top_category: Optional[QueryCategory] = None


class LatencyMetrics(BaseModel):
    """Latency distribution."""

    model_config = ConfigDict(extra="forbid")

    count: int = 0
    average_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0


class CostMetrics(BaseModel):
    """Cost / token usage metrics."""

    model_config = ConfigDict(extra="forbid")

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    avg_tokens_per_request: float = 0.0


class AnswerQualityMetrics(BaseModel):
    """Answer quality + feedback trends."""

    model_config = ConfigDict(extra="forbid")

    avg_confidence: float = 0.0
    avg_faithfulness: float = 0.0
    hallucination_rate: float = 0.0
    avg_attribution_coverage: float = 0.0
    thumbs_up: int = 0
    thumbs_down: int = 0
    satisfaction_ratio: float = 0.0
    feedback_total: int = 0
    correction_count: int = 0
    hallucination_reports: int = 0


class CopilotMetrics(BaseModel):
    """Top-level copilot metrics for a time window."""

    model_config = ConfigDict(extra="forbid")

    window: AnalyticsWindow
    window_start: Optional[datetime] = None
    window_end: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = Field(0.0, ge=0.0, le=1.0)
    conversations: ConversationMetrics = Field(default_factory=ConversationMetrics)
    memory: MemoryUsageMetrics = Field(default_factory=MemoryUsageMetrics)
    categories: QueryCategoryMetrics = Field(default_factory=QueryCategoryMetrics)
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    cost: CostMetrics = Field(default_factory=CostMetrics)
    quality: AnswerQualityMetrics = Field(default_factory=AnswerQualityMetrics)


class UsageStats(BaseModel):
    """Lightweight usage snapshot (for the ``/usage`` endpoint)."""

    model_config = ConfigDict(extra="forbid")

    window: AnalyticsWindow
    total_requests: int = 0
    total_tokens: int = 0
    total_conversations: int = 0
    total_memories: int = 0
    avg_latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    feedback_total: int = 0
    satisfaction_ratio: float = 0.0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "AnalyticsWindow",
    "AnswerQualityMetrics",
    "ConversationMetrics",
    "CopilotMetrics",
    "CostMetrics",
    "LatencyMetrics",
    "MemoryUsageMetrics",
    "QueryCategory",
    "QueryCategoryMetrics",
    "UsageStats",
]
