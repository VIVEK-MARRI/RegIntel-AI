"""Module 5.4 — Hallucination Guard API.

Endpoints
---------
* ``POST /api/v1/hallucination/verify`` — second-pass verification.
* ``GET  /api/v1/hallucination/health`` — health probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_hallucination_guard_service
from app.schemas.hallucination import (
    FaithfulnessRequest,
    FaithfulnessResponse,
    VerificationMethod,
)
from app.services.hallucination import HallucinationGuardService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hallucination", tags=["hallucination"])


@router.post(
    "/verify",
    response_model=FaithfulnessResponse,
    summary="Verify answer faithfulness against retrieved chunks",
)
async def verify(
    request: FaithfulnessRequest,
    service: HallucinationGuardService = Depends(get_hallucination_guard_service),
) -> FaithfulnessResponse:
    """Run second-pass verification on an answer + retrieved chunks.

    The verification method is selected via ``request.method``:

    * ``lexical`` — token-overlap only (offline, deterministic).
    * ``llm``     — LLM judge (OpenAI / Gemini / LiteLLM).
    * ``hybrid``  — both; the union of unsupported claims wins.
    * ``mock``    — alias for lexical; tagged as ``mock`` in metadata.
    """
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`query` must be a non-empty string",
        )
    if not request.answer.executive_summary.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`answer.executive_summary` must be a non-empty string",
        )
    if not request.answer.detailed_explanation.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`answer.detailed_explanation` must be a non-empty string",
        )
    if request.method not in VerificationMethod.__members__.values():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid verification method: {request.method!r}",
        )

    try:
        return await service.verify(request)
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Hallucination verification failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"hallucination verification failed: {exc}",
        ) from exc


@router.get(
    "/health",
    summary="Health probe for the hallucination guard",
)
async def health(
    service: HallucinationGuardService = Depends(get_hallucination_guard_service),
) -> dict:
    return {
        "status": "ok",
        "module": "hallucination_guard",
        "version": "5.4.0",
        "provider": getattr(
            getattr(service, "_provider", None), "name", "lexical-only"
        ),
    }


__all__ = ["router"]
