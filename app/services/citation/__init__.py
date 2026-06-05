"""Module 5.2 — Citation Engine.

Pipeline
--------

::

    AnswerSection  +  RetrievedChunk[]
        ↓
    ClaimExtractor     (sentence split + filter)
        ↓
    CitationMapper     (lexical / token-overlap matching)
        ↓
    CitationBuilder    (annotated text + reference list + citation map)
        ↓
    CitationValidator  (coverage stats; flags uncited claims)
        ↓
    CitationResponse

The engine is deterministic (no LLM dependency) so it's safe to use in
tests, CI, and offline benchmarks.
"""

from __future__ import annotations

from app.services.citation.claim_extractor import (
    ClaimExtractor,
    split_into_sentences,
)
from app.services.citation.mapper import (
    CitationMapper,
    TokenOverlapScorer,
    ClaimChunkMatch,
)
from app.services.citation.builder import CitationBuilder
from app.services.citation.service import (
    CitationService,
    CitationTelemetry,
    build_default_citation_service,
)

__all__ = [
    "CitationService",
    "CitationTelemetry",
    "build_default_citation_service",
    "ClaimExtractor",
    "split_into_sentences",
    "CitationMapper",
    "TokenOverlapScorer",
    "ClaimChunkMatch",
    "CitationBuilder",
]
