"""Embedding provider factory.

Tries to load the BGE (sentence-transformers) backend.  If the
``sentence_transformers`` package is not installed the system automatically
falls back to :class:`~app.services.embedding.tfidf.TFIDFEmbeddingProvider`
so the application remains functional without the heavy ML stack.

The selected backend name is exported as ``EMBEDDING_BACKEND_NAME`` and
registered as a health-check component by the startup module so the
operator always knows which backend is active via ``/health/ready``.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


def _build_provider() -> tuple[EmbeddingProvider, str]:
    """Return ``(provider, backend_name)`` using the best available backend."""
    try:
        import sentence_transformers  # noqa: F401 — presence check only
        from app.services.embedding.bge import BGEEmbeddingProvider

        provider = BGEEmbeddingProvider(
            model_name=settings.EMBEDDING_MODEL_NAME,
            device=settings.EMBEDDING_DEVICE,
            normalize_embeddings=settings.EMBEDDING_NORMALIZE,
            query_instruction=settings.EMBEDDING_QUERY_INSTRUCTION,
        )
        logger.info(
            "Embedding backend: BGE (%s) — sentence_transformers available.",
            settings.EMBEDDING_MODEL_NAME,
        )
        return provider, "bge"
    except ImportError:
        from app.services.embedding.tfidf import TFIDFEmbeddingProvider

        provider = TFIDFEmbeddingProvider()  # warns internally
        return provider, "tfidf_fallback"


# Module-level singletons — created once at import time.
embedding_provider: EmbeddingProvider
EMBEDDING_BACKEND_NAME: str
embedding_provider, EMBEDDING_BACKEND_NAME = _build_provider()


from app.services.embedding.bge import BGEEmbeddingProvider  # noqa: E402 — re-export
from app.services.embedding.tfidf import TFIDFEmbeddingProvider  # noqa: E402

__all__ = [
    "EMBEDDING_BACKEND_NAME",
    "BGEEmbeddingProvider",
    "EmbeddingProvider",
    "TFIDFEmbeddingProvider",
    "embedding_provider",
]

