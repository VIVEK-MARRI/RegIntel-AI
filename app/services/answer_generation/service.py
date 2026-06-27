"""AnswerGeneratorService — Module 5.1 orchestrator.

Glues a :class:`PromptBuilder` to a :class:`BaseLLMProvider`, enforces
the canonical four-section answer format, and exposes async
``generate`` + ``stream`` entry points.  The service is dependency-
injected and integrates with the project's observability layer
(``track_request``).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from app.schemas.answer_generation import (
    AnswerGenerationRequest,
    AnswerGenerationResponse,
    AnswerMetadata,
    AnswerSection,
    AnswerStreamChunk,
    AnswerTone,
    EvidenceChunk,
    LLMProviderName,
    RetrievedChunk,
)
from app.services.answer_generation.providers import (
    BaseLLMProvider,
    LLMResponse,
    MockLLMProvider,
    get_provider,
)
from app.services.answer_generation.prompt_builder import (
    PromptBuilder,
    PromptBundle,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Telemetry ──────────────────────────────────────────────────────────────


@dataclass
class AnswerGeneratorTelemetry:
    """Lightweight telemetry attached to every generation call."""

    request_id: str = ""
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    chunks_used: int = 0
    sources: List[str] = field(default_factory=list)
    truncated: int = 0
    stream: bool = False
    tone: str = "regulatory"


# ─── Section Parsing ────────────────────────────────────────────────────────


# Match section headers in either colon (e.g. "Executive Summary:") or
# Markdown (e.g. "### Executive Summary" or "## Executive Summary:") format.
_HDR = r"^\s*(?:#{1,6}\s+)?"
_FMT = r"\s*:?\s*(.*)$"
_SECTION_PATTERNS = {
    "executive_summary": re.compile(
        _HDR + r"executive\s+summary" + _FMT,
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    ),
    "detailed_explanation": re.compile(
        _HDR + r"detailed\s+explanation" + _FMT,
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    ),
    "supporting_evidence": re.compile(
        _HDR + r"supporting\s+evidence" + _FMT,
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    ),
    "key_regulatory_references": re.compile(
        _HDR + r"key\s+regulatory\s+references" + _FMT,
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    ),
}


def parse_sections(raw_text: str) -> Dict[str, str]:
    """Split a canonical LLM response into the four required sections.

    Falls back to:
      * executive_summary = first paragraph
      * detailed_explanation = remainder
      * supporting_evidence = empty
      * key_regulatory_references = empty
    if the model didn't honour the format.
    """
    if not raw_text:
        return {
            "executive_summary": "",
            "detailed_explanation": "",
            "supporting_evidence": "",
            "key_regulatory_references": "",
        }

    # Find all section header positions.
    matches: List[Dict[str, Any]] = []
    for name, pattern in _SECTION_PATTERNS.items():
        m = pattern.search(raw_text)
        if m:
            matches.append({
                "name": name,
                "header_start": m.start(),
                "body_start": m.start(1),
            })
    matches.sort(key=lambda m: m["header_start"])

    if not matches:
        # Fallback: first paragraph = summary, rest = detail.
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [raw_text.strip()]
        return {
            "executive_summary": paragraphs[0],
            "detailed_explanation": "\n\n".join(paragraphs[1:]) if len(paragraphs) > 1 else "",
            "supporting_evidence": "",
            "key_regulatory_references": "",
        }

    sections: Dict[str, str] = {
        "executive_summary": "",
        "detailed_explanation": "",
        "supporting_evidence": "",
        "key_regulatory_references": "",
    }
    for i, m in enumerate(matches):
        next_header = (
            matches[i + 1]["header_start"] if i + 1 < len(matches) else len(raw_text)
        )
        body = raw_text[m["body_start"] : next_header].strip()
        sections[m["name"]] = body

    # If the model omitted section headers, assign remaining text to the
    # first missing section.
    found = {m["name"] for m in matches}
    for section_name in ("detailed_explanation", "supporting_evidence", "key_regulatory_references"):
        if section_name in found:
            continue
        if sections["executive_summary"] and section_name == "detailed_explanation":
            # Everything after the exec summary body goes to detailed.
            es_idx = matches[0]["body_start"]
            rest = raw_text[es_idx:].strip()
            # Remove the exec summary body from this rest to avoid duplication.
            es_body_len = len(sections["executive_summary"])
            rest = rest[es_body_len:].strip()
            if rest:
                sections["detailed_explanation"] = rest
                break
        break

    return sections


def _extract_evidence_ids(text: str) -> List[str]:
    """Extract chunk ids from a 'Supporting Evidence:' section."""
    if not text:
        return []
    # Accept either [id-1, id-2] or "id-1, id-2" formats.
    bracket = re.search(r"\[([^\[\]]+)\]", text)
    if bracket:
        body = bracket.group(1)
    else:
        # Strip the header prefix if present.
        body = re.sub(r"^.*?:", "", text, count=1)
    ids = [piece.strip().strip("'\"`") for piece in body.split(",")]
    return [piece for piece in ids if piece]


def _extract_references(text: str) -> List[str]:
    """Extract regulatory references from a comma / newline separated list."""
    if not text:
        return []
    body = text.replace("\n", ",")
    items = [piece.strip(" -*•\t") for piece in body.split(",")]
    return [item for item in items if item]


# ─── Service ────────────────────────────────────────────────────────────────


class AnswerGeneratorService:
    """Top-level orchestrator.  Inject a provider and a prompt builder."""

    def __init__(
        self,
        *,
        provider: BaseLLMProvider,
        prompt_builder: Optional[PromptBuilder] = None,
        default_tone: AnswerTone = AnswerTone.REGULATORY,
    ) -> None:
        self.provider = provider
        self.prompt_builder = prompt_builder or PromptBuilder(tone=default_tone)
        self.default_tone = default_tone

    # ── Non-streaming ───────────────────────────────────────────────────────

    async def generate(
        self, request: AnswerGenerationRequest
    ) -> AnswerGenerationResponse:
        if not request.chunks:
            raise ValueError("AnswerGenerationRequest requires at least one chunk")

        tone = request.tone
        builder = self._builder_for_tone(tone)
        bundle = builder.build(request.query, request.chunks)
        request_id = uuid.uuid4().hex

        with track_request(
            endpoint="/api/v1/answer/generate",
            strategy="answer_generation",
        ) as ctx:
            t0 = time.perf_counter()
            try:
                response = await self.provider.generate(
                    system_prompt=bundle.system_prompt,
                    user_prompt=bundle.user_prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                )
            except Exception:
                logger.exception(
                    "LLM provider %s failed for request %s",
                    self.provider.name,
                    request_id,
                )
                raise
            latency_ms = (time.perf_counter() - t0) * 1000.0

        answer = self._build_answer_section(
            raw_text=response.text, chunks=request.chunks
        )
        metadata = AnswerMetadata(
            provider=response.provider or self.provider.name.value,
            model=response.model or self.provider.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            latency_ms=latency_ms,
            chunks_used=len(bundle.chunk_ids),
            sources=self._distinct_sources(request.chunks),
            request_id=request_id,
        )
        try:
            ctx.rerank_used = False  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

        return AnswerGenerationResponse(
            query=request.query,
            answer=answer,
            metadata=metadata,
            raw_response=response.text if request.include_raw else None,
        )

    # ── Streaming ──────────────────────────────────────────────────────────

    async def stream(
        self, request: AnswerGenerationRequest
    ) -> AsyncIterator[AnswerStreamChunk]:
        bundle = self._builder_for_tone(request.tone).build(
            request.query, request.chunks
        )
        request_id = uuid.uuid4().hex

        yield AnswerStreamChunk(event="start")

        buf: List[str] = []
        t0 = time.perf_counter()
        try:
            async for piece in self.provider.stream(
                system_prompt=bundle.system_prompt,
                user_prompt=bundle.user_prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ):
                buf.append(piece)
                yield AnswerStreamChunk(event="token", delta=piece)
        except Exception as exc:
            logger.exception("Streaming provider %s failed", self.provider.name)
            yield AnswerStreamChunk(event="error", error=str(exc))
            return

        latency_ms = (time.perf_counter() - t0) * 1000.0
        raw_text = "".join(buf)
        answer = self._build_answer_section(raw_text=raw_text, chunks=request.chunks)
        yield AnswerStreamChunk(event="section", section=answer)
        yield AnswerStreamChunk(
            event="end",
            metadata=AnswerMetadata(
                provider=self.provider.name.value,
                model=self.provider.model,
                prompt_tokens=max(1, len(bundle.user_prompt.split())),
                completion_tokens=max(1, len(raw_text.split())),
                total_tokens=max(1, len(bundle.user_prompt.split()))
                + max(1, len(raw_text.split())),
                latency_ms=latency_ms,
                chunks_used=len(bundle.chunk_ids),
                sources=self._distinct_sources(request.chunks),
                request_id=request_id,
            ),
        )

    # ── Convenience wrappers ───────────────────────────────────────────────

    async def generate_from_chunks(
        self,
        *,
        query: str,
        chunks: List[RetrievedChunk],
        provider: Optional[LLMProviderName] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tone: Optional[AnswerTone] = None,
        include_raw: bool = False,
    ) -> AnswerGenerationResponse:
        """Single-call convenience wrapper.

        A new request is built from the arguments; useful for callers
        that don't want to construct an :class:`AnswerGenerationRequest`.
        """
        if not chunks:
            raise ValueError("generate_from_chunks requires at least one chunk")
        request = AnswerGenerationRequest(
            query=query,
            chunks=chunks,
            provider=provider or LLMProviderName(self.provider.name.value),
            model=model or self.provider.model,
            max_tokens=max_tokens or 1200,
            temperature=temperature if temperature is not None else 0.1,
            tone=tone or self.default_tone,
            stream=False,
            include_raw=include_raw,
        )
        return await self.generate(request)

    # ── Internals ──────────────────────────────────────────────────────────

    def _builder_for_tone(self, tone: AnswerTone) -> PromptBuilder:
        if tone == self.prompt_builder.tone:
            return self.prompt_builder
        return PromptBuilder(
            tone=tone,
            context_token_budget=self.prompt_builder.context_token_budget,
            max_excerpt_chars=self.prompt_builder.max_excerpt_chars,
        )

    def _build_answer_section(
        self, *, raw_text: str, chunks: List[RetrievedChunk]
    ) -> AnswerSection:
        sections = parse_sections(raw_text)

        evidence_ids = _extract_evidence_ids(sections["supporting_evidence"])
        chunk_index = {c.chunk_id: c for c in chunks}
        # If the model didn't enumerate evidence, default to the top-K.
        if not evidence_ids:
            evidence_ids = list(chunk_index.keys())[: min(5, len(chunk_index))]

        evidence: List[EvidenceChunk] = []
        for cid in evidence_ids:
            chunk = chunk_index.get(cid)
            if chunk is None:
                # Tolerate the model inventing ids – skip silently.
                continue
            evidence.append(
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    source=chunk.source.value if chunk.source else None,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    excerpt=chunk.to_provider_excerpt(240),
                )
            )

        references = _extract_references(sections["key_regulatory_references"])

        # Guarantee non-empty sections – the schema requires min_length=1.
        executive = sections["executive_summary"].strip() or (
            "Executive summary could not be extracted from the model output."
        )
        detailed = sections["detailed_explanation"].strip() or (
            "Detailed explanation could not be extracted from the model output."
        )

        return AnswerSection(
            executive_summary=executive,
            detailed_explanation=detailed,
            supporting_evidence=evidence,
            key_regulatory_references=references,
        )

    @staticmethod
    def _distinct_sources(chunks: List[RetrievedChunk]) -> List[str]:
        seen: List[str] = []
        for c in chunks:
            label = c.source.value if c.source is not None else "UNKNOWN"
            if label not in seen:
                seen.append(label)
        return seen


# ─── Factory ────────────────────────────────────────────────────────────────


def build_default_service(
    *,
    provider: LLMProviderName = LLMProviderName.MOCK,
    model: str = "mock-default",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    timeout: float = 30.0,
    context_token_budget: int = 6000,
    tone: AnswerTone = AnswerTone.REGULATORY,
) -> AnswerGeneratorService:
    """Construct a fully-wired :class:`AnswerGeneratorService`."""
    prov = get_provider(
        provider, model=model, api_key=api_key, api_base=api_base, timeout=timeout
    )
    builder = PromptBuilder(
        tone=tone, context_token_budget=context_token_budget
    )
    return AnswerGeneratorService(
        provider=prov, prompt_builder=builder, default_tone=tone
    )


__all__ = [
    "AnswerGeneratorService",
    "AnswerGeneratorTelemetry",
    "build_default_service",
    "parse_sections",
    "MockLLMProvider",  # re-exported for tests
]
