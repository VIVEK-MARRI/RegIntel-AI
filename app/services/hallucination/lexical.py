"""Lexical faithfulness checker (offline fallback).

Splits the answer into claims (reusing :class:`ClaimExtractor` from
Module 5.2) and verifies each claim against the retrieved chunks
using token-overlap scoring.  A claim is supported if its
``token_overlap`` with at least one chunk exceeds the configured
threshold; otherwise it is unsupported with a short reason.

This is intentionally simple and deterministic — it's a safety net
for the LLM evaluator, not a replacement.  When the LLM is
available, the LLM is the authoritative judge.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.citation import Claim
from app.schemas.hallucination import ClaimVerdict
from app.services.citation.claim_extractor import ClaimExtractor
from app.services.citation.mapper import token_overlap

logger = logging.getLogger(__name__)


class LexicalFaithfulnessChecker:
    """Token-overlap-based faithfulness check.

    Parameters
    ----------
    threshold:
        Minimum token-overlap (cosine+Jaccard blend) to consider a
        claim supported.  Default ``0.15`` is intentionally lenient.
    extractor:
        Optional custom :class:`ClaimExtractor`.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.15,
        extractor: Optional[ClaimExtractor] = None,
    ) -> None:
        self.threshold = float(threshold)
        self.extractor = extractor or ClaimExtractor()

    # ── Public API ──────────────────────────────────────────────────────────

    def verify(
        self,
        *,
        answer: AnswerSection,
        chunks: List[RetrievedChunk],
    ) -> List[ClaimVerdict]:
        """Return one :class:`ClaimVerdict` per claim."""
        claims = self._extract_claims(answer)
        return [self._verdict_for(claim, chunks) for claim in claims]

    def supported_count(self, verdicts: List[ClaimVerdict]) -> int:
        return sum(1 for v in verdicts if v.supported)

    # ── Internals ──────────────────────────────────────────────────────────

    def _extract_claims(self, answer: AnswerSection) -> List[Claim]:
        return self.extractor.extract_all(
            [
                ("executive_summary", answer.executive_summary),
                ("detailed_explanation", answer.detailed_explanation),
            ]
        )

    def _verdict_for(self, claim: Claim, chunks: List[RetrievedChunk]) -> ClaimVerdict:
        if not chunks:
            return ClaimVerdict(
                claim_id=claim.claim_id,
                claim=claim.text,
                section=claim.section,
                supported=False,
                confidence=0.0,
                cited_chunk_ids=[],
                reason="no source documents available",
            )

        scored: List[tuple[RetrievedChunk, float]] = []
        for chunk in chunks:
            score = token_overlap(claim.text, chunk.content)
            if score >= self.threshold:
                scored.append((chunk, score))

        if not scored:
            return ClaimVerdict(
                claim_id=claim.claim_id,
                claim=claim.text,
                section=claim.section,
                supported=False,
                confidence=0.0,
                cited_chunk_ids=[],
                reason=f"no chunk reached lexical-overlap threshold ({self.threshold:.2f})",
            )

        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0]
        return ClaimVerdict(
            claim_id=claim.claim_id,
            claim=claim.text,
            section=claim.section,
            supported=True,
            confidence=min(1.0, best[1]),
            cited_chunk_ids=[best[0].chunk_id],
            reason=f"lexical overlap {best[1]:.2f} with chunk {best[0].chunk_id}",
        )


__all__ = ["LexicalFaithfulnessChecker"]
