from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class GoldenEvaluationItem(BaseModel):
    """Schema representing a single evaluation item with ground truth."""
    query: str = Field(..., description="The query string to run.")
    expected_chunk_ids: List[str] = Field(
        default_factory=list, 
        description="List of expected chunk UUID strings."
    )
    expected_sections: List[str] = Field(
        default_factory=list, 
        description="List of expected section titles/keywords as fallback matching criteria."
    )

class QueryEvaluationResult(BaseModel):
    """Evaluation metrics for a single query."""
    query: str = Field(..., description="The evaluated query.")
    retrieved_ids: List[str] = Field(default_factory=list, description="IDs of top chunks returned.")
    precision_at_5: float = Field(..., description="Precision at K=5.")
    precision_at_10: float = Field(..., description="Precision at K=10.")
    recall_at_5: float = Field(..., description="Recall at K=5.")
    recall_at_10: float = Field(..., description="Recall at K=10.")
    mrr: float = Field(..., description="Reciprocal rank.")
    hit_at_5: bool = Field(..., description="True if at least one expected match was in top 5.")
    hit_at_10: bool = Field(..., description="True if at least one expected match was in top 10.")

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
    distance_metric: str = Field(..., description="Metric used for retrieval (e.g. cosine).")
    fallback_mode_active: bool = Field(..., description="Whether database fallback mode was active.")
    metrics: BenchmarkSummaryMetrics = Field(..., description="Aggregated quality metrics.")
    query_results: List[QueryEvaluationResult] = Field(default_factory=list, description="Detail query results.")
    duration_ms: float = Field(..., description="Total execution duration in milliseconds.")
