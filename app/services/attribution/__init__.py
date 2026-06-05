"""Module 5.5 — Source Attribution Engine.

Provides:

* :class:`AttributionMapper` — splits an :class:`AnswerSection` into
  segments and matches each to the most relevant retrieved chunk.
* :class:`AttributionValidator` — checks that every segment has an
  attribution and the coverage meets the request's threshold.
* :class:`SourceAttributionService` — top-level orchestrator that
  runs the mapper, the validator, and packages the response.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.attribution import (
    AttributionConfidence,
    AttributionCoverage,
    AttributionMetadata,
    AttributionRequest,
    AttributionResponse,
    AttributionSection,
    AttributionValidation,
    SourceAttribution,
    bucket_confidence,
    build_excerpt,
)
from app.services.citation.claim_extractor import ClaimExtractor
from app.services.citation.mapper import token_overlap
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Mapper ─────────────────────────────────────────────────────────────────


@dataclass
class _Segment:
    section: AttributionSection
    index: int
    text: str


class AttributionMapper:
    """Splits an answer into segments and attributes each to a chunk.

    Reuses :class:`ClaimExtractor` from Module 5.2 to split
    ``executive_summary`` and ``detailed_explanation`` into atomic
    claims; ``supporting_evidence`` items are treated as single
    segments; ``key_regulatory_references`` are turned into segments
    too so they can be attributed.

    Matching uses the same token-overlap scorer as Module 5.2's
    :class:`CitationMapper` for consistency.
    """

    def __init__(self, *, extractor: Optional[ClaimExtractor] = None) -> None:
        self.extractor = extractor or ClaimExtractor()

    def map(
        self,
        *,
        answer: AnswerSection,
        chunks: List[RetrievedChunk],
        min_similarity: float = 0.10,
        max_excerpt_length: int = 200,
    ) -> List[SourceAttribution]:
        segments = self._split(answer)
        attributions: List[SourceAttribution] = []
        for seg in segments:
            attr = self._attest(seg, chunks, min_similarity, max_excerpt_length)
            attributions.append(attr)
        return attributions

    # ── Internals ──────────────────────────────────────────────────────────

    def _split(self, answer: AnswerSection) -> List[_Segment]:
        out: List[_Segment] = []
        # Executive summary: each sentence is a segment.
        es_claims = self.extractor.extract(
            answer.executive_summary, section=AttributionSection.EXECUTIVE_SUMMARY.value
        )
        for i, c in enumerate(es_claims):
            out.append(_Segment(AttributionSection.EXECUTIVE_SUMMARY, i, c.text))
        # Detailed explanation: each sentence is a segment.
        de_claims = self.extractor.extract(
            answer.detailed_explanation, section=AttributionSection.DETAILED_EXPLANATION.value
        )
        for i, c in enumerate(de_claims):
            out.append(_Segment(AttributionSection.DETAILED_EXPLANATION, i, c.text))
        # Supporting evidence: each item is a segment.
        for i, ev in enumerate(answer.supporting_evidence):
            text = (ev.excerpt or "").strip()
            if not text:
                continue
            out.append(
                _Segment(AttributionSection.SUPPORTING_EVIDENCE, i, text)
            )
        # Key regulatory references: each item is a segment.
        for i, ref in enumerate(answer.key_regulatory_references):
            text = (ref or "").strip()
            if not text:
                continue
            out.append(
                _Segment(AttributionSection.KEY_REGULATORY_REFERENCES, i, text)
            )
        return out

    def _attest(
        self,
        seg: _Segment,
        chunks: List[RetrievedChunk],
        min_similarity: float,
        max_excerpt_length: int,
    ) -> SourceAttribution:
        best: Optional[Tuple[RetrievedChunk, float]] = None
        for chunk in chunks:
            score = token_overlap(seg.text, chunk.content)
            if best is None or score > best[1]:
                best = (chunk, score)
        # Fallback: no chunks at all (or none matched).
        if best is None:
            return SourceAttribution(
                section=seg.section,
                segment_index=seg.index,
                segment_text=seg.text,
                document_id="",
                document_title="(no source)",
                chunk_id="",
                page_number=None,
                chunk_section=None,
                source=None,
                excerpt="",
                similarity=0.0,
                confidence=AttributionConfidence.NONE,
            )
        chunk, score = best
        confidence = bucket_confidence(score)
        if score < min_similarity:
            # The mapper still emits an attribution record so the caller
            # can see the segment exists, but marks it as unattributed.
            return SourceAttribution(
                section=seg.section,
                segment_index=seg.index,
                segment_text=seg.text,
                document_id=chunk.document_id,
                document_title=chunk.document_title or "(untitled)",
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                chunk_section=chunk.section,
                source=getattr(chunk, "source", None) and (
                    chunk.source.value if hasattr(chunk.source, "value") else str(chunk.source)
                ),
                excerpt=build_excerpt(chunk.content, max_length=max_excerpt_length),
                similarity=score,
                confidence=confidence,
                metadata={"matched_below_threshold": True, "rank": chunk.rank},
            )
        return SourceAttribution(
            section=seg.section,
            segment_index=seg.index,
            segment_text=seg.text,
            document_id=chunk.document_id,
            document_title=chunk.document_title or "(untitled)",
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
            chunk_section=chunk.section,
            source=getattr(chunk, "source", None) and (
                chunk.source.value if hasattr(chunk.source, "value") else str(chunk.source)
            ),
            excerpt=build_excerpt(chunk.content, max_length=max_excerpt_length),
            similarity=score,
            confidence=confidence,
            metadata={"rank": chunk.rank},
        )


# ─── Validator ──────────────────────────────────────────────────────────────


class AttributionValidator:
    """Validates the output of the mapper against the request contract."""

    def validate(
        self,
        *,
        attributions: List[SourceAttribution],
        request: AttributionRequest,
    ) -> AttributionValidation:
        issues: List[str] = []
        warnings: List[str] = []
        unattributed = [a for a in attributions if a.confidence == AttributionConfidence.NONE]
        low_conf = [a for a in attributions if a.confidence == AttributionConfidence.LOW]

        if not attributions:
            issues.append("no answer segments were extracted from the answer")
        if unattributed:
            ids = [a.attribution_id for a in unattributed]
            warnings.append(
                f"{len(unattributed)} segment(s) had no matching chunk (ids={ids})"
            )
        if low_conf and len(low_conf) / max(1, len(attributions)) > 0.5:
            warnings.append(
                f"more than 50% of segments have LOW confidence ({len(low_conf)}/{len(attributions)})"
            )
        if request.require_full_coverage and unattributed:
            issues.append("require_full_coverage=true but some segments are unattributed")
        valid = not issues
        return AttributionValidation(valid=valid, issues=issues, warnings=warnings)


# ─── Service ────────────────────────────────────────────────────────────────


class SourceAttributionService:
    """Top-level orchestrator for source attribution."""

    def __init__(
        self,
        *,
        mapper: Optional[AttributionMapper] = None,
        validator: Optional[AttributionValidator] = None,
    ) -> None:
        self.mapper = mapper or AttributionMapper()
        self.validator = validator or AttributionValidator()

    def attribute(self, request: AttributionRequest) -> AttributionResponse:
        request_id = uuid.uuid4().hex
        t0 = time.perf_counter()
        with track_request(
            endpoint="/api/v1/attribution/attribute",
            strategy="source_attribution",
        ) as ctx:
            try:
                attributions = self.mapper.map(
                    answer=request.answer,
                    chunks=request.chunks,
                    min_similarity=request.min_similarity,
                    max_excerpt_length=request.max_excerpt_length,
                )
                validation = self.validator.validate(
                    attributions=attributions, request=request
                )
                coverage = self._compute_coverage(attributions)
            except Exception as exc:
                logger.exception("Source attribution failed")
                raise
        latency_ms = (time.perf_counter() - t0) * 1000.0
        metadata = AttributionMetadata(
            request_id=request_id,
            latency_ms=latency_ms,
            chunks_used=len(request.chunks),
            segments_extracted=len(attributions),
            attributions_emitted=sum(
                1 for a in attributions if a.confidence != AttributionConfidence.NONE
            ),
        )
        return AttributionResponse(
            query=request.query,
            attributions=attributions,
            coverage=coverage,
            validation=validation,
            metadata=metadata,
        )

    def attribute_segments(
        self,
        *,
        query: str,
        answer: AnswerSection,
        chunks: List[RetrievedChunk],
        min_similarity: float = 0.10,
        require_full_coverage: bool = False,
        max_excerpt_length: int = 200,
    ) -> AttributionResponse:
        request = AttributionRequest(
            query=query,
            answer=answer,
            chunks=chunks,
            min_similarity=min_similarity,
            require_full_coverage=require_full_coverage,
            max_excerpt_length=max_excerpt_length,
        )
        return self.attribute(request)

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_coverage(attributions: List[SourceAttribution]) -> AttributionCoverage:
        if not attributions:
            return AttributionCoverage(
                total_segments=0,
                attributed_segments=0,
                unattributed_segments=0,
                coverage_ratio=0.0,
                unattributed_segment_ids=[],
                average_similarity=0.0,
                high_confidence_count=0,
                medium_confidence_count=0,
                low_confidence_count=0,
            )
        total = len(attributions)
        unattributed = [a for a in attributions if a.confidence == AttributionConfidence.NONE]
        high = sum(1 for a in attributions if a.confidence == AttributionConfidence.HIGH)
        med = sum(1 for a in attributions if a.confidence == AttributionConfidence.MEDIUM)
        low = sum(1 for a in attributions if a.confidence == AttributionConfidence.LOW)
        avg = sum(a.similarity for a in attributions) / total
        return AttributionCoverage(
            total_segments=total,
            attributed_segments=total - len(unattributed),
            unattributed_segments=len(unattributed),
            coverage_ratio=(total - len(unattributed)) / total,
            unattributed_segment_ids=[a.attribution_id for a in unattributed],
            average_similarity=avg,
            high_confidence_count=high,
            medium_confidence_count=med,
            low_confidence_count=low,
        )


def build_default_attribution_service() -> SourceAttributionService:
    """Factory: a default :class:`SourceAttributionService` with lexical mapper."""
    return SourceAttributionService()


__all__ = [
    "AttributionMapper",
    "AttributionValidator",
    "SourceAttributionService",
    "build_default_attribution_service",
]
