"""Reranker package initialization.

Exports the BGE Reranking Engine components:
- BGERerankerProvider: Thread-safe model provider for cross-encoder inference.
- RerankerService: Full reranking pipeline with scoring, filtering, and reporting.
- ScoringResult: Dataclass for scores with latency tracking.
"""

from app.services.reranker.model import BGERerankerProvider, ScoringResult
from app.services.reranker.service import RerankerService

__all__ = [
    "BGERerankerProvider",
    "RerankerService",
    "ScoringResult",
]
