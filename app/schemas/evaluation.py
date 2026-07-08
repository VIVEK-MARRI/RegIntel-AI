from __future__ import annotations

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class GoldenEvaluationItem(BaseModel):
    """Schema representing a single evaluation item with ground truth."""

    query: str = Field(..., description="The query string to run.")
    expected_chunk_ids: List[str] = Field(
        default_factory=list, description="List of expected chunk UUID strings."
    )
    expected_sections: List[str] = Field(
        default_factory=list,
        description="List of expected section titles/keywords as fallback matching criteria.",
    )


class QueryEvaluationResult(BaseModel):
    """Evaluation metrics for a single query."""

    query: str = Field(..., description="The evaluated query.")
    retrieved_ids: List[str] = Field(
        default_factory=list, description="IDs of top chunks returned."
    )
    precision_at_5: float = Field(..., description="Precision at K=5.")
    precision_at_10: float = Field(..., description="Precision at K=10.")
    recall_at_5: float = Field(..., description="Recall at K=5.")
    recall_at_10: float = Field(..., description="Recall at K=10.")
    mrr: float = Field(..., description="Reciprocal rank.")
    hit_at_5: bool = Field(
        ..., description="True if at least one expected match was in top 5."
    )
    hit_at_10: bool = Field(
        ..., description="True if at least one expected match was in top 10."
    )


class BenchmarkSummaryMetrics(BaseModel):
    """Summary aggregated metrics across all queries."""

    mean_precision_at_5: float = Field(..., description="Average precision at 5.")
    mean_precision_at_10: float = Field(..., description="Average precision at 10.")
    mean_recall_at_5: float = Field(..., description="Average recall at 5.")
    mean_recall_at_10: float = Field(..., description="Average recall at 10.")
    mrr: float = Field(..., description="Mean Reciprocal Rank (MRR).")
    hit_rate_at_5: float = Field(..., description="Hit Rate at 5.")
    hit_rate_at_10: float = Field(..., description="Hit Rate at 10.")


class BenchmarkReport(BaseModel):
    """The final retrieval evaluation report containing metadata and results."""

    benchmark_id: str = Field(..., description="Unique ID for this benchmark run.")
    timestamp: str = Field(..., description="Timestamp of execution.")
    embedding_model: str = Field(..., description="The model evaluated.")
    embedding_dimension: int = Field(..., description="The model vector size.")
    distance_metric: str = Field(
        ..., description="Metric used for retrieval (e.g. cosine)."
    )
    fallback_mode_active: bool = Field(
        ..., description="Whether database fallback mode was active."
    )
    metrics: BenchmarkSummaryMetrics = Field(
        ..., description="Aggregated quality metrics."
    )
    query_results: List[QueryEvaluationResult] = Field(
        default_factory=list, description="Detail query results."
    )
    duration_ms: float = Field(
        ..., description="Total execution duration in milliseconds."
    )


# ─── Module 5.7 — Answer Evaluation Framework ──────────────────────────────

import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from enum import Enum  # noqa: E402
from typing import Any  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from app.schemas.orchestrator import FinalAnswerResponse  # noqa: E402


class EvaluationMetric(str, Enum):
    """The set of metrics the framework computes."""

    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCE = "answer_relevance"
    CITATION_ACCURACY = "citation_accuracy"
    SOURCE_ATTRIBUTION_ACCURACY = "source_attribution_accuracy"
    COMPLETENESS = "completeness"
    GROUNDEDNESS = "groundedness"
    HALLUCINATION_RATE = "hallucination_rate"
    EVIDENCE_COVERAGE = "evidence_coverage"


class EvaluationStrategy(str, Enum):
    """Comparison strategy for the benchmark runner."""

    BASELINE = "baseline"
    CANDIDATE = "candidate"


class MetricScore(BaseModel):
    """A single metric's value plus a short note."""

    model_config = ConfigDict(extra="forbid")

    metric: EvaluationMetric
    score: float = Field(..., ge=0.0, le=1.0)
    note: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class AnswerEvaluationResult(BaseModel):
    """Per-response evaluation result."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    strategy: EvaluationStrategy = EvaluationStrategy.CANDIDATE
    scores: List[MetricScore] = Field(default_factory=list)
    aggregate_score: float = Field(0.0, ge=0.0, le=1.0)
    hallucination_rate: float = Field(0.0, ge=0.0, le=1.0)
    notes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AnswerEvaluationReport(BaseModel):
    """Multi-response aggregate report."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cases: int = Field(0, ge=0)
    results: List[AnswerEvaluationResult] = Field(default_factory=list)
    aggregate_metrics: Dict[str, float] = Field(default_factory=dict)
    average_aggregate_score: float = Field(0.0, ge=0.0, le=1.0)
    average_hallucination_rate: float = Field(0.0, ge=0.0, le=1.0)
    regression_detected: bool = False
    regression_delta: float = 0.0
    notes: List[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    """Single-response evaluation request."""

    model_config = ConfigDict(extra="forbid")

    response: FinalAnswerResponse
    query: str = Field(..., min_length=1, max_length=2048)
    chunks: List[Dict[str, Any]] = Field(default_factory=list)
    strategy: EvaluationStrategy = EvaluationStrategy.CANDIDATE
    metrics: Optional[List[EvaluationMetric]] = None


class EvaluationResponse(BaseModel):
    """Single-response evaluation response."""

    model_config = ConfigDict(extra="forbid")

    query: str
    result: AnswerEvaluationResult
