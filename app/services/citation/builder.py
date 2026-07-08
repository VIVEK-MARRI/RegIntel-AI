"""CitationBuilder — assemble annotated answer + reference list.

The builder is stateless; the orchestrating :class:`CitationService`
holds the per-request state.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.citation import (
    AnnotatedAnswer,
    AnnotatedText,
    CitationStyle,
    Claim,
    InlineCitation,
    ReferenceEntry,
    detect_document_type,
    extract_circular_number,
)
from app.services.citation.mapper import ClaimChunkMatch

logger = logging.getLogger(__name__)


_PARAGRAPH_LOCATOR_RE = re.compile(
    r"\b("
    r"clause\s+\([a-z]\)"  # clause (a)
    r"|para\s?\d+(?:\.\d+)?"  # para 3.2
    r"|sub[\-\s]?clause\s+\([a-z]\)"  # sub-clause (a)
    r"|section\s+\d+(?:\.\d+)?"  # section 4.1
    r"|regulation\s+\d+"  # regulation 17
    r"|article\s+\d+"  # article 12
    r")",
    re.IGNORECASE,
)


def _detect_paragraph_locator(content: str) -> Optional[str]:
    if not content:
        return None
    m = _PARAGRAPH_LOCATOR_RE.search(content)
    return m.group(1) if m else None


class CitationBuilder:
    """Build annotated answers, reference entries, and citation maps."""

    def __init__(
        self, *, style: CitationStyle = CitationStyle.BRACKETED_SOURCE
    ) -> None:
        self.style = style

    # ── Reference list ──────────────────────────────────────────────────────

    def build_references(
        self,
        chunks: Sequence[RetrievedChunk],
        *,
        include_paragraph: bool = True,
    ) -> List[ReferenceEntry]:
        """Deduplicate chunks into a reference list.

        Each unique ``document_id`` produces at most one reference; if a
        document contributes multiple chunks we still emit a single
        reference (using the highest-scored chunk as the exemplar).
        """
        by_doc: Dict[str, RetrievedChunk] = {}
        for chunk in chunks:
            existing = by_doc.get(chunk.document_id)
            if existing is None or chunk.score > existing.score:
                by_doc[chunk.document_id] = chunk

        references: List[ReferenceEntry] = []
        for idx, (document_id, chunk) in enumerate(by_doc.items(), start=1):
            doc_title = chunk.document_title or document_id
            doc_type = detect_document_type(doc_title) or detect_document_type(
                chunk.content
            )
            circular = extract_circular_number(doc_title) or extract_circular_number(
                chunk.content
            )
            paragraph = (
                _detect_paragraph_locator(chunk.content) if include_paragraph else None
            )
            references.append(
                ReferenceEntry(
                    citation_id=self._format_citation_id(idx),
                    chunk_id=chunk.chunk_id,
                    document_id=document_id,
                    document_title=doc_title,
                    source=chunk.source.value if chunk.source else None,
                    document_type=doc_type,
                    circular_number=circular,
                    section=chunk.section,
                    subsection=chunk.subsection,
                    page_number=chunk.page_number,
                    paragraph=paragraph,
                    url=None,
                    excerpt=chunk.to_provider_excerpt(220),
                )
            )
        return references

    # ── Annotated text ──────────────────────────────────────────────────────

    def annotate_text(
        self,
        text: str,
        section_name: str,
        claims: Sequence[Claim],
        matches_by_claim: Dict[str, List[ClaimChunkMatch]],
        references: Sequence[ReferenceEntry],
    ) -> AnnotatedText:
        """Append inline markers to each claim and return AnnotatedText.

        Citations are appended in-place at the end of each claim
        sentence (before the trailing period if present).
        """
        if not text:
            return AnnotatedText(
                text="", citations=[], claim_count=0, cited_claim_count=0
            )

        ref_by_chunk: Dict[str, ReferenceEntry] = {r.chunk_id: r for r in references}

        annotated = text
        inline_citations: List[InlineCitation] = []
        cited = 0

        # Annotate from longest claim to shortest to avoid partial overlaps.
        ordered_claims = sorted(claims, key=lambda c: -len(c.text))
        for claim in ordered_claims:
            matches = matches_by_claim.get(claim.claim_id, [])
            if not matches:
                continue
            best = matches[0]
            ref = ref_by_chunk.get(best.chunk.chunk_id)
            if ref is None:
                # The chunk wasn't in our reference list (shouldn't happen,
                # but tolerate) — skip cleanly.
                continue
            marker = self._marker_for(ref)
            added_marker = _append_marker(annotated, claim.text, marker)
            if added_marker is None:
                continue
            annotated = added_marker
            inline_citations.append(
                InlineCitation(
                    citation_id=ref.citation_id,
                    chunk_id=ref.chunk_id,
                    claim_id=claim.claim_id,
                    marker=marker,
                    similarity=best.final_score,
                )
            )
            cited += 1

        return AnnotatedText(
            text=annotated,
            citations=inline_citations,
            claim_count=len(claims),
            cited_claim_count=cited,
        )

    # ── Annotated answer ────────────────────────────────────────────────────

    def build_annotated_answer(
        self,
        answer: AnswerSection,
        references: Sequence[ReferenceEntry],
        exec_claims: Sequence[Claim],
        detailed_claims: Sequence[Claim],
        exec_matches: Dict[str, List[ClaimChunkMatch]],
        detailed_matches: Dict[str, List[ClaimChunkMatch]],
    ) -> Tuple[AnnotatedAnswer, Dict[str, str]]:
        exec_annotated = self.annotate_text(
            answer.executive_summary,
            "executive_summary",
            exec_claims,
            exec_matches,
            references,
        )
        detailed_annotated = self.annotate_text(
            answer.detailed_explanation,
            "detailed_explanation",
            detailed_claims,
            detailed_matches,
            references,
        )

        citation_map: Dict[str, str] = {}
        for ann in (exec_annotated, detailed_annotated):
            for c in ann.citations:
                citation_map.setdefault(c.claim_id, c.citation_id)

        annotated = AnnotatedAnswer(
            executive_summary=exec_annotated,
            detailed_explanation=detailed_annotated,
            supporting_evidence=list(answer.supporting_evidence),
            key_regulatory_references=list(answer.key_regulatory_references),
            references=list(references),
            citation_map=citation_map,
        )
        return annotated, citation_map

    # ── Markers ─────────────────────────────────────────────────────────────

    def _format_citation_id(self, idx: int) -> str:
        if self.style == CitationStyle.NUMERIC_BRACKET:
            return f"[{idx}]"
        return f"ref-{idx}"

    def _marker_for(self, ref: ReferenceEntry) -> str:
        if self.style == CitationStyle.NUMERIC_BRACKET:
            return f" {ref.citation_id}"
        return f" {ref.to_marker()}"


# ─── Helper (module-level) ───────────────────────────────────────────────────


def _append_marker(text: str, claim: str, marker: str) -> Optional[str]:
    """Append ``marker`` right after the first occurrence of ``claim`` in
    ``text``.  Returns the new text, or ``None`` if the claim couldn't
    be found (e.g. the text was already mutated by a previous claim).
    """
    if not claim or not text:
        return None
    idx = text.find(claim)
    if idx == -1:
        return None
    insert_at = idx + len(claim)
    return text[:insert_at] + marker + text[insert_at:]


__all__ = ["CitationBuilder", "ReferenceEntry"]
