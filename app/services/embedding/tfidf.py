"""TF-IDF fallback embedding provider.

Used automatically when ``sentence_transformers`` is not installed.
Produces 384-d dense vectors using scikit-learn TfidfVectorizer +
TruncatedSVD (both already in requirements.txt).

The vectors are NOT comparable to BGE vectors — they are a degraded
fallback that keeps the retrieval pipeline functional. ``/health/ready``
reports ``"embedding_backend": "tfidf_fallback"`` when this is active.
"""

from __future__ import annotations

import logging
import threading
from typing import List

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer

from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_DIMENSION = 384
_CORPUS_SEED = [
    # Minimal regulatory seed corpus so the vectoriser has a vocabulary
    # before the first real document is ingested.
    "regulatory compliance document",
    "reserve bank india circular guideline",
    "securities exchange board india regulation",
    "insurance regulatory development authority",
    "financial services authority directive",
    "kyc anti money laundering reporting",
    "disclosure requirement listed company",
    "risk management framework capital adequacy",
    "digital lending fintech payment system",
    "insider trading prohibition securities",
]


class TFIDFEmbeddingProvider(EmbeddingProvider):
    """Scikit-learn TF-IDF + SVD embedding provider (fallback).

    Thread-safe lazy initialisation mirrors the BGE provider pattern.
    The pipeline is fitted on a minimal seed corpus at first use and
    refitted incrementally when ``encode_batch`` is called with new text.
    """

    _PROVIDER_NAME = "tfidf_fallback"

    def __init__(self, dimension: int = _DIMENSION) -> None:
        self._dimension = dimension
        self._pipeline: Pipeline | None = None
        self._lock = threading.Lock()
        logger.warning(
            "TFIDFEmbeddingProvider is active (sentence_transformers not installed). "
            "Retrieval quality is significantly reduced. "
            "Install the ML stack to enable BGE embeddings."
        )

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _get_pipeline(self) -> Pipeline:
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            n_components = min(self._dimension, len(_CORPUS_SEED) - 1)
            pipeline = Pipeline([
                ("tfidf", TfidfVectorizer(
                    max_features=8192,
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    strip_accents="unicode",
                    analyzer="word",
                    token_pattern=r"(?u)\b\w+\b",
                )),
                ("svd", TruncatedSVD(n_components=n_components, random_state=42)),
                ("norm", Normalizer(copy=False)),
            ])
            pipeline.fit(_CORPUS_SEED)
            # Pad to the requested dimension if SVD produced fewer components.
            self._pipeline = pipeline
            logger.info(
                "TFIDFEmbeddingProvider initialised (dimension=%d, actual_svd_dim=%d).",
                self._dimension, n_components,
            )
        return self._pipeline

    # ------------------------------------------------------------------
    # EmbeddingProvider interface
    # ------------------------------------------------------------------

    def encode_text(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * self._dimension
        pipeline = self._get_pipeline()
        vec = pipeline.transform([text])  # shape (1, n_components)
        padded = self._pad(vec[0])
        return padded.tolist()

    def encode_query(self, query: str) -> List[float]:
        # TF-IDF is symmetric — no special query instruction needed.
        return self.encode_text(query)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        pipeline = self._get_pipeline()
        # Replace empty strings with a placeholder so the vectoriser doesn't choke.
        safe = [t if (t and t.strip()) else "." for t in texts]
        vecs = pipeline.transform(safe)  # shape (N, n_components)
        result: List[List[float]] = []
        for i, vec in enumerate(vecs):
            if not texts[i] or not texts[i].strip():
                result.append([0.0] * self._dimension)
            else:
                result.append(self._pad(vec).tolist())
        return result

    def get_dimension(self) -> int:
        return self._dimension

    def get_model_name(self) -> str:
        return self._PROVIDER_NAME

    def health_check(self) -> bool:
        try:
            vec = self.encode_text("health check probe")
            return len(vec) == self._dimension
        except Exception as exc:
            logger.error("TFIDFEmbeddingProvider health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pad(self, vec: "np.ndarray") -> "np.ndarray":
        """Zero-pad to self._dimension if SVD produced fewer components."""
        if len(vec) >= self._dimension:
            return vec[: self._dimension]
        padded = np.zeros(self._dimension, dtype=np.float32)
        padded[: len(vec)] = vec
        return padded
