"""Module 5.3 — Confidence Scoring Engine.

Pipeline
--------

::

    ConfidenceRequest
        ↓
    FactorCalculator (per factor)
        ↓
    ConfidenceCalculator (weighted aggregation + level)
        ↓
    ConfidenceService (orchestrator + flags + metrics)
        ↓
    ConfidenceResponse

The engine is deterministic and side-effect free, so it's safe in
tests and CI.  The :class:`ConfidenceMetrics` collector is a thin
in-process counter — a real deployment would push to Prometheus / OTLP.
"""

from __future__ import annotations

from app.services.confidence.calculator import (
    ConfidenceCalculator,
    FactorCalculator,
)
from app.services.confidence.factors import (
    chunk_coverage_factor,
    citation_coverage_factor,
    retrieval_relevance_factor,
    reranker_confidence_factor,
    source_agreement_factor,
)
from app.services.confidence.metrics import ConfidenceMetrics
from app.services.confidence.service import (
    ConfidenceService,
    build_default_confidence_service,
)

__all__ = [
    "ConfidenceService",
    "build_default_confidence_service",
    "ConfidenceCalculator",
    "FactorCalculator",
    "ConfidenceMetrics",
    "retrieval_relevance_factor",
    "reranker_confidence_factor",
    "source_agreement_factor",
    "chunk_coverage_factor",
    "citation_coverage_factor",
]
