"""Module 6.4 — Query Planning Engine API.

Endpoints
---------
* ``POST /api/v1/planning/plan``     — generate a plan (no execution).
* ``POST /api/v1/planning/execute``  — generate + execute a plan.
* ``POST /api/v1/planning/validate`` — validate a raw plan payload.
* ``GET  /api/v1/planning/health``   — health probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_query_planner
from app.schemas.planning import (
    ExecutionPlan,
    PlanValidationResult,
    QueryPlanRequest,
    QueryPlanResponse,
)
from app.services.planning import QueryPlanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get(
    "/health",
    summary="Health probe for the query planning engine",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "planning",
        "version": "6.4.0",
    }


@router.post(
    "/plan",
    response_model=QueryPlanResponse,
    summary="Generate a plan for a regulatory query",
)
async def generate_plan(
    request: QueryPlanRequest,
    planner: QueryPlanner = Depends(get_query_planner),
) -> QueryPlanResponse:
    try:
        plan, validation, explanation = planner.plan(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Plan generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"plan generation failed: {exc}",
        ) from exc
    return QueryPlanResponse(
        plan=plan, validation=validation, explanation=explanation
    )


@router.post(
    "/execute",
    response_model=QueryPlanResponse,
    summary="Generate and execute a plan for a regulatory query",
)
async def execute_plan(
    request: QueryPlanRequest,
    planner: QueryPlanner = Depends(get_query_planner),
) -> QueryPlanResponse:
    try:
        plan, validation, explanation, execution = await planner.plan_and_execute(
            request
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Plan execution failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"plan execution failed: {exc}",
        ) from exc
    return QueryPlanResponse(
        plan=plan,
        validation=validation,
        explanation=explanation,
        execution=execution,
    )


@router.post(
    "/validate",
    response_model=PlanValidationResult,
    summary="Validate a raw plan payload",
)
async def validate_plan(
    plan: ExecutionPlan,
    planner: QueryPlanner = Depends(get_query_planner),
) -> PlanValidationResult:
    return planner.validator.validate(plan)


__all__ = ["router"]
