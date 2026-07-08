"""Module 5.1 — Answer Generation API contracts.

Defines the Pydantic v2 schemas for the Answer Generation Engine.  These
contracts describe the wire format of the request / response exchanged
between the API layer and downstream LLM providers.  They are
intentionally separate from internal service-layer schemas so the
public API surface can evolve independently.

Generation flow::

    query
      ↓
    retrieved chunks
      ↓
    PromptBuilder
      ↓
    LLM Provider (OpenAI / Gemini / LiteLLM / Mock)
      ↓
    AnswerSection
      ↓
    AnswerGenerationResponse

Design notes
------------
* The engine never rebuilds retrieval — it accepts the chunk objects
  produced by the hybrid retrieval layer and treats them as read-only
  evidence.
* The answer is structured (Executive Summary / Detailed Explanation /
  Supporting Evidence / Key Regulatory References) so downstream
  consumers can render it in a consistent way.
* Generation is async and streaming-ready.  ``AnswerGenerationRequest``
  carries a ``stream`` flag; the response envelope stays identical for
  non-streaming callers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import SourceEnum


# ─── Enumerations ─────────────────────────────────────────────────────────────


class LLMProviderName(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    GEMINI = "gemini"
    LITELLM = "litellm"
    MOCK = "mock"


class AnswerTone(str, Enum):
    """Answer generation tone preset."""

    REGULATORY = "regulatory"  # Formal, citation-style
    EXPLANATORY = "explanatory"  # Plain-language for non-experts
    CONCISE = "concise"  # Brief executive answer


# ─── Input Models ─────────────────────────────────────────────────────────────


class RetrievedChunk(BaseModel):
    """A single retrieved chunk fed into the answer generator.

    The schema is the public contract for retrieval outputs; it accepts
    the canonical fields produced by both the dense and BM25 retrievers.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="UUID of the matched chunk.")
    document_id: str = Field(..., description="UUID of the parent document.")
    content: str = Field(..., min_length=1, description="Text content of the chunk.")
    score: float = Field(
        ...,
        ge=0.0,
        description="Retrieval / reranker relevance score.",
    )
    source: Optional[SourceEnum] = Field(
        None, description="Regulator source (RBI / SEBI)."
    )
    page_number: Optional[int] = Field(
        None, ge=0, description="Page number the chunk was extracted from."
    )
    section: Optional[str] = Field(None, description="Section title.")
    subsection: Optional[str] = Field(None, description="Subsection title.")
    document_title: Optional[str] = Field(
        None, description="Title of the parent document."
    )
    rank: Optional[int] = Field(
        None, ge=1, description="1-indexed rank from the retriever."
    )

    def to_provider_excerpt(self, max_chars: int = 500) -> str:
        """Return a short, source-tagged excerpt for prompt injection."""
        text = self.content.strip().replace("\n", " ")
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return text


class AnswerGenerationRequest(BaseModel):
    """Request payload for ``POST /api/v1/answer/generate``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048, description="User question.")
    chunks: List[RetrievedChunk] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Retrieved chunks to ground the answer in.",
    )
    provider: LLMProviderName = Field(
        LLMProviderName.MOCK, description="LLM provider to use."
    )
    model: str = Field(
        "mock-default",
        description="Model identifier passed to the provider.",
    )
    max_tokens: int = Field(1200, ge=64, le=8000, description="Generation budget.")
    temperature: float = Field(0.1, ge=0.0, le=2.0, description="Sampling temperature.")
    tone: AnswerTone = Field(AnswerTone.REGULATORY, description="Output tone preset.")
    stream: bool = Field(False, description="If true, return a streaming response.")
    include_raw: bool = Field(
        False, description="Include the raw LLM output in the response."
    )


# ─── Output Models ────────────────────────────────────────────────────────────


class EvidenceChunk(BaseModel):
    """A single piece of supporting evidence attached to the answer."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="UUID of the source chunk.")
    document_id: str = Field(..., description="UUID of the source document.")
    source: Optional[str] = Field(None, description="Regulator source (RBI / SEBI).")
    page_number: Optional[int] = Field(
        None, description="Page number the chunk came from."
    )
    section: Optional[str] = Field(None, description="Section title.")
    excerpt: str = Field(..., description="Short excerpt from the chunk.")


class AnswerSection(BaseModel):
    """Structured answer broken into canonical sections."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(
        ...,
        min_length=1,
        description="One-paragraph high-level answer.",
    )
    detailed_explanation: str = Field(
        ...,
        min_length=1,
        description="Comprehensive, multi-paragraph explanation grounded in the chunks.",
    )
    supporting_evidence: List[EvidenceChunk] = Field(
        default_factory=list,
        description="Chunks that back the answer (chunk-level attribution).",
    )
    key_regulatory_references: List[str] = Field(
        default_factory=list,
        description="Notable regulatory acts, sections, or rules mentioned in the answer.",
    )


class AnswerMetadata(BaseModel):
    """Telemetry / observability fields attached to every answer."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(
        ..., description="Provider used (openai, gemini, litellm, mock)."
    )
    model: str = Field(..., description="Model identifier.")
    prompt_tokens: int = Field(0, ge=0, description="Approx. prompt tokens consumed.")
    completion_tokens: int = Field(
        0, ge=0, description="Approx. completion tokens generated."
    )
    total_tokens: int = Field(0, ge=0, description="Total tokens consumed.")
    latency_ms: float = Field(0.0, ge=0.0, description="Generation latency in ms.")
    chunks_used: int = Field(
        ..., ge=0, description="Number of chunks included in the prompt."
    )
    sources: List[str] = Field(
        default_factory=list,
        description="Distinct regulator sources represented in the answer.",
    )
    request_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Server-generated ID correlating logs and metrics.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Server timestamp at response time.",
    )


class AnswerGenerationResponse(BaseModel):
    """Full response envelope for the answer-generation endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="The original query.")
    answer: AnswerSection = Field(..., description="Structured answer.")
    metadata: AnswerMetadata = Field(..., description="Generation telemetry.")
    raw_response: Optional[str] = Field(
        None,
        description="Raw LLM output (only populated when ``include_raw=True``).",
    )


# ─── Streaming Models ─────────────────────────────────────────────────────────


class AnswerStreamChunk(BaseModel):
    """A single token / segment emitted by the streaming endpoint."""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(
        "token",
        description="Event type: 'start', 'token', 'section', 'evidence', 'end', 'error'.",
    )
    delta: Optional[str] = Field(
        None, description="Incremental text delta (for 'token' events)."
    )
    section: Optional[AnswerSection] = Field(
        None, description="Partial section payload (for 'section' events)."
    )
    metadata: Optional[AnswerMetadata] = Field(
        None, description="Final metadata (emitted on 'end')."
    )
    error: Optional[str] = Field(
        None, description="Error message (for 'error' events)."
    )
