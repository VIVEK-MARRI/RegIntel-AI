"""Module 6.2 — Conversation Management API.

Endpoints
---------
* ``POST   /api/v1/conversations``                       — create a new
  conversation.
* ``GET    /api/v1/conversations/{id}``                  — fetch a
  conversation (with its messages).
* ``POST   /api/v1/conversations/{id}/messages``         — append a
  message.
* ``GET    /api/v1/conversations``                       — list with
  pagination + filters.
* ``DELETE /api/v1/conversations/{id}``                  — archive (soft)
  or delete (hard).
* ``GET    /api/v1/conversations/{id}/context``          — working-set
  context window.
* ``POST   /api/v1/conversations/{id}/refresh-summary``  — rebuild the
  summary.
* ``POST   /api/v1/conversations/{id}/trim``             — trim older
  messages.
* ``POST   /api/v1/conversations/purge-expired``         — admin sweep.
* ``GET    /api/v1/conversations/health``                — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.api.dependencies import get_conversation_service
from app.schemas.conversation import (
    AppendMessageRequest,
    Conversation,
    ConversationContext,
    ConversationFilter,
    ConversationStatus,
    CreateConversationRequest,
    PaginatedConversations,
)
from app.services.conversation import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversation"])


# ── Static routes MUST be declared before the wildcard
#    ``/{conversation_id}`` route or FastAPI will route them to the
#    wrong handler. ────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Health probe for conversation management",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "conversation",
        "version": "6.2.0",
    }


@router.post(
    "/purge-expired",
    summary="Admin: purge all expired conversations",
)
async def purge_expired(
    service: ConversationService = Depends(get_conversation_service),
) -> Dict[str, Any]:
    purged = service.manager.purge_expired()
    return {"purged": purged}


@router.post(
    "",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
    request: CreateConversationRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    try:
        return service.manager.create(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Conversation creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"conversation creation failed: {exc}",
        ) from exc


@router.get(
    "",
    response_model=PaginatedConversations,
    summary="List / search conversations with filters and pagination",
)
async def list_conversations(
    user_id: Optional[str] = Query(None, description="Filter by user_id"),
    conversation_status: Optional[ConversationStatus] = Query(
        None, alias="status", description="Filter by lifecycle status"
    ),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    query: Optional[str] = Query(None, description="Free-text search"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
    sort_by: str = Query("updated_at", description="Field to sort by"),
    sort_desc: bool = Query(True, description="Sort descending"),
    service: ConversationService = Depends(get_conversation_service),
) -> PaginatedConversations:
    flt = ConversationFilter(
        user_id=user_id,
        status=conversation_status,
        tag=tag,
        query=query,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )
    try:
        return service.manager.search(flt)
    except Exception as exc:  # pragma: no cover
        logger.exception("List conversations failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"list conversations failed: {exc}",
        ) from exc


@router.get(
    "/{conversation_id}",
    response_model=Conversation,
    summary="Fetch a conversation (with messages)",
)
async def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    conv = service.manager.get(conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        )
    return conv


@router.post(
    "/{conversation_id}/messages",
    response_model=Conversation,
    summary="Append a message to a conversation",
)
async def append_message(
    conversation_id: str,
    request: AppendMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    try:
        return service.manager.append(conversation_id, request)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        ) from None
    except Exception as exc:  # pragma: no cover
        logger.exception("Append message failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"append message failed: {exc}",
        ) from exc


@router.delete(
    "/{conversation_id}",
    summary="Archive (soft) or delete (hard) a conversation",
)
async def delete_conversation(
    conversation_id: str,
    hard: bool = Query(False, description="If true, hard-delete; otherwise archive"),
    service: ConversationService = Depends(get_conversation_service),
) -> Dict[str, Any]:
    conv = service.manager.get(conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        )
    if hard:
        deleted = service.manager.delete(conversation_id)
        return {"conversation_id": conversation_id, "deleted": deleted, "mode": "hard"}
    conv.status = ConversationStatus.ARCHIVED
    service.repository.update(conv)
    return {"conversation_id": conversation_id, "deleted": False, "mode": "archived"}


@router.get(
    "/{conversation_id}/context",
    response_model=ConversationContext,
    summary="Build a working-set context window for a conversation",
)
async def get_context(
    conversation_id: str,
    token_budget: Optional[int] = Query(
        None, ge=100, le=32000, description="Override the default token budget"
    ),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationContext:
    try:
        return service.manager.build_context(conversation_id, token_budget=token_budget)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        ) from None
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid request: {exc.errors()}",
        ) from exc


@router.post(
    "/{conversation_id}/refresh-summary",
    response_model=Conversation,
    summary="Rebuild the extractive summary for a conversation",
)
async def refresh_summary(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    try:
        return service.manager.refresh_summary(conversation_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        ) from None


@router.post(
    "/{conversation_id}/trim",
    response_model=Conversation,
    summary="Trim older messages into the summary",
)
async def trim_conversation(
    conversation_id: str,
    keep_last: int = Query(20, ge=1, le=200),
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    try:
        return service.manager.trim(conversation_id, keep_last=keep_last)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation {conversation_id!r} not found",
        ) from None


__all__ = ["router"]
