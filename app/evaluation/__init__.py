"""Retrieval Evaluation Suite.

Provides comprehensive evaluation framework for measuring and comparing
retrieval performance across different strategies:
- Dense Retrieval
- BM25 Retrieval
- Hybrid Retrieval
- Hybrid + Reranker

Metrics supported:
- Recall@K (K=5, 10)
- MRR (Mean Reciprocal Rank)
- Precision@K
- Hit Rate
"""

from app.evaluation.metrics import MetricsEngine
from app.evaluation.evaluator import RetrievalEvaluator
from app.evaluation.dataset import GoldenDataset, QueryRelevance
from app.evaluation.reporting import ReportGenerator, Leaderboard
from app.evaluation.storage import MetricsStorage

__all__ = [
    "MetricsEngine",
    "RetrievalEvaluator",
    "GoldenDataset",
    "QueryRelevance",
    "ReportGenerator",
    "Leaderboard",
    "MetricsStorage",
]