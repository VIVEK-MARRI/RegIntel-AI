"""Module 7.2 — Automated Regulatory Ingestion schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────────


class IngestionStatus(str, Enum):
    """Lifecycle status of an ingestion run."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PARSING = "parsing"
    PARSED = "parsed"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    EMBEDDING = "embedding"
    EMBEDDED = "embedded"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # duplicate


class IngestionStepStatus(str, Enum):
    """Per-step status inside a run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class IngestionStepName(str, Enum):
    """The five steps of the ingestion pipeline."""

    DOWNLOAD = "download"
    PARSE = "parse"
    CHUNK = "chunk"
    EMBED = "embed"
    INDEX = "index"


# ─── Ingestion step / run ───────────────────────────────────────────────


class IngestionStep(BaseModel):
    """A single step in an ingestion pipeline run."""

    model_config = ConfigDict(extra="forbid")

    step: IngestionStepName
    status: IngestionStepStatus = IngestionStepStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.status = IngestionStepStatus.RUNNING

    def finish(
        self,
        status: IngestionStepStatus,
        *,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.status = status
        self.error = error
        if metadata:
            self.metadata.update(metadata)
        if self.started_at is not None:
            self.duration_ms = (
                self.finished_at - self.started_at
            ).total_seconds() * 1000.0


class IngestionRun(BaseModel):
    """A single end-to-end ingestion of a document.

    The output contract::

        {
          "document_id": "...",
          "ingestion_status": "completed",
          "chunks_created": 120
        }
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"ing-{uuid4().hex[:12]}")
    discovery_id: Optional[str] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    document_url: Optional[str] = None
    title: Optional[str] = None
    checksum: Optional[str] = None
    version: Optional[str] = None
    status: IngestionStatus = IngestionStatus.PENDING
    steps: List[IngestionStep] = Field(default_factory=list)
    chunks_created: int = 0
    embeddings_created: int = 0
    pages_parsed: int = 0
    is_duplicate: bool = False
    is_incremental_update: bool = False
    failure_reason: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def finish(
        self,
        status: IngestionStatus,
        *,
        failure_reason: Optional[str] = None,
    ) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.status = status
        self.failure_reason = failure_reason
        self.duration_ms = (
            self.finished_at - self.started_at
        ).total_seconds() * 1000.0


# ─── Triggers / responses ───────────────────────────────────────────────


class IngestionTriggerRequest(BaseModel):
    """Trigger an ingestion.

    Two modes:

    * ``by_discovery`` — ingest a document previously discovered by
      the monitoring engine.
    * ``by_url``      — ingest a document directly from a URL.
    """

    model_config = ConfigDict(extra="forbid")

    discovery_id: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    force: bool = Field(
        False, description="Re-ingest even if checksum already exists."
    )


class IngestionRunResponse(BaseModel):
    """Compact summary returned from ingestion API."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    document_id: Optional[str] = None
    ingestion_status: IngestionStatus
    chunks_created: int = 0
    embeddings_created: int = 0
    pages_parsed: int = 0
    is_duplicate: bool = False
    is_incremental_update: bool = False
    failure_reason: Optional[str] = None
    duration_ms: float = 0.0

    @classmethod
    def from_run(cls, run: IngestionRun) -> "IngestionRunResponse":
        return cls(
            run_id=run.run_id,
            document_id=run.document_id,
            ingestion_status=run.status,
            chunks_created=run.chunks_created,
            embeddings_created=run.embeddings_created,
            pages_parsed=run.pages_parsed,
            is_duplicate=run.is_duplicate,
            is_incremental_update=run.is_incremental_update,
            failure_reason=run.failure_reason,
            duration_ms=run.duration_ms,
        )


# ─── Audit ──────────────────────────────────────────────────────────────


class IngestionAuditEntry(BaseModel):
    """A single audit-trail record for an ingestion step or run."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"aud-{uuid4().hex[:12]}")
    run_id: str
    step: Optional[IngestionStepName] = None
    event: str
    level: str = Field("info", description="info | warning | error")
    message: Optional[str] = None
    document_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Filters / listing ──────────────────────────────────────────────────


class IngestionFilter(BaseModel):
    """Filter for listing ingestion runs."""

    model_config = ConfigDict(extra="forbid")

    source: Optional[str] = None
    status: Optional[IngestionStatus] = None
    document_id: Optional[str] = None
    is_duplicate: Optional[bool] = None
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedIngestionRuns(BaseModel):
    """Paginated ingestion run list."""

    model_config = ConfigDict(extra="forbid")

    items: List[IngestionRun]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Stats ──────────────────────────────────────────────────────────────


class IngestionStats(BaseModel):
    """Aggregated ingestion statistics."""

    model_config = ConfigDict(extra="forbid")

    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0
    duplicate_runs: int = 0
    incremental_updates: int = 0
    chunks_created: int = 0
    embeddings_created: int = 0
    pages_parsed: int = 0
    average_duration_ms: float = 0.0
    by_source: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[IngestionStatus, int] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Scheduler ──────────────────────────────────────────────────────────


class IngestionSchedulerStatus(BaseModel):
    """Status of the ingestion scheduler."""

    model_config = ConfigDict(extra="forbid")

    running: bool
    active_tasks: int = 0
    interval_seconds: int = 3600
    last_tick_at: Optional[datetime] = None
    next_tick_at: Optional[datetime] = None
    last_run_id: Optional[str] = None


# ─── Pipeline coordinator / registry synchroniser ─────────────────────


class RegistrySyncResult(BaseModel):
    """Result of synchronising discoveries with the document registry."""

    model_config = ConfigDict(extra="forbid")

    matched: int = 0
    new_in_registry: int = 0
    already_in_registry: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    details: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "IngestionAuditEntry",
    "IngestionFilter",
    "IngestionRun",
    "IngestionRunResponse",
    "IngestionSchedulerStatus",
    "IngestionStats",
    "IngestionStatus",
    "IngestionStep",
    "IngestionStepName",
    "IngestionStepStatus",
    "IngestionTriggerRequest",
    "PaginatedIngestionRuns",
    "RegistrySyncResult",
]
