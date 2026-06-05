"""Module 5.7 — Answer Evaluation Framework API.

Endpoints
---------
* ``POST /api/v1/evaluation/evaluate`` — evaluate a single response.
* ``POST /api/v1/evaluation/benchmark`` — run a benchmark over many
  cases and produce an aggregate report.
* ``GET  /api/v1/evaluation/health`` — health probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_evaluation_service
from app.schemas.evaluation import (
    AnswerEvaluationReport,
    AnswerEvaluationResult,
    EvaluationRequest,
    EvaluationResponse,
)
from app.services.evaluation import AnswerEvaluationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate a single final response",
)
async def evaluate(
    request: EvaluationRequest,
    service: AnswerEvaluationService = Depends(get_evaluation_service),
) -> EvaluationResponse:
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`query` must be a non-empty string",
        )
    try:
        return service.evaluate(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Answer evaluation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"answer evaluation failed: {exc}",
        ) from exc


@router.post(
    "/benchmark",
    response_model=AnswerEvaluationReport,
    summary="Run a benchmark over multiple cases",
)
async def benchmark(
    payload: dict,
    service: AnswerEvaluationService = Depends(get_evaluation_service),
) -> AnswerEvaluationReport:
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`cases` must be a non-empty list",
        )
    baseline_raw = payload.get("baseline_results")
    baseline = (
        [AnswerEvaluationResult.model_validate(r) for r in baseline_raw]
        if baseline_raw
        else None
    )
    try:
        return service.benchmark(cases, baseline_results=baseline)
    except Exception as exc:  # pragma: no cover
        logger.exception("Benchmark failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"benchmark failed: {exc}",
        ) from exc


@router.get(
    "/health",
    summary="Health probe for the evaluation framework",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "answer_evaluation",
        "version": "5.7.0",
    }


__all__ = ["router"]
