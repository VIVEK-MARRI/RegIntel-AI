"""BGE Reranker Model Provider.

Thread-safe, lazy-loading wrapper around the ``sentence_transformers.CrossEncoder``
model for cross-encoder relevance scoring.  Follows the same patterns as
``BGEEmbeddingProvider`` (lazy init, thread lock, health check).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Result from a scoring operation, including scores and timing."""

    scores: List[float]
    scoring_latency_ms: float = 0.0


class BGERerankerProvider:
    """Manages the BAAI/bge-reranker-base cross-encoder model.

    Features:
    - **Lazy loading**: model is loaded on first use.
    - **Thread safety**: double-checked locking via ``threading.Lock``.
    - **Batch scoring**: ``score_pairs`` accepts a list of (query, text) tuples.
    - **Device auto-detection**: CUDA if available, else CPU.
    - **Latency tracking**: ``score_pairs_timed`` returns inference latency.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        device: Optional[str] = None,
        max_length: int = 512,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def _get_model(self):
        """Thread-safe lazy loading of the CrossEncoder model."""
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            # Auto-detect device
            if not self.device:
                try:
                    import torch
                    self.device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    self.device = "cpu"

            logger.info(
                "Loading reranker model '%s' on device '%s' (max_length=%d)...",
                self.model_name, self.device, self.max_length,
            )
            start = time.perf_counter()
            try:
                from sentence_transformers import CrossEncoder

                model = CrossEncoder(
                    self.model_name,
                    max_length=self.max_length,
                    device=self.device,
                )
                self._model = model
                elapsed = (time.perf_counter() - start) * 1000
                logger.info(
                    "Loaded reranker model '%s' in %.2fms.",
                    self.model_name, elapsed,
                )
            except Exception as e:
                logger.error(
                    "Failed to load reranker model '%s': %s",
                    self.model_name, e, exc_info=True,
                )
                raise RuntimeError(f"Could not load reranker model: {e}") from e

        return self._model

    # ------------------------------------------------------------------
    # Scoring API
    # ------------------------------------------------------------------

    def score_pair(self, query: str, text: str) -> float:
        """Score a single (query, text) pair.

        Returns a float relevance score (higher = more relevant).
        """
        model = self._get_model()
        score = model.predict([(query, text)])
        # CrossEncoder.predict returns ndarray; take first element
        return float(score[0])

    def score_pairs(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Score a batch of (query, text) pairs.

        Uses the configured ``batch_size`` for efficient GPU/CPU throughput.

        Returns:
            A list of float relevance scores, one per input pair.
        """
        result = self.score_pairs_timed(pairs)
        return result.scores

    def score_pairs_timed(self, pairs: List[Tuple[str, str]]) -> ScoringResult:
        """Score a batch of (query, text) pairs with latency tracking.

        Uses the configured ``batch_size`` for efficient GPU/CPU throughput.

        Returns:
            ScoringResult with scores and inference latency in milliseconds.
        """
        if not pairs:
            return ScoringResult(scores=[], scoring_latency_ms=0.0)

        model = self._get_model()
        logger.debug("Scoring %d query-text pairs (batch_size=%d)...", len(pairs), self.batch_size)
        start = time.perf_counter()

        scores = model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "Scored %d pairs with reranker in %.2fms.",
            len(pairs), elapsed,
        )
        return ScoringResult(
            scores=[float(s) for s in scores],
            scoring_latency_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_model_name(self) -> str:
        """Return the configured model identifier."""
        return self.model_name

    def health_check(self) -> bool:
        """Run a trivial inference pass to verify the model is loaded and functional."""
        try:
            model = self._get_model()
            if model is None:
                return False
            test_score = self.score_pair("health check", "system is operational")
            return isinstance(test_score, float)
        except Exception as e:
            logger.error("Reranker health check failed: %s", e)
            return False
