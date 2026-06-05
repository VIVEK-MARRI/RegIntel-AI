"""Module 6.1 — Regulatory Copilot Service.

The :class:`CopilotService` is the top-level orchestrator for the
Regulatory Copilot.  It composes:

* :class:`ResponseOrchestrator` (Milestone 5.6) — runs the full
  answer intelligence pipeline.
* :class:`MemoryService` (Module 6.3) — short-term / long-term /
  retrieval memory.
* :class:`ConversationService` (Module 6.2) — persistent multi-turn
  history.
* :class:`AnswerAnalyticsService` (Milestone 5.8) — observability.

Three copilot modes are supported:

* ``ANSWER``     — full orchestrated answer (the default).
* ``SUMMARISE``  — produce a summary of the relevant context /
  conversation history without invoking the answer generator.
* ``SEARCH``     — return ranked memory hits as sources only.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.schemas.answer_generation import RetrievedChunk
from app.schemas.copilot import (
    CopilotMessage,
    CopilotMode,
    CopilotRequest,
    CopilotResponse,
)
from app.schemas.conversation import AppendMessageRequest, Role
from app.schemas.orchestrator import (
    FinalAnswerResponse,
    OrchestratorMetadata,
    OrchestratorRequest,
    VerificationMethod,
)
from app.services.conversation import ConversationService
from app.services.memory import MemoryService
from app.services.observability import track_request
from app.services.orchestrator import ResponseBuilder, ResponseOrchestrator

logger = logging.getLogger(__name__)


# ─── Copilot service ────────────────────────────────────────────────────


class CopilotService:
    """Top-level service exposed via DI for Module 6.1."""

    def __init__(
        self,
        *,
        orchestrator: Optional[ResponseOrchestrator] = None,
        memory: Optional[MemoryService] = None,
        conversation: Optional[ConversationService] = None,
        analytics: Optional[Any] = None,  # AnswerAnalyticsService (avoid circular import)
    ) -> None:
        self.orchestrator = orchestrator
        self.memory = memory
        self.conversation = conversation
        self.analytics = analytics

    # ── Public API ──────────────────────────────────────────────────────

    async def ask(self, request: CopilotRequest) -> CopilotResponse:
        """Execute a copilot query.

        Pipeline:

        1. Get-or-create a :class:`Conversation`.
        2. Build a :class:`MemoryContext` (long-term + retrieval).
        3. Dispatch by mode.
        4. Append user + assistant messages to the conversation.
        5. Record retrieval memory.
        6. Record analytics (if wired).
        """
        with track_request(endpoint="/api/v1/copilot/query", strategy="copilot"):
            start = time.perf_counter()
            # 1. Resolve conversation.
            conv = self.conversation.manager.get_or_create(
                request.conversation_id, user_id=request.user_id
            )
            request.conversation_id = conv.conversation_id

            # 2. Memory context (optional).
            if request.use_memory:
                memory_context = self.memory.manager.build_context(
                    query=request.query,
                    user_id=request.user_id,
                    conversation_id=conv.conversation_id,
                    top_k=request.memory_top_k,
                )
            else:
                from app.schemas.memory import MemoryContext  # local to avoid cycle
                memory_context = MemoryContext(memory_used=False)

            # 3. Dispatch by mode.
            if request.mode == CopilotMode.ANSWER:
                response = await self._answer_mode(
                    request=request,
                    conv=conv,
                    memory_context=memory_context,
                )
            elif request.mode == CopilotMode.SUMMARISE:
                response = self._summarise_mode(
                    request=request, conv=conv, memory_context=memory_context
                )
            elif request.mode == CopilotMode.SEARCH:
                response = self._search_mode(
                    request=request, memory_context=memory_context
                )
            else:
                raise ValueError(f"unknown copilot mode: {request.mode!r}")

            # Record latency.
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            response.latency_ms = elapsed_ms
            return response

    # ── Mode: ANSWER ────────────────────────────────────────────────────

    async def _answer_mode(
        self,
        *,
        request: CopilotRequest,
        conv: Any,
        memory_context: Any,
    ) -> CopilotResponse:
        chunks = self._resolve_chunks(request, memory_context)
        if not chunks:
            # Build an empty answer (degraded path) without invoking the
            # orchestrator: the orchestrator requires ≥1 chunk.
            return self._empty_answer(
                request=request, conv=conv, memory_context=memory_context,
                reason="no chunks available; orchestrator not invoked",
            )
        # Build the orchestrator request.
        verification = self._resolve_verification_method(
            request.verification_method
        )
        orchestrator_request = OrchestratorRequest(
            query=request.query,
            chunks=chunks,
            tone=request.tone,
            verification_method=verification,
            min_faithfulness=request.min_faithfulness,
        )
        final_response: FinalAnswerResponse = await self.orchestrator.answer(
            orchestrator_request
        )
        # Record analytics (best-effort).
        if self.analytics is not None:
            try:
                self.analytics.record(final_response, total_tokens=0)
            except Exception as exc:  # pragma: no cover
                logger.warning("Analytics record failed: %s", exc)
        # Record retrieval memory (best-effort).
        try:
            answer_text = final_response.answer.executive_summary or final_response.answer.detailed_explanation or ""
            self.memory.manager.record_retrieval(
                query=request.query,
                answer_text=answer_text,
                user_id=request.user_id,
                conversation_id=conv.conversation_id,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Memory record_retrieval failed: %s", exc)
        # Build CopilotResponse.
        return self._build_copilot_response(
            request=request,
            conv=conv,
            final_response=final_response,
            memory_context=memory_context,
        )

    def _empty_answer(
        self,
        *,
        request: CopilotRequest,
        conv: Any,
        memory_context: Any,
        reason: str,
    ) -> CopilotResponse:
        """Return a degraded ANSWER response when no chunks are available."""
        empty_meta = OrchestratorMetadata(
            request_id=request.request_id,
            model_used="",
            provider_used="",
            warnings=[reason],
        )
        # Still record the user + assistant message in the conversation.
        assistant_text = (
            "No grounded information was retrieved. Try a more specific "
            "query or provide context."
        )
        try:
            self.conversation.manager.append_user(
                conv.conversation_id, request.query
            )
            self.conversation.manager.append_assistant(
                conv.conversation_id,
                assistant_text,
                references={"request_id": request.request_id, "degraded": "true"},
            )
        except Exception:  # pragma: no cover
            pass
        history = [
            CopilotMessage(role=m.role.value, content=m.content, timestamp=m.timestamp)
            for m in conv.messages[-6:]
        ]
        return CopilotResponse(
            request_id=request.request_id,
            conversation_id=conv.conversation_id,
            user_id=request.user_id,
            query=request.query,
            mode=request.mode,
            answer={
                "executive_summary": assistant_text,
                "detailed_explanation": " ",
            },
            confidence_score=0.0,
            faithfulness_score=0.0,
            hallucination_detected=False,
            attribution_coverage_ratio=0.0,
            memory_used=memory_context.memory_used,
            memory_context=memory_context,
            history=history,
            metadata=empty_meta,
        )

    # ── Mode: SUMMARISE ─────────────────────────────────────────────────

    def _summarise_mode(
        self,
        *,
        request: CopilotRequest,
        conv: Any,
        memory_context: Any,
    ) -> CopilotResponse:
        # Use the conversation summary if present, otherwise a snapshot
        # of the last messages.
        parts: List[str] = []
        if conv.summary:
            parts.append(f"Summary so far: {conv.summary}")
        # Pull a few recent memory hits to inform the summary.
        if memory_context.long_term:
            parts.append("Long-term context:")
            for m in memory_context.long_term[:3]:
                parts.append(f"- {m.content}")
        if memory_context.retrieval:
            parts.append("Relevant past Q/A:")
            for hit in memory_context.retrieval[:3]:
                parts.append(f"- {hit.entry.content[:200]}")
        if not parts:
            summary_text = (
                f"No prior context for query: {request.query!r}."
            )
        else:
            summary_text = " ".join(parts)
        history = [
            CopilotMessage(role=m.role.value, content=m.content, timestamp=m.timestamp)
            for m in conv.messages[-6:]
        ]
        return CopilotResponse(
            request_id=request.request_id,
            conversation_id=conv.conversation_id,
            user_id=request.user_id,
            query=request.query,
            mode=request.mode,
            answer={"summary": summary_text},
            memory_used=memory_context.memory_used,
            memory_context=memory_context,
            history=history,
            metadata=OrchestratorMetadata(
                request_id=request.request_id,
                model_used="",
                provider_used="",
                warnings=["summarise mode: no answer generated"],
            ),
        )

    # ── Mode: SEARCH ────────────────────────────────────────────────────

    def _search_mode(
        self,
        *,
        request: CopilotRequest,
        memory_context: Any,
    ) -> CopilotResponse:
        # Convert retrieval hits into a list of "sources" (raw dicts).
        sources: List[Dict[str, Any]] = []
        for hit in memory_context.retrieval[: request.memory_top_k]:
            entry = hit.entry
            sources.append(
                {
                    "memory_id": entry.memory_id,
                    "content": entry.content,
                    "score": hit.score,
                    "tags": list(entry.tags),
                    "memory_type": entry.memory_type.value,
                    "created_at": entry.created_at.isoformat()
                    if entry.created_at
                    else None,
                }
            )
        return CopilotResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id or "",
            user_id=request.user_id,
            query=request.query,
            mode=request.mode,
            answer={"sources": sources},
            memory_used=memory_context.memory_used,
            memory_context=memory_context,
            metadata=OrchestratorMetadata(
                request_id=request.request_id,
                model_used="",
                provider_used="",
                warnings=["search mode: no answer generated"],
            ),
        )

    # ── Helpers ─────────────────────────────────────────────────────────

    def _resolve_chunks(
        self, request: CopilotRequest, memory_context: Any
    ) -> List[RetrievedChunk]:
        """Resolve chunks: caller-provided first, else synthesise from
        retrieval memory hits."""
        if request.chunks:
            return [RetrievedChunk.model_validate(c) for c in request.chunks]
        # Synthesise from retrieval memory.
        if memory_context.retrieval:
            out: List[RetrievedChunk] = []
            for idx, hit in enumerate(memory_context.retrieval, start=1):
                entry = hit.entry
                out.append(
                    RetrievedChunk(
                        chunk_id=entry.memory_id,
                        document_id=(
                            entry.metadata.get("document_id")
                            if entry.metadata
                            else None
                        )
                        or f"mem-{idx}",
                        content=entry.content[:4096],
                        score=hit.score,
                        rank=idx,
                    )
                )
            return out
        return []

    def _resolve_verification_method(self, value: str) -> VerificationMethod:
        try:
            return VerificationMethod(value)
        except ValueError:
            return VerificationMethod.LEXICAL

    def _build_copilot_response(
        self,
        *,
        request: CopilotRequest,
        conv: Any,
        final_response: FinalAnswerResponse,
        memory_context: Any,
    ) -> CopilotResponse:
        # Append the user + assistant messages to the conversation.
        self._append_user_assistant(conv, request, final_response)
        # Echo the recent history.
        history = [
            CopilotMessage(
                role=m.role.value, content=m.content, timestamp=m.timestamp
            )
            for m in conv.messages[-6:]
        ]
        # Project FinalAnswerResponse to the CopilotResponse shape.
        answer_dict = ResponseBuilder.to_dict(final_response)
        return CopilotResponse(
            request_id=request.request_id,
            conversation_id=conv.conversation_id,
            user_id=request.user_id,
            query=request.query,
            mode=request.mode,
            answer=answer_dict.get("answer"),
            citations=final_response.citations,
            confidence_score=final_response.confidence_score,
            confidence_level=final_response.confidence_level,
            faithfulness_score=final_response.faithfulness_score,
            hallucination_detected=final_response.hallucination_detected,
            hallucination_risk_level=final_response.hallucination_risk_level,
            sources=final_response.source_attributions,
            attribution_coverage_ratio=final_response.attribution_coverage_ratio,
            memory_used=memory_context.memory_used,
            memory_context=memory_context,
            history=history,
            metadata=final_response.metadata,
        )

    def _append_user_assistant(
        self,
        conv: Any,
        request: CopilotRequest,
        final_response: FinalAnswerResponse,
    ) -> None:
        """Append the user query and the assistant answer to the
        conversation history (best-effort)."""
        try:
            self.conversation.manager.append_user(
                conv.conversation_id, request.query
            )
            assistant_text = (
                final_response.answer.executive_summary
                or final_response.answer.detailed_explanation
                or ""
            )
            self.conversation.manager.append_assistant(
                conv.conversation_id,
                assistant_text,
                references={
                    "request_id": request.request_id,
                    "confidence": str(round(final_response.confidence_score, 3)),
                },
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to append messages: %s", exc)


# ─── Controller (HTTP-shaped wrapper) ──────────────────────────────────


class CopilotController:
    """Thin validation wrapper for the API layer."""

    def __init__(self, *, service: CopilotService) -> None:
        self.service = service

    async def handle(self, request: CopilotRequest) -> CopilotResponse:
        if not request.query.strip():
            raise ValueError("query must be a non-empty string")
        return await self.service.ask(request)


# ─── Default factory ───────────────────────────────────────────────────


def build_default_copilot_service(
    *,
    orchestrator: Optional[ResponseOrchestrator] = None,
    memory: Optional[MemoryService] = None,
    conversation: Optional[ConversationService] = None,
    analytics: Optional[Any] = None,
) -> CopilotService:
    return CopilotService(
        orchestrator=orchestrator,
        memory=memory,
        conversation=conversation,
        analytics=analytics,
    )


__all__ = [
    "CopilotController",
    "CopilotService",
    "build_default_copilot_service",
]
