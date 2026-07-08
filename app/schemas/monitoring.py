"""Module 7.1 — Regulatory Monitoring Engine schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────────


class RegulatorySource(str, Enum):
    """Supported regulatory authorities.

    The enum is open for extension: adapters may register additional
    custom sources at runtime.
    """

    RBI = "RBI"
    SEBI = "SEBI"
    IRDAI = "IRDAI"
    PFRDA = "PFRDA"
    MINISTRY_OF_FINANCE = "MINISTRY_OF_FINANCE"
    CUSTOM = "CUSTOM"


class MonitoringStatus(str, Enum):
    """Per-source monitoring status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DiscoveryType(str, Enum):
    """How the document was discovered."""

    LISTING_PAGE = "listing_page"
    RSS_FEED = "rss_feed"
    SITEMAP = "sitemap"
    API = "api"
    MANUAL = "manual"


class ChangeType(str, Enum):
    """Type of change detected for an already-known document."""

    NEW = "new"
    UPDATED = "updated"
    REPUBLISHED = "republished"
    WITHDRAWN = "withdrawn"
    UNCHANGED = "unchanged"


# ─── Source configuration ────────────────────────────────────────────────


class SourceConfig(BaseModel):
    """Configuration for a regulatory source adapter."""

    model_config = ConfigDict(extra="forbid")

    source: RegulatorySource
    base_url: str = Field(..., description="Authority homepage / listing page.")
    listing_url: Optional[str] = Field(
        None, description="URL of the document-listing page or RSS feed."
    )
    enabled: bool = True
    poll_interval_seconds: int = Field(3600, ge=60, le=86_400)
    user_agent: Optional[str] = None
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Discovered document ─────────────────────────────────────────────────


class DiscoveredDocument(BaseModel):
    """A document surfaced by a source adapter.

    Mirrors the output contract::

        {
          "source": "RBI",
          "document_found": true,
          "document_url": "...",
          "version": "..."
        }
    """

    model_config = ConfigDict(extra="forbid")

    discovery_id: str = Field(default_factory=lambda: f"disc-{uuid4().hex[:12]}")
    source: RegulatorySource
    title: str
    document_url: str
    document_type: Optional[str] = None
    publication_date: Optional[datetime] = None
    version: Optional[str] = None
    checksum_hint: Optional[str] = Field(
        None, description="ETag / Last-Modified / SHA1 hint for change detection."
    )
    discovery_type: DiscoveryType = DiscoveryType.LISTING_PAGE
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    document_found: bool = True
    change_type: ChangeType = ChangeType.NEW
    already_known: bool = False

    def to_brief_dict(self) -> Dict[str, Any]:
        """Compact representation used by API responses."""
        return {
            "source": self.source.value,
            "document_found": self.document_found,
            "document_url": self.document_url,
            "version": self.version,
        }


# ─── Document change detection / version tracking ────────────────────────


class DocumentVersion(BaseModel):
    """A specific version of a known document."""

    model_config = ConfigDict(extra="forbid")

    document_key: str = Field(..., description="Stable key (e.g. source:slug).")
    version: str
    document_url: str
    publication_date: Optional[datetime] = None
    checksum: Optional[str] = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Monitoring runs ─────────────────────────────────────────────────────


class MonitoringRun(BaseModel):
    """A single execution of a monitoring job for a source."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:12]}")
    source: RegulatorySource
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    status: MonitoringStatus = MonitoringStatus.UNKNOWN
    discovered_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def finish(
        self,
        status: MonitoringStatus,
        *,
        discovered_count: int = 0,
        new_count: int = 0,
        updated_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.status = status
        self.discovered_count = discovered_count
        self.new_count = new_count
        self.updated_count = updated_count
        self.error_message = error_message
        self.duration_ms = (self.finished_at - self.started_at).total_seconds() * 1000.0


# ─── Health ──────────────────────────────────────────────────────────────


class SourceHealth(BaseModel):
    """Health snapshot for a single source."""

    model_config = ConfigDict(extra="forbid")

    source: RegulatorySource
    status: MonitoringStatus
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_discovery_count: int = 0


class MonitoringHealth(BaseModel):
    """Aggregate health of the monitoring engine."""

    model_config = ConfigDict(extra="forbid")

    overall_status: MonitoringStatus
    sources: List[SourceHealth] = Field(default_factory=list)
    total_runs: int = 0
    total_discoveries: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Run triggers / responses ────────────────────────────────────────────


class RunMonitorRequest(BaseModel):
    """Request to trigger a monitoring run for a single source."""

    model_config = ConfigDict(extra="forbid")

    source: RegulatorySource
    force: bool = Field(
        False, description="Run even if the source is currently disabled."
    )


class RunMonitorResponse(BaseModel):
    """Outcome of a single-source monitoring run."""

    model_config = ConfigDict(extra="forbid")

    run: MonitoringRun
    discoveries: List[DiscoveredDocument] = Field(default_factory=list)


class RunAllResponse(BaseModel):
    """Outcome of running the monitor for every registered source."""

    model_config = ConfigDict(extra="forbid")

    runs: List[MonitoringRun] = Field(default_factory=list)
    discoveries: List[DiscoveredDocument] = Field(default_factory=list)
    total_discoveries: int = 0


# ─── Filters / listing ───────────────────────────────────────────────────


class DiscoveryFilter(BaseModel):
    """Filter for listing discoveries."""

    model_config = ConfigDict(extra="forbid")

    source: Optional[RegulatorySource] = None
    change_type: Optional[ChangeType] = None
    document_url: Optional[str] = None
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedDiscoveries(BaseModel):
    """Paginated discovery list."""

    model_config = ConfigDict(extra="forbid")

    items: List[DiscoveredDocument]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Scheduler ───────────────────────────────────────────────────────────


class SchedulerStatus(BaseModel):
    """Status of the monitoring scheduler."""

    model_config = ConfigDict(extra="forbid")

    running: bool
    active_tasks: int = 0
    sources: List[RegulatorySource] = Field(default_factory=list)
    interval_seconds: int = 3600
    last_tick_at: Optional[datetime] = None
    next_tick_at: Optional[datetime] = None


# ─── Custom adapter registration ────────────────────────────────────────


class CustomSourceRegistration(BaseModel):
    """Payload for registering an ad-hoc source at runtime."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    base_url: str
    listing_url: Optional[str] = None
    poll_interval_seconds: int = Field(3600, ge=60)
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ChangeType",
    "CustomSourceRegistration",
    "DiscoveryFilter",
    "DiscoveryType",
    "DiscoveredDocument",
    "DocumentVersion",
    "MonitoringHealth",
    "MonitoringRun",
    "MonitoringStatus",
    "PaginatedDiscoveries",
    "RegulatorySource",
    "RunAllResponse",
    "RunMonitorRequest",
    "RunMonitorResponse",
    "SchedulerStatus",
    "SourceConfig",
    "SourceHealth",
]
