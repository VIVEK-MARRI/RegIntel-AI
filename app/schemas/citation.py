"""Module 5.2 — Citation Engine API contracts.

Defines the Pydantic v2 schemas used by the citation layer.  The
citation engine accepts the :class:`AnswerSection` produced by Module
5.1 and the original :class:`RetrievedChunk` list, then emits an
annotated answer with inline citation markers, a structured reference
list, and citation-coverage metadata.

Citation format
---------------

Inline markers follow the spec:

    [RBI Circular 12/2024 | Page 8]

That is ``[<source> <document-type> <number> | Page <page>]`` when a
page number is available, falling back to ``[<source> <document-type>
<number>]`` when not.  The reference list uses bracketed numeric IDs
(``[1]``, ``[2]``, ...) that map to :class:`ReferenceEntry` objects.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.answer_generation import (
    AnswerSection,
    EvidenceChunk,
    RetrievedChunk,
)


# ─── Enumerations ────────────────────────────────────────────────────────────


class CitationStyle(str, Enum):
    """Supported inline-citation styles."""

    BRACKETED_SOURCE = "bracketed_source"  # [RBI Circular 12/2024 | Page 8]
    NUMERIC_BRACKET = "numeric_bracket"    # [1] [2] [3]  (with separate ref list)


# ─── Reference / Citation Models ─────────────────────────────────────────────


class ReferenceEntry(BaseModel):
    """One source-document reference in the citation list."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(
        ..., description="Citation id used inline (e.g. '[1]' or 'RBI-CIRC-1')."
    )
    chunk_id: str = Field(..., description="Source chunk UUID.")
    document_id: str = Field(..., description="Source document UUID.")
    document_title: str = Field(..., description="Title of the source document.")
    source: Optional[str] = Field(
        None, description="Regulator source (RBI / SEBI / IRDAI / PFRDA)."
    )
    document_type: Optional[str] = Field(
        None,
        description="Detected document type (Circular, Master Direction, Act, ...).",
    )
    circular_number: Optional[str] = Field(
        None,
        description="Extracted circular / notification number, e.g. '12/2024'.",
    )
    section: Optional[str] = Field(None, description="Section title.")
    subsection: Optional[str] = Field(None, description="Subsection title.")
    page_number: Optional[int] = Field(
        None, ge=0, description="Page number the chunk was extracted from."
    )
    paragraph: Optional[str] = Field(
        None,
        description="A short paragraph locator (e.g. 'para 3.2' or 'clause (a)').",
    )
    url: Optional[str] = Field(None, description="Optional deep link.")
    excerpt: str = Field(..., description="Short excerpt of the chunk.")

    def to_marker(self) -> str:
        """Format the inline citation marker (e.g. ``[RBI Circular 12/2024 | Page 8]``)."""
        return format_inline_marker(
            source=self.source,
            document_type=self.document_type,
            document_title=self.document_title,
            circular_number=self.circular_number,
            page_number=self.page_number,
        )


class InlineCitation(BaseModel):
    """A citation marker attached to a specific claim."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(..., description="Matches ReferenceEntry.citation_id.")
    chunk_id: str = Field(..., description="Source chunk UUID.")
    claim_id: str = Field(..., description="The claim this citation supports.")
    marker: str = Field(..., description="Inline marker text, e.g. '[RBI ... | Page 8]'.")
    similarity: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the claim→chunk match.",
    )


class Claim(BaseModel):
    """A single factual claim extracted from the answer text."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(
        default_factory=lambda: f"clm-{uuid.uuid4().hex[:8]}",
        description="Unique claim id.",
    )
    text: str = Field(..., min_length=1, description="The claim sentence.")
    section: str = Field(
        ..., description="Which answer section the claim came from (executive_summary / detailed_explanation)."
    )


# ─── Annotated Answer ───────────────────────────────────────────────────────


class AnnotatedText(BaseModel):
    """A block of text with embedded citation markers."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="Annotated text with inline markers appended per claim.")
    citations: List[InlineCitation] = Field(
        default_factory=list, description="Inline citations attached to the text."
    )
    claim_count: int = Field(0, ge=0, description="Number of claims detected in the original text.")
    cited_claim_count: int = Field(
        0, ge=0, description="Number of claims that received at least one citation."
    )


class AnnotatedAnswer(BaseModel):
    """An :class:`AnswerSection` enriched with citation metadata."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: AnnotatedText
    detailed_explanation: AnnotatedText
    supporting_evidence: List[EvidenceChunk] = Field(default_factory=list)
    key_regulatory_references: List[str] = Field(default_factory=list)
    references: List[ReferenceEntry] = Field(
        default_factory=list, description="Deduplicated reference list."
    )
    citation_map: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of claim_id → citation_id (primary citation).",
    )


# ─── Coverage / Validation ──────────────────────────────────────────────────


class CitationCoverage(BaseModel):
    """Coverage statistics — used to validate that every claim is cited."""

    model_config = ConfigDict(extra="forbid")

    total_claims: int = Field(0, ge=0)
    cited_claims: int = Field(0, ge=0)
    uncited_claims: int = Field(0, ge=0)
    coverage_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="cited_claims / total_claims (1.0 means full coverage).",
    )
    uncited_claim_ids: List[str] = Field(default_factory=list)
    unique_references: int = Field(0, ge=0)


class CitationMetadata(BaseModel):
    """Telemetry attached to every citation response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = Field(0.0, ge=0.0)
    chunks_used: int = Field(0, ge=0, description="Number of input chunks.")
    claims_extracted: int = Field(0, ge=0)
    citations_emitted: int = Field(0, ge=0)
    style: CitationStyle = Field(CitationStyle.BRACKETED_SOURCE)


# ─── Request / Response ─────────────────────────────────────────────────────


class CitationRequest(BaseModel):
    """Request payload for the citation endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048)
    answer: AnswerSection = Field(..., description="Structured answer (from Module 5.1).")
    chunks: List[RetrievedChunk] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Retrieved chunks that grounded the answer.",
    )
    style: CitationStyle = Field(
        CitationStyle.BRACKETED_SOURCE,
        description="Inline citation style.",
    )
    min_similarity: float = Field(
        0.05,
        ge=0.0,
        le=1.0,
        description="Minimum similarity to accept a citation; below this the claim is marked uncited.",
    )
    require_full_coverage: bool = Field(
        False,
        description="If true, the response flags partial coverage in metadata but does not raise.",
    )
    include_paragraph: bool = Field(
        True,
        description="Extract a paragraph locator from chunk content where possible.",
    )


class CitationResponse(BaseModel):
    """Full response envelope for the citation endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str
    annotated_answer: AnnotatedAnswer
    coverage: CitationCoverage
    metadata: CitationMetadata


# ─── Marker Formatting (shared helper) ──────────────────────────────────────


_DOC_TYPE_PATTERNS: List[tuple[re.Pattern[str], str]] = [
    (re.compile(r"master\s+direction", re.IGNORECASE), "Master Direction"),
    (re.compile(r"master\s+circular", re.IGNORECASE), "Master Circular"),
    (re.compile(r"circular", re.IGNORECASE), "Circular"),
    (re.compile(r"notification", re.IGNORECASE), "Notification"),
    (re.compile(r"act", re.IGNORECASE), "Act"),
    (re.compile(r"regulation", re.IGNORECASE), "Regulation"),
    (re.compile(r"guideline", re.IGNORECASE), "Guidelines"),
    (re.compile(r"direction", re.IGNORECASE), "Direction"),
]


_CIRCULAR_NUMBER_RE = re.compile(
    r"\b("
    r"[A-Z]{2,6}(?:/[\w\-]+){1,3}/\d{1,5}"  # RBI/2024-25/123, SEBI/HO/MIRSD-SEC-1/2024, MD/2016/1
    r"|[A-Z]+/\d{4}-\d{2,5}"  # RBI/2024-25
    r"|\d+/\d{4}"  # 12/2024
    r")\b"
)


def extract_circular_number(text: str) -> Optional[str]:
    """Best-effort circular / notification number extractor.

    Examples matched:
      * ``12/2024``
      * ``MD/2016/1``
      * ``RBI/2024-25/123``
      * ``CIR/MIRSD/12/2024``
    """
    if not text:
        return None
    m = _CIRCULAR_NUMBER_RE.search(text)
    return m.group(1) if m else None


def detect_document_type(text: str) -> Optional[str]:
    """Detect the document type from a title or text snippet."""
    if not text:
        return None
    for pattern, label in _DOC_TYPE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def format_inline_marker(
    *,
    source: Optional[str],
    document_type: Optional[str],
    document_title: Optional[str],
    circular_number: Optional[str],
    page_number: Optional[int],
) -> str:
    """Build an inline marker like ``[RBI Circular 12/2024 | Page 8]``.

    Components are joined greedily in this order:

      1. ``<source>``               (e.g. "RBI", "SEBI")
      2. ``<document_type>``         (e.g. "Circular", "Master Direction")
      3. ``<circular_number>`` OR   (e.g. "12/2024")
         ``<document_title>``        (fallback if no number)

    ``| Page <page_number>`` is appended when a page is known.
    """
    parts: List[str] = []
    src = (source or "").strip()
    if src:
        parts.append(src)

    if circular_number:
        if document_type:
            parts.append(f"{document_type} {circular_number}")
        else:
            parts.append(circular_number)
    elif document_title:
        title = document_title.strip()
        # Avoid duplicating the regulator prefix when the title already
        # starts with the source name (e.g. "SEBI Master Direction ...").
        if src and title.lower().startswith(src.lower() + " "):
            title = title[len(src) + 1 :].strip()
        if document_type and title.lower().startswith(document_type.lower() + " "):
            # Title is already self-describing; use it as-is.
            parts.append(title)
        elif document_type:
            parts.append(f"{document_type} {title}")
        else:
            parts.append(title)
    elif document_type:
        parts.append(document_type)

    body = " ".join(p for p in parts if p).strip()
    body = re.sub(r"\s+", " ", body)
    if not body:
        body = "Unknown Source"
    if page_number is not None:
        return f"[{body} | Page {page_number}]"
    return f"[{body}]"


__all__ = [
    "CitationStyle",
    "ReferenceEntry",
    "InlineCitation",
    "Claim",
    "AnnotatedText",
    "AnnotatedAnswer",
    "CitationCoverage",
    "CitationMetadata",
    "CitationRequest",
    "CitationResponse",
    "extract_circular_number",
    "detect_document_type",
    "format_inline_marker",
]
