"""Module 6.1 — Regulatory Copilot API.

Endpoints
---------
* ``POST /api/v1/copilot/query``  — execute a copilot query.
* ``GET  /api/v1/copilot/health`` — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_conversation_service,
    get_memory_service,
    get_response_orchestrator,
)
from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.answer_analytics import (
    AnswerAnalyticsService,
    build_default_answer_analytics_service,
)
from app.services.conversation import ConversationService
from app.services.copilot import CopilotController, CopilotService
from app.services.memory import MemoryService
from app.services.orchestrator import ResponseOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot"])


def _build_copilot_service(
    orchestrator: Optional[ResponseOrchestrator] = None,
    memory: Optional[MemoryService] = None,
    conversation: Optional[ConversationService] = None,
    analytics: Optional[AnswerAnalyticsService] = None,
) -> CopilotService:
    return CopilotService(
        orchestrator=orchestrator,
        memory=memory,
        conversation=conversation,
        analytics=analytics,
    )


_copilot_service: "CopilotService | None" = None  # type: ignore[name-defined]


def _copilot_service_singleton(
    orchestrator: ResponseOrchestrator,
    memory: MemoryService,
    conversation: ConversationService,
) -> "CopilotService":
    global _copilot_service
    if _copilot_service is None:
        # Best-effort wiring of analytics (uses the default factory which
        # creates a fresh in-memory service; the canonical singleton is
        # exposed via the answer-analytics API).
        try:
            analytics = build_default_answer_analytics_service()
        except Exception:  # pragma: no cover
            analytics = None
        _copilot_service = _build_copilot_service(
            orchestrator=orchestrator,
            memory=memory,
            conversation=conversation,
            analytics=analytics,
        )
    return _copilot_service


def get_copilot_service(
    orchestrator: ResponseOrchestrator = Depends(get_response_orchestrator),
    memory: MemoryService = Depends(get_memory_service),
    conversation: ConversationService = Depends(get_conversation_service),
) -> CopilotService:
    """Dependency injection provider for CopilotService (singleton)."""
    return _copilot_service_singleton(orchestrator, memory, conversation)


def reset_copilot_service() -> None:
    """Reset the CopilotService singleton (used by tests)."""
    global _copilot_service
    _copilot_service = None


@router.post(
    "/query",
    response_model=CopilotResponse,
    summary="Execute a copilot query",
)
async def copilot_query(
    request: CopilotRequest,
    service: CopilotService = Depends(get_copilot_service),
) -> CopilotResponse:
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`query` must be a non-empty string",
        )
    controller = CopilotController(service=service)
    try:
        return await controller.handle(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Copilot query failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"copilot query failed: {exc}",
        ) from exc


@router.get(
    "/health",
    summary="Health probe for the regulatory copilot",
)
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "module": "copilot",
        "version": "6.1.0",
    }


__all__ = ["get_copilot_service", "reset_copilot_service", "router"]
