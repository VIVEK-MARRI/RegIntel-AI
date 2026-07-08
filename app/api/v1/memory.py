"""Module 6.3 — Memory Layer API.

Endpoints
---------
* ``POST   /api/v1/memory``              — create a new memory entry.
* ``GET    /api/v1/memory/{id}``         — fetch a memory entry.
* ``PUT    /api/v1/memory/{id}``         — update tags / metadata /
  content.
* ``DELETE /api/v1/memory/{id}``         — delete a memory entry.
* ``POST   /api/v1/memory/search``       — ranked search.
* ``POST   /api/v1/memory/record-message`` — record a message as
  short-term memory.
* ``POST   /api/v1/memory/record-retrieval`` — record a Q/A pair as
  retrieval memory.
* ``POST   /api/v1/memory/record-long-term`` — record long-term user
  context.
* ``POST   /api/v1/memory/purge``        — admin: purge expired.
* ``GET    /api/v1/memory/health``      — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_memory_service
from app.schemas.conversation import Message, Role
from app.schemas.memory import (
    CreateMemoryRequest,
    MemoryContext,
    MemoryEntry,
    MemoryQuery,
    MemorySearchResult,
)
from app.services.memory import MemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])


# ── Inline payload schemas for endpoints that don't need a full Pydantic
#    request model from the schema layer. ────────────────────────────────


class UpdateMemoryRequest(BaseModel):
    """Partial update payload for a memory entry."""

    content: Optional[str] = Field(
        default=None, max_length=8192, description="Replacement content"
    )
    tags: Optional[List[str]] = Field(
        default=None, description="Replacement tag list"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Replacement metadata"
    )
    pinned: Optional[bool] = Field(
        default=None, description="Pin or unpin the entry"
    )


class RecordMessageRequest(BaseModel):
    """Payload for recording a message as short-term memory."""

    role: Role
    content: str = Field(min_length=1, max_length=8192)
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


class RecordRetrievalRequest(BaseModel):
    """Payload for recording a Q/A pair as retrieval memory."""

    query: str = Field(min_length=1, max_length=4096)
    answer_text: str = Field(min_length=1, max_length=16384)
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None


class RecordLongTermRequest(BaseModel):
    """Payload for recording long-term user context."""

    content: str = Field(min_length=1, max_length=8192)
    user_id: str = Field(min_length=1)
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class BuildContextRequest(BaseModel):
    """Payload for :func:`build_context`."""

    query: str = Field(min_length=1, max_length=4096)
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    top_k: int = Field(5, ge=1, le=20)


# ── Endpoints ────────────────────────────────────────────────────────────

# Static routes MUST be declared before the wildcard ``/{memory_id}``
# route or FastAPI will route them to the wrong handler. ────────────────


@router.get(
    "/health",
    summary="Health probe for the memory layer",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "memory",
        "version": "6.3.0",
    }


@router.post(
    "/search",
    response_model=List[MemorySearchResult],
    summary="Ranked memory search",
)
async def search_memory(
    query: MemoryQuery,
    service: MemoryService = Depends(get_memory_service),
) -> List[MemorySearchResult]:
    try:
        return service.repository.search(query)
    except Exception as exc:  # pragma: no cover
        logger.exception("Memory search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"memory search failed: {exc}",
        ) from exc


@router.post(
    "/record-message",
    response_model=Optional[MemoryEntry],
    summary="Record a message as short-term memory",
)
async def record_message(
    request: RecordMessageRequest,
    service: MemoryService = Depends(get_memory_service),
) -> Optional[MemoryEntry]:
    msg = Message(role=request.role, content=request.content)
    entry = service.manager.record_from_message(msg, user_id=request.user_id)
    # Tag with the optional conversation_id after creation.
    if entry is not None and request.conversation_id:
        entry.conversation_id = request.conversation_id
        service.repository.update(entry)
    return entry


@router.post(
    "/record-retrieval",
    response_model=MemoryEntry,
    summary="Record a Q/A pair as retrieval memory",
)
async def record_retrieval(
    request: RecordRetrievalRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryEntry:
    return service.manager.record_retrieval(
        query=request.query,
        answer_text=request.answer_text,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
    )


@router.post(
    "/record-long-term",
    response_model=MemoryEntry,
    summary="Record a long-term user memory",
)
async def record_long_term(
    request: RecordLongTermRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryEntry:
    return service.manager.record_long_term(
        content=request.content,
        user_id=request.user_id,
        tags=request.tags,
        metadata=request.metadata,
    )


@router.post(
    "/build-context",
    response_model=MemoryContext,
    summary="Build a :class:`MemoryContext` for a copilot request",
)
async def build_context(
    request: BuildContextRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryContext:
    return service.manager.build_context(
        query=request.query,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        top_k=request.top_k,
    )


@router.post(
    "/purge",
    summary="Admin: purge all expired memories",
)
async def purge_expired(
    service: MemoryService = Depends(get_memory_service),
) -> Dict[str, Any]:
    purged = service.manager.purge_expired()
    return {"purged": purged}


@router.post(
    "",
    response_model=MemoryEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Create a memory entry",
)
async def create_memory(
    request: CreateMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryEntry:
    try:
        return service.repository.create(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Memory creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"memory creation failed: {exc}",
        ) from exc


@router.get(
    "/{memory_id}",
    response_model=MemoryEntry,
    summary="Fetch a memory entry",
)
async def get_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryEntry:
    entry = service.repository.get(memory_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"memory {memory_id!r} not found",
        )
    return entry


@router.put(
    "/{memory_id}",
    response_model=MemoryEntry,
    summary="Partially update a memory entry",
)
async def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryEntry:
    entry = service.repository.get(memory_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"memory {memory_id!r} not found",
        )
    if request.content is not None:
        entry.content = request.content
        entry.embedding_text = request.content
    if request.tags is not None:
        entry.tags = list(request.tags)
    if request.metadata is not None:
        entry.metadata = dict(request.metadata)
    if request.pinned is not None:
        entry.pinned = request.pinned
    service.repository.update(entry)
    return entry


@router.delete(
    "/{memory_id}",
    summary="Delete a memory entry",
)
async def delete_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> Dict[str, Any]:
    deleted = service.repository.delete(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"memory {memory_id!r} not found",
        )
    return {"memory_id": memory_id, "deleted": True}


__all__ = ["router"]
