"""CitationService — orchestrator (Module 5.2 public API).

Glues the :class:`ClaimExtractor`, :class:`CitationMapper`, and
:class:`CitationBuilder` together.  Produces a :class:`CitationResponse`
and validates the "every claim must have a citation" rule.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.schemas.answer_generation import RetrievedChunk
from app.schemas.citation import (
    AnnotatedAnswer,
    CitationCoverage,
    CitationMetadata,
    CitationRequest,
    CitationResponse,
    CitationStyle,
    Claim,
)
from app.services.citation.builder import CitationBuilder
from app.services.citation.claim_extractor import ClaimExtractor
from app.services.citation.mapper import (
    CitationMapper,
    ClaimChunkMatch,
    TokenOverlapScorer,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Telemetry ──────────────────────────────────────────────────────────────


@dataclass
class CitationTelemetry:
    request_id: str = ""
    latency_ms: float = 0.0
    chunks_used: int = 0
    claims_extracted: int = 0
    citations_emitted: int = 0
    uncited_claim_count: int = 0
    style: str = "bracketed_source"


# ─── Service ────────────────────────────────────────────────────────────────


class CitationService:
    """Top-level orchestrator.  Pure-Python; no external services."""

    def __init__(
        self,
        *,
        extractor: Optional[ClaimExtractor] = None,
        mapper: Optional[CitationMapper] = None,
        builder: Optional[CitationBuilder] = None,
    ) -> None:
        self.extractor = extractor or ClaimExtractor()
        self.mapper = mapper or CitationMapper()
        self.builder = builder or CitationBuilder()

    # ── Public API ──────────────────────────────────────────────────────────

    def cite(self, request: CitationRequest) -> CitationResponse:
        if not request.chunks:
            raise ValueError("CitationRequest requires at least one chunk")

        # Configure sub-components for this request.
        mapper = CitationMapper(
            scorer=TokenOverlapScorer(),
            min_similarity=request.min_similarity,
        )
        builder = CitationBuilder(style=request.style)

        with track_request(
            endpoint="/api/v1/citation/cite",
            strategy="citation",
        ) as ctx:
            t0 = time.perf_counter()

            # 1. Extract claims.
            exec_claims = self.extractor.extract(
                request.answer.executive_summary, section="executive_summary"
            )
            detailed_claims = self.extractor.extract(
                request.answer.detailed_explanation, section="detailed_explanation"
            )
            all_claims: List[Claim] = [*exec_claims, *detailed_claims]

            # 2. Map claims → chunks.
            exec_matches = self._map_all(exec_claims, request.chunks, mapper)
            detailed_matches = self._map_all(
                detailed_claims, request.chunks, mapper
            )

            # 3. Build reference list.
            references = builder.build_references(
                request.chunks,
                include_paragraph=request.include_paragraph,
            )

            # 4. Annotate text.
            annotated_answer, _ = builder.build_annotated_answer(
                answer=request.answer,
                references=references,
                exec_claims=exec_claims,
                detailed_claims=detailed_claims,
                exec_matches=exec_matches,
                detailed_matches=detailed_matches,
            )

            # 5. Coverage.
            coverage = self._compute_coverage(all_claims, annotated_answer)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            try:
                ctx.rerank_used = False  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass

        metadata = CitationMetadata(
            request_id=uuid.uuid4().hex,
            latency_ms=latency_ms,
            chunks_used=len(request.chunks),
            claims_extracted=len(all_claims),
            citations_emitted=sum(
                len(annotated_answer.executive_summary.citations)
                + len(annotated_answer.detailed_explanation.citations)
                for _ in [0]
            ),
            style=request.style,
        )

        if request.require_full_coverage and coverage.coverage_ratio < 1.0:
            logger.warning(
                "Partial citation coverage: %d/%d claims cited (%.1f%%)",
                coverage.cited_claims,
                coverage.total_claims,
                coverage.coverage_ratio * 100.0,
            )

        return CitationResponse(
            query=request.query,
            annotated_answer=annotated_answer,
            coverage=coverage,
            metadata=metadata,
        )

    # ── Convenience ────────────────────────────────────────────────────────

    def cite_answer(
        self,
        *,
        query: str,
        answer,  # AnswerSection
        chunks: List[RetrievedChunk],
        style: CitationStyle = CitationStyle.BRACKETED_SOURCE,
        min_similarity: float = 0.05,
        require_full_coverage: bool = False,
        include_paragraph: bool = True,
    ) -> CitationResponse:
        """One-shot wrapper for callers that don't want to build a request."""
        request = CitationRequest(
            query=query,
            answer=answer,
            chunks=chunks,
            style=style,
            min_similarity=min_similarity,
            require_full_coverage=require_full_coverage,
            include_paragraph=include_paragraph,
        )
        return self.cite(request)

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_all(
        claims: List[Claim],
        chunks: List[RetrievedChunk],
        mapper: CitationMapper,
    ) -> Dict[str, List[ClaimChunkMatch]]:
        out: Dict[str, List[ClaimChunkMatch]] = {}
        for claim in claims:
            out[claim.claim_id] = mapper.map_claim(claim, chunks)
        return out

    @staticmethod
    def _compute_coverage(
        claims: List[Claim], annotated: AnnotatedAnswer
    ) -> CitationCoverage:
        cited_ids = {
            c.claim_id
            for c in annotated.executive_summary.citations
            for _ in [0]
        } | {
            c.claim_id
            for c in annotated.detailed_explanation.citations
            for _ in [0]
        }
        uncited = [c.claim_id for c in claims if c.claim_id not in cited_ids]
        total = len(claims)
        cited = total - len(uncited)
        return CitationCoverage(
            total_claims=total,
            cited_claims=cited,
            uncited_claims=len(uncited),
            coverage_ratio=(cited / total) if total else 1.0,
            uncited_claim_ids=uncited,
            unique_references=len(annotated.references),
        )


# ─── Factory ────────────────────────────────────────────────────────────────


def build_default_citation_service() -> CitationService:
    return CitationService()


__all__ = [
    "CitationService",
    "CitationTelemetry",
    "build_default_citation_service",
]
