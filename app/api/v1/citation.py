"""Module 5.2 — Citation Engine API Layer.

Endpoints (mounted under ``/api/v1``):

* ``POST /citation/cite``   — annotate an :class:`AnswerSection` with
  inline citations, a reference list, and coverage stats.

The endpoint is fully deterministic and synchronous — there is no LLM
involved in the citation engine itself; it just maps claims to the
retrieved chunks that already grounded the answer.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_citation_service
from app.schemas.citation import (
    CitationRequest,
    CitationResponse,
    ReferenceEntry,
)
from app.services.citation import CitationService
from app.services.observability import track_request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["citation"])


# ─── POST /citation/cite ─────────────────────────────────────────────────────


@router.post(
    "/citation/cite",
    response_model=CitationResponse,
    status_code=status.HTTP_200_OK,
    summary="Annotate an answer with inline citations and a reference list",
)
async def cite_answer(
    request: CitationRequest,
    service: CitationService = Depends(get_citation_service),
) -> CitationResponse:
    """Run the citation engine.

    The handler:
      1. Validates the request (Pydantic).
      2. Wraps the call in ``track_request`` for observability.
      3. Delegates to :meth:`CitationService.cite`.
      4. Returns the structured :class:`CitationResponse`.
    """
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one chunk is required for citation.",
        )

    with track_request(
        endpoint="/api/v1/citation/cite",
        strategy="citation",
    ) as ctx:
        try:
            response = service.cite(request)
        except ValueError as exc:
            logger.warning("Validation error in citation: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception as exc:
            logger.exception("Citation engine failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Citation engine failed: {exc}",
            ) from exc
        try:
            ctx.rerank_used = False  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    logger.info(
        "citation.complete query=%s claims=%d cited=%d coverage=%.2f references=%d",
        request.query[:60],
        response.coverage.total_claims,
        response.coverage.cited_claims,
        response.coverage.coverage_ratio,
        response.coverage.unique_references,
    )
    return response


# ─── Convenience: list references (read-only) ───────────────────────────────


@router.get(
    "/citation/health",
    status_code=status.HTTP_200_OK,
    summary="Health check for the citation engine",
)
async def citation_health() -> dict:
    """Tiny liveness probe — the engine has no external dependencies."""
    return {"status": "ok", "module": "5.2-citation-engine"}


__all__ = ["router"]
