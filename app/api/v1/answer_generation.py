r"""Module 5.1 — Answer Generation API Layer.

Endpoints (mounted under ``/api/v1``):

* ``POST /answer/generate``  — generate a structured answer from retrieved
  chunks (non-streaming; returns a full ``AnswerGenerationResponse``).
* ``POST /answer/stream``    — same inputs, emits Server-Sent Events:
  ``start`` → ``token``* → ``section`` → ``end`` (or ``error``).

Both endpoints:

* Are async-first.
* Validate the request body with the Pydantic v2 contract in
  ``app.schemas.answer_generation``.
* Wrap their work in the ``track_request`` observability context manager so
  per-request latency / error / strategy counters are always recorded.
* Delegate generation to :class:`AnswerGeneratorService`.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_answer_generator_service
from app.schemas.answer_generation import (
    AnswerGenerationRequest,
    AnswerGenerationResponse,
    AnswerStreamChunk,
)
from app.services.answer_generation import AnswerGeneratorService
from app.services.observability import track_request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["answer-generation"])


# ─── POST /answer/generate ───────────────────────────────────────────────────


@router.post(
    "/answer/generate",
    response_model=AnswerGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a structured answer from retrieved chunks",
)
async def generate_answer(
    request: AnswerGenerationRequest,
    service: AnswerGeneratorService = Depends(get_answer_generator_service),
) -> AnswerGenerationResponse:
    """Generate a non-streaming answer.

    The handler:
      1. Validates the request (Pydantic).
      2. Wraps the call in ``track_request`` for observability.
      3. Delegates to :meth:`AnswerGeneratorService.generate`.
      4. Returns the structured ``AnswerGenerationResponse``.
    """
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one chunk is required to generate an answer.",
        )

    with track_request(
        endpoint="/api/v1/answer/generate",
        strategy="answer_generation",
    ) as ctx:
        try:
            response = await service.generate(request)
        except ValueError as exc:
            logger.warning("Validation error in answer generation: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception as exc:
            logger.exception("Answer generation failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Answer generation failed: {exc}",
            ) from exc
        try:
            ctx.rerank_used = False  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    logger.info(
        "answer.generated provider=%s model=%s tokens=%d latency_ms=%.2f",
        response.metadata.provider,
        response.metadata.model,
        response.metadata.total_tokens,
        response.metadata.latency_ms,
    )
    return response


# ─── POST /answer/stream (SSE) ──────────────────────────────────────────────


@router.post(
    "/answer/stream",
    summary="Stream answer-generation tokens via Server-Sent Events",
    response_class=StreamingResponse,
)
async def stream_answer(
    request: AnswerGenerationRequest,
    service: AnswerGeneratorService = Depends(get_answer_generator_service),
) -> StreamingResponse:
    r"""Stream the generation as ``text/event-stream`` SSE.

    Event sequence:
        start   → token*   → section  → end
        (any failure short-circuits with an ``error`` event).
    """
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one chunk is required to stream an answer.",
        )

    async def event_source() -> AsyncIterator[bytes]:
        with track_request(
            endpoint="/api/v1/answer/stream",
            strategy="answer_generation_stream",
        ):
            try:
                async for chunk in service.stream(request):
                    payload = chunk.model_dump_json()
                    yield f"data: {payload}\n\n".encode("utf-8")
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Streaming failed: %s", exc)
                err = AnswerStreamChunk(event="error", error=str(exc)).model_dump_json()
                yield f"data: {err}\n\n".encode("utf-8")
        # SSE terminator.
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
