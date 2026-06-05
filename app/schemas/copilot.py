"""Module 6.1 — Regulatory Copilot API schemas.

The :class:`CopilotRequest` is the top-level payload the frontend
sends.  The :class:`CopilotResponse` is the unified response
containing the answer, citations, attribution, faithfulness, and
conversation / memory metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.attribution import SourceAttribution
from app.schemas.citation import AnnotatedAnswer
from app.schemas.hallucination import HallucinationRiskLevel
from app.schemas.memory import MemoryContext
from app.schemas.orchestrator import OrchestratorMetadata
from app.schemas.confidence import ConfidenceLevel


# ─── Enums ──────────────────────────────────────────────────────────────────


class CopilotMode(str, Enum):
    """Copilot execution mode."""

    ANSWER = "answer"            # Produce a full orchestrated answer.
    SUMMARISE = "summarise"      # Just summarise the memory/context.
    SEARCH = "search"            # Just retrieve chunks; no answer.


# ─── Request / Response ───────────────────────────────────────────────────


class CopilotRequest(BaseModel):
    """Top-level copilot query payload."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    query: str = Field(..., min_length=1, max_length=4096)
    conversation_id: Optional[str] = Field(
        None, description="If absent, a new conversation is created."
    )
    user_id: Optional[str] = Field(None, description="Owning user (for long-term memory).")
    mode: CopilotMode = CopilotMode.ANSWER
    # Optional override of orchestrator knobs.
    tone: str = Field("regulatory")
    verification_method: str = Field("lexical")
    min_faithfulness: float = Field(0.7, ge=0.0, le=1.0)
    # Memory knobs.
    use_memory: bool = Field(
        True, description="If false, the copilot ignores prior memory."
    )
    memory_top_k: int = Field(5, ge=1, le=20)
    # Pre-retrieved chunks (skips retrieval when present).
    chunks: Optional[List[Dict[str, Any]]] = Field(
        None, description="Pre-retrieved chunks; when provided, retrieval is skipped."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CopilotMessage(BaseModel):
    """A copilot-shaped message (used in the response history echo)."""

    model_config = ConfigDict(extra="forbid")

    role: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CopilotResponse(BaseModel):
    """Top-level copilot response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    conversation_id: str
    user_id: Optional[str] = None
    query: str
    mode: CopilotMode
    answer: Optional[Dict[str, Any]] = Field(
        None, description="The orchestrator's structured answer (or None for non-answer modes)."
    )
    citations: Optional[AnnotatedAnswer] = None
    confidence_score: float = Field(0.0, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    faithfulness_score: float = Field(0.0, ge=0.0, le=1.0)
    hallucination_detected: bool = False
    hallucination_risk_level: HallucinationRiskLevel = HallucinationRiskLevel.NONE
    sources: List[SourceAttribution] = Field(default_factory=list)
    attribution_coverage_ratio: float = Field(0.0, ge=0.0, le=1.0)
    memory_used: bool = False
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    history: List[CopilotMessage] = Field(default_factory=list)
    latency_ms: float = Field(0.0, ge=0.0)
    metadata: OrchestratorMetadata = Field(default_factory=OrchestratorMetadata)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "CopilotMessage",
    "CopilotMode",
    "CopilotRequest",
    "CopilotResponse",
]
