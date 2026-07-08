"""Module 7.1 — Regulatory Monitoring Engine.

Public surface
--------------
* :class:`SourceAdapter` — abstract adapter for a regulatory authority.
* :class:`RBISourceAdapter`, :class:`SEBISourceAdapter`,
  :class:`IRDAISourceAdapter`, :class:`PFRDASourceAdapter`,
  :class:`MoFSourceAdapter` — built-in adapters (default behaviour:
  emit a synthetic discovery so the platform is exercisable offline).
* :class:`SourceRegistry` — pluggable registry of adapters.
* :class:`DocumentDiscoveryEngine` — runs an adapter and converts the
  result into :class:`DiscoveredDocument` objects.
* :class:`MonitoringStore` / :class:`MonitoringRepository` — persistence.
* :class:`RegulatoryMonitor` — top-level orchestrator.
* :class:`MonitoringService` — DI-friendly facade.
* :class:`MonitoringScheduler` — asyncio-based scheduler.
* :func:`build_default_monitoring_service` — production factory.

Adapters in production are responsible for fetching the authority's
listing page / RSS feed. To keep the platform functional offline (and
unit-testable), every built-in adapter is implemented against a
``listing_url``-aware mock that emits a deterministic, well-formed
:class:`DiscoveredDocument` set.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.core.config import settings
from app.core.http_client import HTTPClient, HTTPClientConfig, build_default_http_client
from app.schemas.monitoring import (
    ChangeType,
    DiscoveryFilter,
    DiscoveryType,
    DiscoveredDocument,
    DocumentVersion,
    MonitoringHealth,
    MonitoringRun,
    MonitoringStatus,
    PaginatedDiscoveries,
    RegulatorySource,
    RunAllResponse,
    RunMonitorResponse,
    SchedulerStatus,
    SourceConfig,
    SourceHealth,
)
from app.services.observability import (
    RequestContext,
    get_monitoring_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Source adapters ─────────────────────────────────────────────────────


FetchFn = Callable[[str], Awaitable[str]]


class SourceAdapter(ABC):
    """Abstract adapter for a single regulatory authority.

    Adapters are responsible for:

    1. Fetching the authority's listing / RSS / sitemap.
    2. Parsing it into raw rows ``{"title", "url", "date", "version"}``.
    3. Emitting :class:`DiscoveredDocument` objects.
    """

    source: RegulatorySource
    config: SourceConfig

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @abstractmethod
    async def discover(self) -> List[DiscoveredDocument]:
        """Discover new / updated documents from this source."""

    # Helpers shared by all adapters ─────────────────────────────────────

    def _doc(
        self,
        title: str,
        url: str,
        *,
        publication_date: Optional[datetime] = None,
        version: Optional[str] = None,
        document_type: Optional[str] = None,
        summary: Optional[str] = None,
        change_type: ChangeType = ChangeType.NEW,
        discovery_type: DiscoveryType = DiscoveryType.LISTING_PAGE,
    ) -> DiscoveredDocument:
        return DiscoveredDocument(
            source=self.source,
            title=title,
            document_url=url,
            publication_date=publication_date,
            version=version,
            document_type=document_type,
            summary=summary,
            change_type=change_type,
            discovery_type=discovery_type,
        )


def _synthetic_listing_for(source: RegulatorySource) -> List[Dict[str, Any]]:
    """Built-in offline listing. The actual adapter may override this."""
    base = source.value.lower()
    today = datetime.now(timezone.utc)
    return [
        {
            "title": f"{source.value} Master Circular {today.year}",
            "url": f"https://example.gov.in/{base}/circular-{uuid.uuid4().hex[:6]}.pdf",
            "date": today,
            "version": f"v{today.year}.1",
            "type": "circular",
        },
        {
            "title": f"{source.value} Quarterly Bulletin Q1",
            "url": f"https://example.gov.in/{base}/bulletin-q1.pdf",
            "date": today,
            "version": "Q1",
            "type": "bulletin",
        },
    ]


class _BaseHTTPAdapter(SourceAdapter):
    """Default adapter that synthesises a listing (offline-friendly)."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        self._client: Optional[HTTPClient] = None

    def _http(self) -> HTTPClient:
        if self._client is None:
            self._client = build_default_http_client()
        return self._client

    async def discover(self) -> List[DiscoveredDocument]:
        # In production, this would fetch self.config.listing_url and parse
        # it. Offline we emit a synthetic listing so the engine is always
        # runnable / observable.
        rows = _synthetic_listing_for(self.source)
        out: List[DiscoveredDocument] = []
        for r in rows:
            out.append(
                self._doc(
                    title=r["title"],
                    url=r["url"],
                    publication_date=r["date"],
                    version=r.get("version"),
                    document_type=r.get("type"),
                    summary=f"Auto-discovered from {self.source.value} listing.",
                )
            )
        return out


class RBISourceAdapter(_BaseHTTPAdapter):
    source = RegulatorySource.RBI


class SEBISourceAdapter(_BaseHTTPAdapter):
    source = RegulatorySource.SEBI


class IRDAISourceAdapter(_BaseHTTPAdapter):
    source = RegulatorySource.IRDAI


class PFRDASourceAdapter(_BaseHTTPAdapter):
    source = RegulatorySource.PFRDA


class MoFSourceAdapter(_BaseHTTPAdapter):
    source = RegulatorySource.MINISTRY_OF_FINANCE


# ─── Source registry ────────────────────────────────────────────────────


_DEFAULT_FACTORIES: Dict[RegulatorySource, Callable[[SourceConfig], SourceAdapter]] = {
    RegulatorySource.RBI: RBISourceAdapter,
    RegulatorySource.SEBI: SEBISourceAdapter,
    RegulatorySource.IRDAI: IRDAISourceAdapter,
    RegulatorySource.PFRDA: PFRDASourceAdapter,
    RegulatorySource.MINISTRY_OF_FINANCE: MoFSourceAdapter,
}


class SourceRegistry:
    """Pluggable registry of :class:`SourceAdapter` instances.

    Built-in factories cover RBI, SEBI, IRDAI, PFRDA, MoF. Custom
    sources can be added at runtime via :meth:`register`.
    """

    def __init__(self) -> None:
        self._configs: Dict[RegulatorySource, SourceConfig] = {}
        self._factories: Dict[
            RegulatorySource, Callable[[SourceConfig], SourceAdapter]
        ] = dict(_DEFAULT_FACTORIES)
        self._lock = threading.RLock()

    # ── Registration ────────────────────────────────────────────────────

    def register(
        self,
        source: RegulatorySource,
        factory: Callable[[SourceConfig], SourceAdapter],
        config: Optional[SourceConfig] = None,
    ) -> None:
        with self._lock:
            self._factories[source] = factory
            if config is not None:
                self._configs[source] = config

    def unregister(self, source: RegulatorySource) -> None:
        with self._lock:
            self._factories.pop(source, None)
            self._configs.pop(source, None)

    def set_config(self, source: RegulatorySource, config: SourceConfig) -> None:
        with self._lock:
            self._configs[source] = config

    # ── Accessors ───────────────────────────────────────────────────────

    def get_config(self, source: RegulatorySource) -> Optional[SourceConfig]:
        with self._lock:
            return self._configs.get(source)

    def list_sources(self) -> List[RegulatorySource]:
        with self._lock:
            return list(self._factories.keys())

    def list_enabled_sources(self) -> List[RegulatorySource]:
        with self._lock:
            return [
                s
                for s, cfg in self._configs.items()
                if cfg.enabled and s in self._factories
            ]

    def build(self, source: RegulatorySource) -> SourceAdapter:
        with self._lock:
            factory = self._factories.get(source)
            config = self._configs.get(source) or self._default_config(source)
            if factory is None:
                raise KeyError(f"no adapter registered for {source}")
            return factory(config)

    @staticmethod
    def _default_config(source: RegulatorySource) -> SourceConfig:
        return SourceConfig(
            source=source,
            base_url=f"https://example.gov.in/{source.value.lower()}",
            listing_url=f"https://example.gov.in/{source.value.lower()}/listing",
        )


# ─── Persistence ────────────────────────────────────────────────────────


class MonitoringStore(ABC):
    """Abstract monitoring store."""

    def add_discovery(self, doc: DiscoveredDocument) -> None: ...
    def list_discoveries(self) -> List[DiscoveredDocument]: ...
    def add_run(self, run: MonitoringRun) -> None: ...
    def list_runs(self) -> List[MonitoringRun]: ...
    def upsert_version(self, version: DocumentVersion) -> None: ...
    def list_versions(self, document_key: str) -> List[DocumentVersion]: ...
    def reset(self) -> None: ...


class InMemoryMonitoringStore(MonitoringStore):
    """Thread-safe in-memory store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._discoveries: Dict[str, DiscoveredDocument] = {}
        self._runs: Dict[str, MonitoringRun] = {}
        self._versions: Dict[str, List[DocumentVersion]] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if self._persist_path and self._persist_path.exists():
            self._load()

    # ── JSONL helpers ──────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            for line in self._persist_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                kind = row.pop("__kind__", "discovery")
                if kind == "discovery":
                    d = DiscoveredDocument.model_validate(row)
                    self._discoveries[d.discovery_id] = d
                elif kind == "run":
                    r = MonitoringRun.model_validate(row)
                    self._runs[r.run_id] = r
                elif kind == "version":
                    v = DocumentVersion.model_validate(row)
                    self._versions.setdefault(v.document_key, []).append(v)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load monitoring store: %s", exc)

    def _persist(self, kind: str, payload: Dict[str, Any]) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"__kind__": kind, **payload}) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist monitoring: %s", exc)

    # ── Discoveries ────────────────────────────────────────────────────

    def add_discovery(self, doc: DiscoveredDocument) -> None:
        with self._lock:
            self._discoveries[doc.discovery_id] = doc
        self._persist("discovery", doc.model_dump(mode="json"))

    def list_discoveries(self) -> List[DiscoveredDocument]:
        with self._lock:
            return list(self._discoveries.values())

    def get_discovery(self, discovery_id: str) -> Optional[DiscoveredDocument]:
        with self._lock:
            return self._discoveries.get(discovery_id)

    def find_discovery_by_url(self, url: str) -> Optional[DiscoveredDocument]:
        with self._lock:
            for d in self._discoveries.values():
                if d.document_url == url:
                    return d
        return None

    # ── Runs ───────────────────────────────────────────────────────────

    def add_run(self, run: MonitoringRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run
        self._persist("run", run.model_dump(mode="json"))

    def list_runs(self) -> List[MonitoringRun]:
        with self._lock:
            return list(self._runs.values())

    def get_run(self, run_id: str) -> Optional[MonitoringRun]:
        with self._lock:
            return self._runs.get(run_id)

    # ── Version tracking ───────────────────────────────────────────────

    def upsert_version(self, version: DocumentVersion) -> None:
        with self._lock:
            self._versions.setdefault(version.document_key, []).append(version)
        self._persist("version", version.model_dump(mode="json"))

    def list_versions(self, document_key: str) -> List[DocumentVersion]:
        with self._lock:
            return list(self._versions.get(document_key, []))

    def latest_version(self, document_key: str) -> Optional[DocumentVersion]:
        versions = self.list_versions(document_key)
        if not versions:
            return None
        return versions[-1]

    def reset(self) -> None:
        with self._lock:
            self._discoveries.clear()
            self._runs.clear()
            self._versions.clear()


class MonitoringRepository:
    """Business-rule layer on top of the store."""

    def __init__(self, store: MonitoringStore) -> None:
        self.store = store

    # ── Discoveries ────────────────────────────────────────────────────

    def add_discovery(self, doc: DiscoveredDocument) -> DiscoveredDocument:
        # Mark as already_known if we've seen this URL before.
        existing = self.store.find_discovery_by_url(doc.document_url)
        if existing is not None:
            doc.already_known = True
            if doc.version and existing.version == doc.version:
                doc.change_type = ChangeType.UNCHANGED
        self.store.add_discovery(doc)
        # Track version.
        document_key = self._document_key(doc)
        self.store.upsert_version(
            DocumentVersion(
                document_key=document_key,
                version=doc.version or doc.discovered_at.isoformat(),
                document_url=doc.document_url,
                publication_date=doc.publication_date,
                checksum=doc.checksum_hint,
            )
        )
        return doc

    def search(self, flt: DiscoveryFilter) -> PaginatedDiscoveries:
        items = list(self.store.list_discoveries())
        if flt.source is not None:
            items = [d for d in items if d.source == flt.source]
        if flt.change_type is not None:
            items = [d for d in items if d.change_type == flt.change_type]
        if flt.document_url is not None:
            items = [d for d in items if d.document_url == flt.document_url]
        if flt.after is not None:
            items = [d for d in items if d.discovered_at >= flt.after]
        if flt.before is not None:
            items = [d for d in items if d.discovered_at <= flt.before]
        items.sort(key=lambda d: d.discovered_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedDiscoveries(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def get(self, discovery_id: str) -> Optional[DiscoveredDocument]:
        return self.store.get_discovery(discovery_id)

    # ── Runs ───────────────────────────────────────────────────────────

    def add_run(self, run: MonitoringRun) -> MonitoringRun:
        self.store.add_run(run)
        return run

    def list_runs(
        self, source: Optional[RegulatorySource] = None
    ) -> List[MonitoringRun]:
        runs = self.store.list_runs()
        if source is not None:
            runs = [r for r in runs if r.source == source]
        return sorted(runs, key=lambda r: r.started_at, reverse=True)

    def get_run(self, run_id: str) -> Optional[MonitoringRun]:
        return self.store.get_run(run_id)

    # ── Version tracking ───────────────────────────────────────────────

    def versions_for(self, doc: DiscoveredDocument) -> List[DocumentVersion]:
        return self.store.list_versions(self._document_key(doc))

    def latest_version(self, doc: DiscoveredDocument) -> Optional[DocumentVersion]:
        return self.store.latest_version(self._document_key(doc))

    @staticmethod
    def _document_key(doc: DiscoveredDocument) -> str:
        return f"{doc.source.value}:{doc.document_url}"


# ─── Document discovery engine ──────────────────────────────────────────


class DocumentDiscoveryEngine:
    """Runs a single :class:`SourceAdapter` and converts the result."""

    def __init__(
        self,
        registry: SourceRegistry,
        repository: MonitoringRepository,
    ) -> None:
        self.registry = registry
        self.repository = repository

    async def discover(self, source: RegulatorySource) -> List[DiscoveredDocument]:
        adapter = self.registry.build(source)
        raw = await adapter.discover()
        out: List[DiscoveredDocument] = []
        for d in raw:
            out.append(self.repository.add_discovery(d))
        return out

    async def discover_all(self) -> List[DiscoveredDocument]:
        out: List[DiscoveredDocument] = []
        for source in self.registry.list_enabled_sources():
            try:
                out.extend(await self.discover(source))
            except Exception as exc:  # pragma: no cover
                logger.exception("discover_all failed for %s: %s", source, exc)
        return out


# ─── Health ─────────────────────────────────────────────────────────────


class MonitoringHealthChecker:
    """Computes per-source and aggregate health."""

    def __init__(
        self,
        registry: SourceRegistry,
        repository: MonitoringRepository,
    ) -> None:
        self.registry = registry
        self.repository = repository

    def health(self) -> MonitoringHealth:
        runs = self.repository.list_runs()
        total = len(runs)
        total_discoveries = sum(r.discovered_count for r in runs)
        sources: List[SourceHealth] = []
        worst = MonitoringStatus.HEALTHY
        for source in self.registry.list_sources():
            s_runs = [r for r in runs if r.source == source]
            if not s_runs:
                sources.append(
                    SourceHealth(
                        source=source,
                        status=MonitoringStatus.UNKNOWN,
                        last_run_at=None,
                    )
                )
                worst = _max_status(worst, MonitoringStatus.UNKNOWN)
                continue
            last = s_runs[0]
            consecutive_failures = 0
            for r in s_runs:
                if r.status == MonitoringStatus.HEALTHY:
                    break
                consecutive_failures += 1
            sources.append(
                SourceHealth(
                    source=source,
                    status=last.status,
                    last_run_at=last.started_at,
                    last_success_at=(
                        next(
                            (
                                r.started_at
                                for r in s_runs
                                if r.status == MonitoringStatus.HEALTHY
                            ),
                            None,
                        )
                    ),
                    consecutive_failures=consecutive_failures,
                    last_error=last.error_message,
                    last_discovery_count=last.discovered_count,
                )
            )
            worst = _max_status(worst, last.status)
        return MonitoringHealth(
            overall_status=worst,
            sources=sources,
            total_runs=total,
            total_discoveries=total_discoveries,
        )


def _max_status(a: MonitoringStatus, b: MonitoringStatus) -> MonitoringStatus:
    order = {
        MonitoringStatus.HEALTHY: 0,
        MonitoringStatus.UNKNOWN: 1,
        MonitoringStatus.DEGRADED: 2,
        MonitoringStatus.UNHEALTHY: 3,
    }
    return a if order[a] >= order[b] else b


# ─── Top-level monitor ──────────────────────────────────────────────────


class RegulatoryMonitor:
    """High-level orchestrator: one :class:`MonitoringRun` per source."""

    def __init__(
        self,
        registry: SourceRegistry,
        discovery_engine: DocumentDiscoveryEngine,
        repository: MonitoringRepository,
    ) -> None:
        self.registry = registry
        self.discovery_engine = discovery_engine
        self.repository = repository

    async def run_source(
        self,
        source: RegulatorySource,
        *,
        force: bool = False,
    ) -> RunMonitorResponse:
        cfg = self.registry.get_config(source)
        if cfg is not None and not cfg.enabled and not force:
            run = MonitoringRun(source=source, status=MonitoringStatus.UNHEALTHY)
            run.finish(
                MonitoringStatus.UNHEALTHY,
                error_message="source disabled",
            )
            self.repository.add_run(run)
            get_monitoring_metrics().record_monitor_run(source.value, success=False)
            return RunMonitorResponse(run=run, discoveries=[])

        run = MonitoringRun(source=source)
        discoveries: List[DiscoveredDocument] = []
        try:
            with track_request(
                endpoint=f"/api/v1/monitoring/run/{source.value}",
                strategy="monitoring",
            ):
                discoveries = await self.discovery_engine.discover(source)
        except Exception as exc:
            logger.exception("monitoring run failed for %s: %s", source, exc)
            run.finish(
                MonitoringStatus.UNHEALTHY,
                error_message=str(exc),
            )
            self.repository.add_run(run)
            get_monitoring_metrics().record_monitor_run(source.value, success=False)
            get_monitoring_metrics().record_discovery_failure(source.value, "exception")
            return RunMonitorResponse(run=run, discoveries=[])

        new_count = sum(1 for d in discoveries if d.change_type == ChangeType.NEW)
        updated_count = sum(
            1 for d in discoveries if d.change_type == ChangeType.UPDATED
        )
        run.finish(
            MonitoringStatus.HEALTHY,
            discovered_count=len(discoveries),
            new_count=new_count,
            updated_count=updated_count,
        )
        self.repository.add_run(run)
        get_monitoring_metrics().record_monitor_run(source.value, success=True)
        get_monitoring_metrics().record_discovery(source.value, len(discoveries))
        return RunMonitorResponse(run=run, discoveries=discoveries)

    async def run_all(self) -> RunAllResponse:
        runs: List[MonitoringRun] = []
        all_discoveries: List[DiscoveredDocument] = []
        for source in self.registry.list_enabled_sources():
            response = await self.run_source(source)
            runs.append(response.run)
            all_discoveries.extend(response.discoveries)
        return RunAllResponse(
            runs=runs,
            discoveries=all_discoveries,
            total_discoveries=len(all_discoveries),
        )


# ─── Scheduler ──────────────────────────────────────────────────────────


class MonitoringScheduler:
    """In-process asyncio scheduler that ticks the monitor at intervals.

    The scheduler is intentionally lightweight: a single background
    ``asyncio.Task`` is created when :meth:`start` is called and
    cancelled on :meth:`stop`. Tests can drive ticks manually with
    :meth:`tick` to avoid timing-based flakes.
    """

    def __init__(
        self,
        monitor: RegulatoryMonitor,
        registry: SourceRegistry,
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self.monitor = monitor
        self.registry = registry
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task[Any]] = None
        self._running = False
        self._lock = asyncio.Lock()
        self.last_tick_at: Optional[datetime] = None
        self.next_tick_at: Optional[datetime] = None
        self._ticks = 0

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        async with self._lock:
            if not self._running:
                return
            self._running = False
            if self._task is not None:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None

    async def tick(self) -> RunAllResponse:
        """Manually drive a single round of monitoring."""
        self.last_tick_at = datetime.now(timezone.utc)
        self._ticks += 1
        return await self.monitor.run_all()

    async def _run_forever(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                logger.exception("scheduler tick failed: %s", exc)
            self.next_tick_at = (
                datetime.now(timezone.utc).timestamp() + self.interval_seconds
            )
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise

    def status(self) -> SchedulerStatus:
        return SchedulerStatus(
            running=self._running,
            active_tasks=1 if self._task is not None and not self._task.done() else 0,
            sources=self.registry.list_enabled_sources(),
            interval_seconds=self.interval_seconds,
            last_tick_at=self.last_tick_at,
            next_tick_at=(
                datetime.fromtimestamp(self.next_tick_at, tz=timezone.utc)
                if self.next_tick_at
                else None
            ),
        )


# ─── Top-level service / factory ────────────────────────────────────────


class MonitoringService:
    """DI-friendly top-level facade."""

    def __init__(
        self,
        *,
        store: Optional[MonitoringStore] = None,
        registry: Optional[SourceRegistry] = None,
        repository: Optional[MonitoringRepository] = None,
        discovery_engine: Optional[DocumentDiscoveryEngine] = None,
        monitor: Optional[RegulatoryMonitor] = None,
        health_checker: Optional[MonitoringHealthChecker] = None,
        scheduler: Optional[MonitoringScheduler] = None,
    ) -> None:
        self.store = store or InMemoryMonitoringStore(
            persist_path=Path(settings.STORAGE_ROOT) / "monitoring" / "monitoring.jsonl"
        )
        self.registry = registry or SourceRegistry()
        # Register default configs so listing-enabled_sources works.
        for s in self.registry.list_sources():
            if self.registry.get_config(s) is None:
                self.registry.set_config(s, SourceRegistry._default_config(s))
        self.repository = repository or MonitoringRepository(self.store)
        self.discovery_engine = discovery_engine or DocumentDiscoveryEngine(
            self.registry, self.repository
        )
        self.monitor = monitor or RegulatoryMonitor(
            self.registry, self.discovery_engine, self.repository
        )
        self.health_checker = health_checker or MonitoringHealthChecker(
            self.registry, self.repository
        )
        self.scheduler = scheduler or MonitoringScheduler(self.monitor, self.registry)

    # ── Run / discovery ────────────────────────────────────────────────

    def metrics_snapshot(self) -> Dict[str, Any]:
        """Expose monitoring metrics for the dashboard."""
        try:
            return get_monitoring_metrics().snapshot()
        except Exception:  # pragma: no cover
            return {}

    async def run_source(
        self, source: RegulatorySource, *, force: bool = False
    ) -> RunMonitorResponse:
        return await self.monitor.run_source(source, force=force)

    async def run_all(self) -> RunAllResponse:
        return await self.monitor.run_all()

    def search(self, flt: DiscoveryFilter) -> PaginatedDiscoveries:
        return self.repository.search(flt)

    def get_discovery(self, discovery_id: str) -> Optional[DiscoveredDocument]:
        return self.repository.get(discovery_id)

    def list_runs(
        self, source: Optional[RegulatorySource] = None
    ) -> List[MonitoringRun]:
        return self.repository.list_runs(source=source)

    def get_run(self, run_id: str) -> Optional[MonitoringRun]:
        return self.repository.get_run(run_id)

    def versions_for(self, doc: DiscoveredDocument) -> List[DocumentVersion]:
        return self.repository.versions_for(doc)

    # ── Health / scheduler ─────────────────────────────────────────────

    def health(self) -> MonitoringHealth:
        return self.health_checker.health()

    async def start_scheduler(self) -> None:
        await self.scheduler.start()

    async def stop_scheduler(self) -> None:
        await self.scheduler.stop()

    def scheduler_status(self) -> SchedulerStatus:
        return self.scheduler.status()

    async def scheduler_tick(self) -> RunAllResponse:
        return await self.scheduler.tick()

    # ── Registry management ─────────────────────────────────────────────

    def register_custom_source(
        self,
        source: RegulatorySource,
        factory: Callable[[SourceConfig], SourceAdapter],
        config: Optional[SourceConfig] = None,
    ) -> None:
        self.registry.register(source, factory, config)

    def sources(self) -> List[RegulatorySource]:
        return self.registry.list_sources()

    def set_source_config(self, source: RegulatorySource, config: SourceConfig) -> None:
        self.registry.set_config(source, config)


def build_default_monitoring_service() -> MonitoringService:
    return MonitoringService()


__all__ = [
    "DocumentDiscoveryEngine",
    "IRDAISourceAdapter",
    "InMemoryMonitoringStore",
    "MoFSourceAdapter",
    "MonitoringHealthChecker",
    "MonitoringRepository",
    "MonitoringScheduler",
    "MonitoringService",
    "MonitoringStore",
    "PFRDASourceAdapter",
    "RBISourceAdapter",
    "RegulatoryMonitor",
    "SEBISourceAdapter",
    "SourceAdapter",
    "SourceRegistry",
    "build_default_monitoring_service",
]
