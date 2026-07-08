"""Module 6.3 — Memory Layer schemas.

Three memory types are supported:

* **Short-term memory** — the active conversation's most recent
  :class:`app.schemas.conversation.Message` objects.
* **Long-term memory** — persistent user-level context (preferences,
  role, organisation, etc.) keyed by ``user_id``.
* **Retrieval memory** — previous regulatory queries / answers that
  have proven useful.  Indexed by user and ranked by relevance to
  the current query.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.conversation import Message


# ─── Enums ──────────────────────────────────────────────────────────────────


class MemoryType(str, Enum):
    """The three memory classes."""

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    RETRIEVAL = "retrieval"


class MemoryScope(str, Enum):
    """Visibility scope for a memory entry."""

    USER = "user"
    CONVERSATION = "conversation"
    GLOBAL = "global"


# ─── Memory entry ─────────────────────────────────────────────────────────


class MemoryEntry(BaseModel):
    """A single memory record."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    memory_type: MemoryType
    scope: MemoryScope = MemoryScope.USER
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    content: str = Field(..., min_length=1, description="The memory text.")
    embedding_text: str = Field(
        "", description="Optional text used for ranking (defaults to content)."
    )
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(
        None, description="When this memory should be purged."
    )
    ttl_seconds: Optional[int] = Field(None, ge=1)
    access_count: int = Field(0, ge=0)
    last_accessed_at: Optional[datetime] = None
    relevance_score: float = Field(
        0.0, ge=0.0, description="Last computed relevance to the active query."
    )
    pinned: bool = Field(False, description="Pinned memories are never auto-expired.")


# ─── Search & filter ──────────────────────────────────────────────────────


class MemoryQuery(BaseModel):
    """Search / filter for memory entries."""

    model_config = ConfigDict(extra="forbid")

    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    memory_types: Optional[List[MemoryType]] = Field(
        None, description="Restrict to these memory types (None = all)."
    )
    tags: Optional[List[str]] = None
    query: Optional[str] = Field(None, description="Free-text query for ranking.")
    top_k: int = Field(5, ge=1, le=50)
    min_relevance: float = Field(0.0, ge=0.0, le=1.0)
    include_expired: bool = False


class MemorySearchResult(BaseModel):
    """A single hit in a memory search."""

    model_config = ConfigDict(extra="forbid")

    entry: MemoryEntry
    score: float = Field(..., ge=0.0, le=1.0)
    matched_terms: List[str] = Field(default_factory=list)


class MemoryContext(BaseModel):
    """The memory context attached to a copilot request.

    The copilot orchestrator uses this to inject prior knowledge into
    the answer generation pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    short_term: List[Message] = Field(default_factory=list)
    long_term: List[MemoryEntry] = Field(default_factory=list)
    retrieval: List[MemorySearchResult] = Field(default_factory=list)
    total_count: int = 0
    memory_used: bool = Field(
        False, description="True if any memory class contributed entries."
    )


# ─── Request/Response payloads ───────────────────────────────────────────


class CreateMemoryRequest(BaseModel):
    """API request to create a memory entry."""

    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    content: str = Field(..., min_length=1, max_length=8192)
    scope: MemoryScope = MemoryScope.USER
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: Optional[int] = Field(None, ge=1, le=60 * 60 * 24 * 365)
    pinned: bool = False


__all__ = [
    "CreateMemoryRequest",
    "MemoryContext",
    "MemoryEntry",
    "MemoryQuery",
    "MemoryScope",
    "MemorySearchResult",
    "MemoryType",
]
