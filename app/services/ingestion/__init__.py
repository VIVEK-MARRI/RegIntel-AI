"""Module 7.2 — Automated Regulatory Ingestion.

Pipeline
--------
::

    Monitor
      ↓
    Discover Document
      ↓
    Download
      ↓
    Parse
      ↓
    Chunk
      ↓
    Embed
      ↓
    Index
      ↓
    Audit

Public surface
--------------
* :class:`AutoIngestionService` — top-level DI-friendly facade.
* :class:`DocumentPipelineCoordinator` — runs the 5-step pipeline.
* :class:`IngestionScheduler` — background asyncio scheduler.
* :class:`RegistrySynchronizer` — syncs discoveries with the
  document registry.
* :class:`IngestionAuditService` — append-only audit trail.
* :class:`DuplicateDetector` — checksum-based de-duplication.
* :class:`FailureRecovery` — bounded retry / backoff helper.

This module REUSES existing services in production:

* :class:`app.services.parser_service.ParserService`
* :class:`app.services.structure.chunker.HierarchicalChunkerService`
* :class:`app.services.chunk_registry.ChunkRegistryService`
* :class:`app.services.embedding.pipeline.EmbeddingPipeline`
* :class:`app.services.embedding.index_manager.VectorIndexManager`
* :class:`app.services.analytics.service.AnalyticsService`

For test ergonomics (and to keep this module self-contained for
unit / scheduler / audit tests), every collaborator is pluggable via
a small Protocol surface. In production the real services are
wired in :func:`build_default_auto_ingestion_service`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from pydantic import BaseModel

from app.core.config import settings
from app.schemas.ingestion import (
    IngestionAuditEntry,
    IngestionFilter,
    IngestionRun,
    IngestionRunResponse,
    IngestionSchedulerStatus,
    IngestionStats,
    IngestionStatus,
    IngestionStep,
    IngestionStepName,
    IngestionStepStatus,
    IngestionTriggerRequest,
    PaginatedIngestionRuns,
    RegistrySyncResult,
)
from app.schemas.monitoring import DiscoveredDocument
from app.services.observability import (
    get_ingestion_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Pluggable collaborators (Protocol) ───────────────────────────────────


@runtime_checkable
class DownloaderProtocol(Protocol):
    async def download(self, url: str) -> bytes: ...


@runtime_checkable
class ParserProtocol(Protocol):
    """Minimal surface for the existing ParserService.

    The real ``ParserService.parse_document(document_id, ...)`` returns
    a list of ``{"page_number", "content"}`` dicts.  The pipeline calls
    this method with a document_id and an injected page-store callback.
    """

    async def parse(self, document_id: Any) -> List[Dict[str, Any]]: ...


@runtime_checkable
class ChunkerProtocol(Protocol):
    async def chunk(
        self, document_id: Any
    ) -> List[Dict[str, Any]]: ...


@runtime_checkable
class EmbedderProtocol(Protocol):
    async def embed(self, document_id: Any) -> Dict[str, Any]: ...


@runtime_checkable
class IndexerProtocol(Protocol):
    async def ensure_index(self, model_name: str) -> str: ...


@runtime_checkable
class DocumentRegistryProtocol(Protocol):
    """Minimal contract for the existing document registry."""

    async def register(self, payload: Dict[str, Any]) -> Any: ...
    async def get_by_checksum(self, checksum: str) -> Optional[Any]: ...
    async def get_by_id(self, document_id: Any) -> Optional[Any]: ...


# ─── In-memory defaults for collaborators (used in tests) ──────────────


class _BytesDownloader:
    """Default downloader: returns a stub PDF byte string keyed by URL."""

    def __init__(self, payload: bytes = b"%PDF-1.4\n%stub\n") -> None:
        self._payload = payload

    async def download(self, url: str) -> bytes:  # noqa: D401
        # Synthesise a deterministic, content-addressed payload.
        seed = hashlib.sha256(url.encode("utf-8")).digest()
        return b"%PDF-1.4\n" + seed[:64]


class _NoOpParser:
    async def parse(self, document_id: Any) -> List[Dict[str, Any]]:
        return [{"page_number": 1, "content": f"page for {document_id}"}]


class _NoOpChunker:
    async def chunk(self, document_id: Any) -> List[Dict[str, Any]]:
        return [
            {
                "chunk_id": f"chunk-{i}",
                "content": f"chunk {i} for {document_id}",
                "section": "auto",
                "subsection": "",
                "page_number": 1,
                "token_count": 10,
            }
            for i in range(3)
        ]


class _NoOpEmbedder:
    async def embed(self, document_id: Any) -> Dict[str, Any]:
        # Mirrors ``EmbeddingPipeline.process_document_embeddings`` return.
        return {
            "total_chunks": 3,
            "processed_chunks": 3,
            "failed_chunks": 0,
            "duration_ms": 1.0,
        }


class _NoOpIndexer:
    async def ensure_index(self, model_name: str) -> str:
        return f"idx_{model_name}"


class _NoOpRegistry:
    def __init__(self) -> None:
        self._by_checksum: Dict[str, Any] = {}
        self._by_id: Dict[str, Any] = {}

    async def register(self, payload: Dict[str, Any]) -> Any:
        doc_id = payload.get("document_id") or f"doc-{uuid.uuid4().hex[:8]}"
        payload = {**payload, "document_id": doc_id}
        self._by_id[doc_id] = payload
        if payload.get("checksum"):
            self._by_checksum[payload["checksum"]] = payload
        return payload

    async def get_by_checksum(self, checksum: str) -> Optional[Any]:
        return self._by_checksum.get(checksum)

    async def get_by_id(self, document_id: Any) -> Optional[Any]:
        return self._by_id.get(str(document_id))


# ─── Persistence ────────────────────────────────────────────────────────


class IngestionStore(ABC):
    """Abstract ingestion store."""

    def add_run(self, run: IngestionRun) -> None: ...
    def list_runs(self) -> List[IngestionRun]: ...
    def add_audit(self, entry: IngestionAuditEntry) -> None: ...
    def list_audits(self) -> List[IngestionAuditEntry]: ...
    def reset(self) -> None: ...


class InMemoryIngestionStore(IngestionStore):
    """Thread-safe in-memory ingestion store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._runs: Dict[str, IngestionRun] = {}
        self._audits: Dict[str, IngestionAuditEntry] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if self._persist_path and self._persist_path.exists():
            self._load()

    def _load(self) -> None:
        try:
            for line in self._persist_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                kind = row.pop("__kind__", "run")
                if kind == "run":
                    r = IngestionRun.model_validate(row)
                    self._runs[r.run_id] = r
                elif kind == "audit":
                    a = IngestionAuditEntry.model_validate(row)
                    self._audits[a.audit_id] = a
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load ingestion store: %s", exc)

    def _persist(self, kind: str, payload: Dict[str, Any]) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"__kind__": kind, **payload}) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist ingestion: %s", exc)

    # ── Runs ───────────────────────────────────────────────────────────

    def add_run(self, run: IngestionRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run
        self._persist("run", run.model_dump(mode="json"))

    def list_runs(self) -> List[IngestionRun]:
        with self._lock:
            return list(self._runs.values())

    def get_run(self, run_id: str) -> Optional[IngestionRun]:
        with self._lock:
            return self._runs.get(run_id)

    # ── Audits ─────────────────────────────────────────────────────────

    def add_audit(self, entry: IngestionAuditEntry) -> None:
        with self._lock:
            self._audits[entry.audit_id] = entry
        self._persist("audit", entry.model_dump(mode="json"))

    def list_audits(self) -> List[IngestionAuditEntry]:
        with self._lock:
            return list(self._audits.values())

    def list_audits_for_run(self, run_id: str) -> List[IngestionAuditEntry]:
        with self._lock:
            return [a for a in self._audits.values() if a.run_id == run_id]

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()
            self._audits.clear()


class IngestionRepository:
    """Business-rule layer over the store."""

    def __init__(self, store: IngestionStore) -> None:
        self.store = store

    # ── Runs ───────────────────────────────────────────────────────────

    def add_run(self, run: IngestionRun) -> IngestionRun:
        self.store.add_run(run)
        return run

    def get_run(self, run_id: str) -> Optional[IngestionRun]:
        return self.store.get_run(run_id)

    def list_runs(self, flt: IngestionFilter) -> PaginatedIngestionRuns:
        items = self.store.list_runs()
        if flt.source is not None:
            items = [r for r in items if r.source == flt.source]
        if flt.status is not None:
            items = [r for r in items if r.status == flt.status]
        if flt.document_id is not None:
            items = [r for r in items if r.document_id == flt.document_id]
        if flt.is_duplicate is not None:
            items = [r for r in items if r.is_duplicate == flt.is_duplicate]
        if flt.after is not None:
            items = [r for r in items if r.started_at >= flt.after]
        if flt.before is not None:
            items = [r for r in items if r.started_at <= flt.before]
        items.sort(key=lambda r: r.started_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedIngestionRuns(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def latest_run_for_document(self, document_id: str) -> Optional[IngestionRun]:
        runs = [r for r in self.store.list_runs() if r.document_id == document_id]
        if not runs:
            return None
        return max(runs, key=lambda r: r.started_at)

    # ── Audits ─────────────────────────────────────────────────────────

    def add_audit(self, entry: IngestionAuditEntry) -> IngestionAuditEntry:
        self.store.add_audit(entry)
        return entry

    def list_audits(
        self,
        run_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[IngestionAuditEntry]:
        audits = (
            self.store.list_audits_for_run(run_id)
            if run_id is not None
            else self.store.list_audits()
        )
        audits.sort(key=lambda a: a.timestamp, reverse=True)
        return audits[:limit]

    # ── Stats ──────────────────────────────────────────────────────────

    def stats(self) -> IngestionStats:
        runs = self.store.list_runs()
        if not runs:
            return IngestionStats()
        by_source: Dict[str, int] = {}
        by_status: Dict[IngestionStatus, int] = {}
        chunks = 0
        embs = 0
        pages = 0
        completed = 0
        failed = 0
        skipped = 0
        duplicates = 0
        incrementals = 0
        total_duration = 0.0
        for r in runs:
            by_source[r.source or "unknown"] = by_source.get(r.source or "unknown", 0) + 1
            by_status[r.status] = by_status.get(r.status, 0) + 1
            chunks += r.chunks_created
            embs += r.embeddings_created
            pages += r.pages_parsed
            total_duration += r.duration_ms
            if r.status == IngestionStatus.COMPLETED:
                completed += 1
            if r.status == IngestionStatus.FAILED:
                failed += 1
            if r.status == IngestionStatus.SKIPPED:
                skipped += 1
            if r.is_duplicate:
                duplicates += 1
            if r.is_incremental_update:
                incrementals += 1
        return IngestionStats(
            total_runs=len(runs),
            completed_runs=completed,
            failed_runs=failed,
            skipped_runs=skipped,
            duplicate_runs=duplicates,
            incremental_updates=incrementals,
            chunks_created=chunks,
            embeddings_created=embs,
            pages_parsed=pages,
            average_duration_ms=total_duration / len(runs) if runs else 0.0,
            by_source=by_source,
            by_status=by_status,
        )


# ─── Duplicate detection ────────────────────────────────────────────────


class DuplicateDetector:
    """Checksum-based duplicate detector."""

    def __init__(self, registry: DocumentRegistryProtocol) -> None:
        self.registry = registry

    async def is_duplicate(self, checksum: str) -> bool:
        existing = await self.registry.get_by_checksum(checksum)
        return existing is not None

    @staticmethod
    def compute_checksum(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


# ─── Failure recovery ──────────────────────────────────────────────────


@dataclass
class FailureRecovery:
    """Bounded exponential backoff."""

    max_retries: int = 3
    backoff_factor: float = 0.5

    async def run(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        step: IngestionStepName,
    ) -> Any:
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                sleep_for = self.backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "ingestion_step_retry",
                    extra={
                        "step": step.value,
                        "attempt": attempt,
                        "sleep_for": sleep_for,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(sleep_for)
        assert last_exc is not None
        raise last_exc


# ─── Audit service ──────────────────────────────────────────────────────


class IngestionAuditService:
    """Append-only audit trail for ingestion events."""

    def __init__(self, repository: IngestionRepository) -> None:
        self.repository = repository

    def record(
        self,
        run_id: str,
        event: str,
        *,
        step: Optional[IngestionStepName] = None,
        level: str = "info",
        message: Optional[str] = None,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionAuditEntry:
        entry = IngestionAuditEntry(
            run_id=run_id,
            step=step,
            event=event,
            level=level,
            message=message,
            document_id=document_id,
            metadata=metadata or {},
        )
        return self.repository.add_audit(entry)


# ─── Pipeline coordinator ──────────────────────────────────────────────


class DocumentPipelineCoordinator:
    """Executes the 5-step ingestion pipeline for a single document.

    The coordinator is intentionally pluggable: in tests we use the
    no-op collaborators; in production the real parser/chunker/
    embedder are wired in :func:`build_default_auto_ingestion_service`.
    """

    def __init__(
        self,
        downloader: DownloaderProtocol,
        parser: ParserProtocol,
        chunker: ChunkerProtocol,
        embedder: EmbedderProtocol,
        indexer: IndexerProtocol,
        registry: DocumentRegistryProtocol,
        duplicate_detector: DuplicateDetector,
        recovery: FailureRecovery,
        audit_service: IngestionAuditService,
        chunk_persister: Any = None,
    ) -> None:
        self.downloader = downloader
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.indexer = indexer
        self.registry = registry
        self.duplicate_detector = duplicate_detector
        self.recovery = recovery
        self.audit_service = audit_service
        self.chunk_persister = chunk_persister

    async def run(
        self,
        request: IngestionTriggerRequest,
        run: IngestionRun,
    ) -> IngestionRun:
        # ── 1. Download ────────────────────────────────────────────────
        download_step = IngestionStep(step=IngestionStepName.DOWNLOAD)
        run.steps.append(download_step)
        try:
            with track_request(endpoint="/api/v1/ingestion/download", strategy="ingestion"):
                download_step.start()
                run.status = IngestionStatus.DOWNLOADING
                if not request.url:
                    raise ValueError("ingestion request missing 'url'")
                content = await self.recovery.run(
                    lambda: self.downloader.download(request.url or ""),
                    step=IngestionStepName.DOWNLOAD,
                )
                checksum = DuplicateDetector.compute_checksum(content)
                download_step.finish(
                    IngestionStepStatus.SUCCEEDED,
                    metadata={"bytes": len(content), "checksum": checksum},
                )
                run.checksum = checksum
                self.audit_service.record(
                    run.run_id,
                    "download_succeeded",
                    step=IngestionStepName.DOWNLOAD,
                    metadata={"bytes": len(content), "checksum": checksum},
                )
        except Exception as exc:
            logger.exception("download failed: %s", exc)
            download_step.finish(IngestionStepStatus.FAILED, error=str(exc))
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"download: {exc}"
            self.audit_service.record(
                run.run_id,
                "download_failed",
                step=IngestionStepName.DOWNLOAD,
                level="error",
                message=str(exc),
            )
            return run

        # ── Duplicate detection ────────────────────────────────────────
        if not request.force and await self.duplicate_detector.is_duplicate(checksum):
            run.is_duplicate = True
            run.status = IngestionStatus.SKIPPED
            self.audit_service.record(
                run.run_id,
                "ingestion_skipped_duplicate",
                level="warning",
                message=f"checksum={checksum}",
            )
            return run

        # ── 1b. Save downloaded content to file ─────────────────────────
        from pathlib import Path as _Path
        file_name = _Path(request.url or "").name or "document.pdf"
        file_path = _Path(settings.STORAGE_ROOT) / "documents" / f"{checksum[:8]}_{file_name}"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        # ── 1c. Register document ───────────────────────────────────────
        run.status = IngestionStatus.DOWNLOADED
        try:
            doc = await self.registry.register(
                {
                    "title": request.title or run.title or "(untitled)",
                    "source": request.source or run.source or "UNKNOWN",
                    "file_name": file_name,
                    "file_path": str(file_path.relative_to(settings.STORAGE_ROOT)),
                    "checksum": checksum,
                    "metadata": {
                        "url": request.url,
                        "version": run.version,
                    },
                }
            )
            run.document_id = str(doc.get("document_id")) if isinstance(doc, dict) else str(doc)
        except Exception as exc:
            logger.exception("registry register failed: %s", exc)
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"register: {exc}"
            self.audit_service.record(
                run.run_id,
                "register_failed",
                level="error",
                message=str(exc),
            )
            return run

        # ── 2. Parse ───────────────────────────────────────────────────
        parse_step = IngestionStep(step=IngestionStepName.PARSE)
        run.steps.append(parse_step)
        try:
            with track_request(endpoint="/api/v1/ingestion/parse", strategy="ingestion"):
                parse_step.start()
                run.status = IngestionStatus.PARSING
                pages = await self.recovery.run(
                    lambda: self.parser.parse(run.document_id),
                    step=IngestionStepName.PARSE,
                )
                run.pages_parsed = len(pages)
                parse_step.finish(
                    IngestionStepStatus.SUCCEEDED,
                    metadata={"page_count": len(pages)},
                )
                self.audit_service.record(
                    run.run_id,
                    "parse_succeeded",
                    step=IngestionStepName.PARSE,
                    metadata={"page_count": len(pages)},
                )
        except Exception as exc:
            logger.exception("parse failed: %s", exc)
            parse_step.finish(IngestionStepStatus.FAILED, error=str(exc))
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"parse: {exc}"
            self.audit_service.record(
                run.run_id,
                "parse_failed",
                step=IngestionStepName.PARSE,
                level="error",
                message=str(exc),
            )
            return run

        # ── 3. Chunk ───────────────────────────────────────────────────
        logger.info("Starting chunking step for document_id=%s", run.document_id)
        chunk_step = IngestionStep(step=IngestionStepName.CHUNK)
        run.steps.append(chunk_step)
        try:
            with track_request(endpoint="/api/v1/ingestion/chunk", strategy="ingestion"):
                chunk_step.start()
                run.status = IngestionStatus.CHUNKING
                logger.info("Calling chunker.chunk for document_id=%s", run.document_id)
                chunks = await self.recovery.run(
                    lambda: self.chunker.chunk(run.document_id),
                    step=IngestionStepName.CHUNK,
                )
                logger.info("Chunker returned %d chunks", len(chunks))
                run.chunks_created = len(chunks)
                # Persist chunks to database
                if self.chunk_persister is not None and run.document_id is not None:
                    try:
                        from uuid import UUID as _UUID
                        doc_id_uuid = _UUID(str(run.document_id))
                        persisted = await self.chunk_persister.register_chunks_bulk(doc_id_uuid, chunks)
                        logger.info("Persisted %d chunks to database", len(persisted))
                    except Exception as persist_exc:
                        logger.error("Failed to persist chunks: %s", persist_exc)
                        raise
                chunk_step.finish(
                    IngestionStepStatus.SUCCEEDED,
                    metadata={"chunk_count": len(chunks)},
                )
                self.audit_service.record(
                    run.run_id,
                    "chunk_succeeded",
                    step=IngestionStepName.CHUNK,
                    metadata={"chunk_count": len(chunks)},
                )
        except Exception as exc:
            logger.exception("chunk failed: %s", exc)
            chunk_step.finish(IngestionStepStatus.FAILED, error=str(exc))
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"chunk: {exc}"
            self.audit_service.record(
                run.run_id,
                "chunk_failed",
                step=IngestionStepName.CHUNK,
                level="error",
                message=str(exc),
            )
            return run

        # ── 4. Embed ───────────────────────────────────────────────────
        embed_step = IngestionStep(step=IngestionStepName.EMBED)
        run.steps.append(embed_step)
        try:
            with track_request(endpoint="/api/v1/ingestion/embed", strategy="ingestion"):
                embed_step.start()
                run.status = IngestionStatus.EMBEDDING
                result = await self.recovery.run(
                    lambda: self.embedder.embed(run.document_id),
                    step=IngestionStepName.EMBED,
                )
                run.embeddings_created = int(result.get("processed_chunks", 0))
                embed_step.finish(
                    IngestionStepStatus.SUCCEEDED,
                    metadata={
                        "total_chunks": result.get("total_chunks"),
                        "failed_chunks": result.get("failed_chunks"),
                    },
                )
                self.audit_service.record(
                    run.run_id,
                    "embed_succeeded",
                    step=IngestionStepName.EMBED,
                    metadata={
                        "processed_chunks": run.embeddings_created,
                    },
                )
        except Exception as exc:
            logger.exception("embed failed: %s", exc)
            embed_step.finish(IngestionStepStatus.FAILED, error=str(exc))
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"embed: {exc}"
            self.audit_service.record(
                run.run_id,
                "embed_failed",
                step=IngestionStepName.EMBED,
                level="error",
                message=str(exc),
            )
            return run

        # ── 5. Index ───────────────────────────────────────────────────
        index_step = IngestionStep(step=IngestionStepName.INDEX)
        run.steps.append(index_step)
        try:
            with track_request(endpoint="/api/v1/ingestion/index", strategy="ingestion"):
                index_step.start()
                run.status = IngestionStatus.INDEXING
                index_name = await self.recovery.run(
                    lambda: self.indexer.ensure_index("default"),
                    step=IngestionStepName.INDEX,
                )
                index_step.finish(
                    IngestionStepStatus.SUCCEEDED,
                    metadata={"index_name": index_name},
                )
                self.audit_service.record(
                    run.run_id,
                    "index_succeeded",
                    step=IngestionStepName.INDEX,
                    metadata={"index_name": index_name},
                )
        except Exception as exc:
            logger.exception("index failed: %s", exc)
            index_step.finish(IngestionStepStatus.FAILED, error=str(exc))
            run.status = IngestionStatus.FAILED
            run.failure_reason = f"index: {exc}"
            self.audit_service.record(
                run.run_id,
                "index_failed",
                step=IngestionStepName.INDEX,
                level="error",
                message=str(exc),
            )
            return run

        # ── Done ───────────────────────────────────────────────────────
        run.status = IngestionStatus.COMPLETED
        self.audit_service.record(
            run.run_id,
            "ingestion_completed",
            metadata={
                "chunks_created": run.chunks_created,
                "embeddings_created": run.embeddings_created,
                "pages_parsed": run.pages_parsed,
            },
        )
        return run


# ─── Registry synchroniser ─────────────────────────────────────────────


class RegistrySynchronizer:
    """Reconciles discoveries from the monitoring engine with the
    document registry.  Counts:

    * matched — discovery references a known document
    * new_in_registry — discovery was not yet known
    * already_in_registry — checksum already exists
    """

    def __init__(
        self,
        registry: DocumentRegistryProtocol,
        duplicate_detector: DuplicateDetector,
    ) -> None:
        self.registry = registry
        self.duplicate_detector = duplicate_detector

    async def sync(
        self, discoveries: List[DiscoveredDocument]
    ) -> RegistrySyncResult:
        start = time.perf_counter()
        result = RegistrySyncResult()
        for d in discoveries:
            try:
                # Compute a stable URL-based key as the checksum hint.
                checksum = DuplicateDetector.compute_checksum(
                    d.document_url.encode("utf-8")
                )
                is_dup = await self.duplicate_detector.is_duplicate(checksum)
                if is_dup:
                    result.already_in_registry += 1
                    result.details.append(
                        {
                            "discovery_id": d.discovery_id,
                            "url": d.document_url,
                            "action": "already_in_registry",
                        }
                    )
                else:
                    await self.registry.register(
                        {
                            "title": d.title,
                            "source": d.source.value,
                            "file_name": Path(d.document_url).name or "document",
                            "checksum": checksum,
                            "metadata": {
                                "url": d.document_url,
                                "version": d.version,
                                "publication_date": (
                                    d.publication_date.isoformat()
                                    if d.publication_date
                                    else None
                                ),
                                "discovery_id": d.discovery_id,
                            },
                        }
                    )
                    result.new_in_registry += 1
                    result.details.append(
                        {
                            "discovery_id": d.discovery_id,
                            "url": d.document_url,
                            "action": "registered",
                        }
                    )
                result.matched += 1
            except Exception as exc:
                result.errors += 1
                result.details.append(
                    {
                        "discovery_id": d.discovery_id,
                        "url": d.document_url,
                        "action": "error",
                        "error": str(exc),
                    }
                )
        result.duration_ms = (time.perf_counter() - start) * 1000.0
        return result


# ─── Scheduler ──────────────────────────────────────────────────────────


class IngestionScheduler:
    """Background asyncio scheduler that periodically ingests new
    discoveries from the monitoring engine.

    Like :class:`MonitoringScheduler`, ticks are driven manually in
    tests via :meth:`tick` to avoid timing-based flakes.
    """

    def __init__(
        self,
        ingestion_service: "AutoIngestionService",  # forward ref
        *,
        interval_seconds: int = 3600,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task[Any]] = None
        self._running = False
        self._lock = asyncio.Lock()
        self.last_tick_at: Optional[datetime] = None
        self.next_tick_at: Optional[datetime] = None
        self.last_run_id: Optional[str] = None

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

    async def tick(self) -> List[IngestionRun]:
        """Run a single round: ingest any un-ingested discoveries."""
        self.last_tick_at = datetime.now(timezone.utc)
        runs = await self.ingestion_service.ingest_pending_discoveries()
        if runs:
            self.last_run_id = runs[-1].run_id
        return runs

    async def _run_forever(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                logger.exception("ingestion scheduler tick failed: %s", exc)
            self.next_tick_at = (
                datetime.now(timezone.utc).timestamp() + self.interval_seconds
            )
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise

    def status(self) -> IngestionSchedulerStatus:
        return IngestionSchedulerStatus(
            running=self._running,
            active_tasks=1 if self._task is not None and not self._task.done() else 0,
            interval_seconds=self.interval_seconds,
            last_tick_at=self.last_tick_at,
            next_tick_at=(
                datetime.fromtimestamp(self.next_tick_at, tz=timezone.utc)
                if self.next_tick_at
                else None
            ),
            last_run_id=self.last_run_id,
        )


# ─── Top-level service ─────────────────────────────────────────────────


class AutoIngestionService:
    """DI-friendly top-level facade.

    Holds references to the monitoring service (for ingesting pending
    discoveries) and the ingestion pipeline + repository.
    """

    def __init__(
        self,
        *,
        coordinator: DocumentPipelineCoordinator,
        repository: IngestionRepository,
        audit_service: IngestionAuditService,
        synchronizer: RegistrySynchronizer,
        registry: DocumentRegistryProtocol,
        monitoring_service: Optional[Any] = None,
        scheduler: Optional[IngestionScheduler] = None,
    ) -> None:
        self.coordinator = coordinator
        self.repository = repository
        self.audit_service = audit_service
        self.synchronizer = synchronizer
        self.registry = registry
        self.monitoring_service = monitoring_service
        self.scheduler = scheduler or IngestionScheduler(self)

    # ── Public API ────────────────────────────────────────────────────

    async def ingest(
        self, request: IngestionTriggerRequest
    ) -> IngestionRunResponse:
        run = IngestionRun(
            document_url=request.url,
            source=request.source,
        )
        self.repository.add_run(run)
        self.audit_service.record(
            run.run_id, "ingestion_started", metadata={"url": request.url}
        )
        metrics = get_ingestion_metrics()
        run = await self.coordinator.run(request, run)
        self.repository.add_run(run)
        metrics.record_run(
            run.source or "unknown",
            success=(run.status == IngestionStatus.COMPLETED),
            chunks=run.chunks_created,
            embeddings=run.embeddings_created,
            latency_ms=run.duration_ms,
        )
        for step in run.steps:
            metrics.record_step_latency(step.step.value, step.duration_ms)
        return IngestionRunResponse.from_run(run)

    async def ingest_discovery(
        self, discovery: DiscoveredDocument, *, force: bool = False
    ) -> IngestionRunResponse:
        return await self.ingest(
            IngestionTriggerRequest(
                discovery_id=discovery.discovery_id,
                url=discovery.document_url,
                source=discovery.source.value,
                title=discovery.title,
                force=force,
            )
        )

    async def ingest_pending_discoveries(
        self, *, force: bool = False
    ) -> List[IngestionRun]:
        """Ingest every discovery from the monitoring service."""
        if self.monitoring_service is None:
            return []
        flt = DiscoveryFilter_All()
        result = self.monitoring_service.search(flt)
        runs: List[IngestionRun] = []
        for d in result.items:
            r = await self.ingest_discovery(d, force=force)
            # Hydrate the run from the response.
            run = self.repository.get_run(r.run_id)
            if run is not None:
                runs.append(run)
        return runs

    # ── Read / query ──────────────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[IngestionRun]:
        return self.repository.get_run(run_id)

    def list_runs(self, flt: IngestionFilter) -> PaginatedIngestionRuns:
        return self.repository.list_runs(flt)

    def list_audits(
        self, run_id: Optional[str] = None, limit: int = 100
    ) -> List[IngestionAuditEntry]:
        return self.repository.list_audits(run_id=run_id, limit=limit)

    def stats(self) -> IngestionStats:
        return self.repository.stats()

    # ── Sync ──────────────────────────────────────────────────────────

    async def sync_registry(
        self, discoveries: List[DiscoveredDocument]
    ) -> RegistrySyncResult:
        return await self.synchronizer.sync(discoveries)

    # ── Scheduler ─────────────────────────────────────────────────────

    async def start_scheduler(self) -> None:
        await self.scheduler.start()

    async def stop_scheduler(self) -> None:
        await self.scheduler.stop()

    def scheduler_status(self) -> IngestionSchedulerStatus:
        return self.scheduler.status()

    async def scheduler_tick(self) -> List[IngestionRun]:
        return await self.scheduler.tick()


class DiscoveryFilter_All:
    """Sentinel passed to monitoring service.search() for "everything"."""

    source = None
    change_type = None
    document_url = None
    after = None
    before = None
    page = 1
    page_size = 200  # cap to avoid runaway

    def model_dump(self, mode: Optional[str] = None) -> Dict[str, Any]:
        return {
            "source": None,
            "change_type": None,
            "document_url": None,
            "after": None,
            "before": None,
            "page": self.page,
            "page_size": self.page_size,
        }


# ─── Production factory ────────────────────────────────────────────────


class _RealDownloader:
    """Real HTTP/HTTPS downloader with size limits and timeout."""

    def __init__(self, timeout_seconds: int = 30, max_bytes: int = 50 * 1024 * 1024) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    async def download(self, url: str) -> bytes:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content = bytearray()
                async for chunk in resp.content.iter_chunked(8192):
                    content.extend(chunk)
                    if len(content) > self._max_bytes:
                        raise ValueError(f"Download exceeds {self._max_bytes} byte limit")
                return bytes(content)


class _ParserAdapter:
    """Adapts ParserService to the ParserProtocol."""

    def __init__(self, parser_service: Any) -> None:
        self._service = parser_service

    async def parse(self, document_id: Any) -> List[Dict[str, Any]]:
        return await self._service.parse_document(document_id)


class _ChunkerAdapter:
    """Adapts HierarchicalChunkerService to the ChunkerProtocol."""

    def __init__(self, chunker_service: Any) -> None:
        self._service = chunker_service

    async def chunk(self, document_id: Any) -> List[Dict[str, Any]]:
        logger.info("ChunkerAdapter.chunk called for document_id=%s", document_id)
        try:
            result = await self._service.chunk_document_by_id(document_id)
            logger.info("ChunkerAdapter.chunk returned %d chunks", len(result))
            return result
        except Exception as e:
            logger.exception("ChunkerAdapter.chunk failed for document_id=%s: %s", document_id, e)
            raise


class _EmbedderAdapter:
    """Adapts EmbeddingPipeline to the EmbedderProtocol."""

    def __init__(self, embedding_pipeline: Any) -> None:
        self._pipeline = embedding_pipeline

    async def embed(self, document_id: Any) -> Dict[str, Any]:
        return await self._pipeline.process_document_embeddings(document_id)


class _IndexerAdapter:
    """Adapts VectorIndexManager to the IndexerProtocol."""

    def __init__(self, index_manager: Any) -> None:
        self._manager = index_manager

    async def ensure_index(self, model_name: str) -> str:
        return await self._manager.create_index(model_name)


class _RegistryAdapter:
    """Adapts DocumentService to the DocumentRegistryProtocol."""

    def __init__(self, document_service: Any) -> None:
        self._service = document_service

    async def register(self, payload: Dict[str, Any]) -> Any:
        from app.schemas.document import DocumentCreate
        doc_create = DocumentCreate(
            title=payload.get("title", "(untitled)"),
            source=payload.get("source", "UNKNOWN"),
            file_name=payload.get("file_name", "document.pdf"),
            checksum=payload.get("checksum"),
            file_path=payload.get("file_path", ""),
            metadata=payload.get("metadata", {}),
        )
        doc = await self._service.register_document(doc_create)
        return {"document_id": str(doc.id)}

    async def get_by_checksum(self, checksum: str) -> Optional[Any]:
        return await self._service.repository.get_document_by_checksum(checksum)

    async def get_by_id(self, document_id: Any) -> Optional[Any]:
        try:
            return await self._service.get_document_by_id(document_id)
        except Exception:
            return None


def build_default_auto_ingestion_service(
    monitoring_service: Optional[Any] = None,
    db_session: Optional[Any] = None,
    downloader: Optional[Any] = None,
    embedding_provider: Optional[Any] = None,
) -> AutoIngestionService:
    """Build a production-ready :class:`AutoIngestionService` with real
    service collaborators.

    Args:
        monitoring_service: Optional monitoring service for discovery ingestion.
        db_session: Optional AsyncSession for database operations. If not provided,
                   the function will create one using the app's
                   database configuration.
        downloader: Optional downloader instance. If not provided, uses _RealDownloader.
        embedding_provider: Optional embedding provider. If not provided, uses the
                           default BGEEmbeddingProvider.

    The following real services are wired:
    * ``downloader`` → _RealDownloader (HTTP/HTTPS with timeout and size limits) or injected
    * ``parser``     → app.services.parser_service.ParserService
    * ``chunker``    → app.services.structure.chunker.HierarchicalChunkerService
    * ``embedder``   → app.services.embedding.pipeline.EmbeddingPipeline
    * ``indexer``    → app.services.embedding.index_manager.VectorIndexManager
    * ``registry``   → app.services.document.DocumentService
    """
    from app.services.parser_service import ParserService
    from app.services.structure.chunker import HierarchicalChunkerService, HierarchicalChunker
    from app.services.embedding.pipeline import EmbeddingPipeline
    from app.services.embedding.index_manager import VectorIndexManager
    from app.services.document import DocumentService
    from app.services.chunk_registry import ChunkRegistryService
    from app.core.token_utils import SimpleTokenizer
    from app.services.page import PageService
    from app.services.structure.enricher import MetadataEnricher, MetadataValidator

    if db_session is None:
        from app.core.database import async_session_factory
        db_session = async_session_factory()

    if downloader is None:
        downloader = _RealDownloader()

    if embedding_provider is None:
        from app.services.embedding import embedding_provider as _default_embedder
        embedding_provider = _default_embedder

    store = InMemoryIngestionStore(
        persist_path=Path(settings.STORAGE_ROOT) / "ingestion" / "ingestion.jsonl"
    )
    repository = IngestionRepository(store)
    audit_service = IngestionAuditService(repository)

    # Real service instances
    document_service = DocumentService(db_session)
    page_service = PageService(db_session, document_service)
    parser_service = ParserService(document_service, settings.STORAGE_ROOT, page_service=page_service)
    chunker = HierarchicalChunker(tokenizer=SimpleTokenizer())
    enricher = MetadataEnricher(MetadataValidator())
    chunker_service = HierarchicalChunkerService(
        document_service=document_service,
        page_service=page_service,
        chunker=chunker,
        enricher=enricher,
    )
    embedding_provider = embedding_provider
    chunk_registry = ChunkRegistryService(db_session, document_service)
    embedding_pipeline = EmbeddingPipeline(
        db_session=db_session,
        chunk_service=chunk_registry,
        embedding_provider=embedding_provider,
    )
    index_manager = VectorIndexManager(db_session)

    # Adapters for protocol compliance
    registry = _RegistryAdapter(document_service)
    duplicate_detector = DuplicateDetector(registry)
    coordinator = DocumentPipelineCoordinator(
        downloader=downloader,
        parser=_ParserAdapter(parser_service),
        chunker=_ChunkerAdapter(chunker_service),
        embedder=_EmbedderAdapter(embedding_pipeline),
        indexer=_IndexerAdapter(index_manager),
        registry=registry,
        duplicate_detector=duplicate_detector,
        recovery=FailureRecovery(),
        audit_service=audit_service,
        chunk_persister=chunk_registry,
    )
    synchronizer = RegistrySynchronizer(registry, duplicate_detector)
    return AutoIngestionService(
        coordinator=coordinator,
        repository=repository,
        audit_service=audit_service,
        synchronizer=synchronizer,
        registry=registry,
        monitoring_service=monitoring_service,
    )


__all__ = [
    "AutoIngestionService",
    "DocumentPipelineCoordinator",
    "DuplicateDetector",
    "FailureRecovery",
    "InMemoryIngestionStore",
    "IngestionAuditService",
    "IngestionRepository",
    "IngestionScheduler",
    "IngestionStore",
    "RegistrySynchronizer",
    "build_default_auto_ingestion_service",
]
