"""PromptBuilder for the Answer Generation Engine.

Converts a user query and a list of retrieved chunks into a structured,
source-aware prompt pair (system + user).  The output is deterministic
and the prompt enforces a canonical answer format::

    Executive Summary: ...
    Detailed Explanation: ...
    Supporting Evidence: [<chunk_id>, <chunk_id>, ...]
    Key Regulatory References: ...

The builder is stateless and safe to share across requests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from app.schemas.answer_generation import (
    AnswerTone,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)


_SYSTEM_PROMPTS: dict[AnswerTone, str] = {
    AnswerTone.REGULATORY: (
        "You are a senior regulatory compliance analyst for Indian financial "
        "regulators (RBI, SEBI, IRDAI, PFRDA).  You answer questions strictly "
        "from the provided regulatory chunks.  Do not invent rules, "
        "circulars, sections, or dates.  If the chunks are insufficient, say "
        "Always format your answer with these sections, in "
        "this order, using the exact headers shown below (Markdown style, "
        "with ## prefix) and a blank line between them:\n\n"
        "## Executive Summary\n<one paragraph>\n"
        "## Detailed Explanation\n<multi-paragraph grounded analysis>\n"
        "## Supporting Evidence\n<comma-separated list of chunk ids that back "
        "each claim, e.g. [chunk-id-1, chunk-id-2]>\n"
        "## Key Regulatory References\n<comma-separated list of acts, "
        "circulars, master directions, or sections explicitly mentioned in "
        "the chunks>"
    ),
    AnswerTone.EXPLANATORY: (
        "You are a regulatory analyst who explains Indian financial rules "
        "(RBI / SEBI / IRDAI / PFRDA) in plain English.  Answer only from "
        "the supplied regulatory chunks.  Use the same four-section format "
        "(Executive Summary, Detailed Explanation, Supporting Evidence, "
        "Key Regulatory References) with the exact headers."
    ),
    AnswerTone.CONCISE: (
        "You are a regulatory analyst who answers briefly and to the point.  "
        "Use the same four-section format (Executive Summary, Detailed "
        "Explanation, Supporting Evidence, Key Regulatory References) with "
        "the exact headers.  Keep total length under 200 words unless more "
        "detail is required."
    ),
}


@dataclass
class PromptBundle:
    """System + user prompt pair ready for a provider call."""

    system_prompt: str
    user_prompt: str
    chunk_ids: List[str]
    truncated: int = 0


class PromptBuilder:
    """Builds prompts from queries and retrieved chunks.

    Parameters
    ----------
    tone:
        Output tone preset (regulatory / explanatory / concise).
    context_token_budget:
        Soft cap on prompt tokens reserved for chunk context.  Chunks
        are dropped from the tail once the budget is exhausted.
    max_excerpt_chars:
        Maximum characters per chunk excerpt included in the prompt.
    """

    _TOKEN_RE = re.compile(r"\s+")

    def __init__(
        self,
        *,
        tone: AnswerTone = AnswerTone.REGULATORY,
        context_token_budget: int = 6000,
        max_excerpt_chars: int = 1200,
    ) -> None:
        self.tone = tone
        self.context_token_budget = max(64, int(context_token_budget))
        self.max_excerpt_chars = max(80, int(max_excerpt_chars))

    # ── Public API ──────────────────────────────────────────────────────────

    def build(self, query: str, chunks: Sequence[RetrievedChunk]) -> PromptBundle:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not chunks:
            raise ValueError("at least one retrieved chunk is required")

        system_prompt = self._build_system_prompt()
        truncated = 0
        kept: List[RetrievedChunk] = []
        remaining = self.context_token_budget

        for chunk in chunks:
            excerpt = chunk.to_provider_excerpt(self.max_excerpt_chars)
            approx_tokens = self._approx_tokens(excerpt)
            if approx_tokens > remaining and kept:
                truncated += 1
                continue
            kept.append(chunk)
            remaining -= approx_tokens

        user_prompt = self._build_user_prompt(query, kept)
        return PromptBundle(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            chunk_ids=[c.chunk_id for c in kept],
            truncated=truncated,
        )

    # ── Internals ──────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return _SYSTEM_PROMPTS[self.tone]

    @staticmethod
    def _approx_tokens(text: str) -> int:
        # Cheap approximation: ~0.75 tokens per whitespace-delimited word.
        if not text:
            return 0
        return max(1, int(len(PromptBuilder._TOKEN_RE.findall(text)) * 1.3))

    def _build_user_prompt(
        self, query: str, chunks: Iterable[RetrievedChunk]
    ) -> str:
        chunks = list(chunks)
        header = (
            f"Question:\n{query.strip()}\n\n"
            f"Retrieved regulatory context ({len(chunks)} chunk"
            f"{'s' if len(chunks) != 1 else ''}):"
        )
        body_parts: List[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            body_parts.append(self._format_chunk(idx, chunk))
        body = "\n\n".join(body_parts) if body_parts else "(no chunks)"
        return f"{header}\n\n{body}\n\nNow produce the answer using the four sections."

    @staticmethod
    def _format_chunk(idx: int, chunk: RetrievedChunk) -> str:
        lines: List[str] = [f"[{idx}] Chunk ID: {chunk.chunk_id}"]
        if chunk.source:
            lines.append(f"Source: {chunk.source.value}")
        if chunk.document_title:
            lines.append(f"Document: {chunk.document_title}")
        if chunk.section:
            lines.append(f"Section: {chunk.section}")
        if chunk.subsection:
            lines.append(f"Subsection: {chunk.subsection}")
        if chunk.page_number is not None:
            lines.append(f"Page: {chunk.page_number}")
        if chunk.score:
            lines.append(f"Score: {chunk.score:.4f}")
        excerpt = chunk.to_provider_excerpt(1200)
        lines.append(f"Content: {excerpt}")
        return "\n".join(lines)
