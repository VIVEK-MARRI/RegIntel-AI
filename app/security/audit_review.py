"""Audit review (M10.6).

Adds a higher-level review layer on top of the existing in-memory
:class:`app.middleware.AuditLog`. Provides:

* Filtering by time window, path, method, status, identity
* Pagination
* Mark-for-review / approve / reject flags
* Export to JSONL / CSV
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.middleware import AuditLog, AuditLogEntry

logger = logging.getLogger(__name__)


# ─── Review model ────────────────────────────────────────────────────


REVIEW_STATUSES = ("pending", "approved", "rejected")


@dataclass
class AuditRecord:
    """The audit record surfaced by the review API."""

    timestamp: str
    request_id: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    api_key_id: Optional[str]
    client_ip: Optional[str]
    user_agent: Optional[str]
    error: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    review_status: str = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditQuery:
    """Filter / paginate audit records."""

    start: Optional[datetime] = None
    end: Optional[datetime] = None
    method: Optional[str] = None
    path_prefix: Optional[str] = None
    status_code: Optional[int] = None
    status_min: Optional[int] = None
    status_max: Optional[int] = None
    api_key_id: Optional[str] = None
    client_ip: Optional[str] = None
    review_status: Optional[str] = None
    limit: int = 100
    offset: int = 0

    def matches(self, record: AuditRecord) -> bool:
        if self.method and record.method.upper() != self.method.upper():
            return False
        if self.path_prefix and not record.path.startswith(self.path_prefix):
            return False
        if self.status_code is not None and record.status_code != self.status_code:
            return False
        if self.status_min is not None and record.status_code < self.status_min:
            return False
        if self.status_max is not None and record.status_code > self.status_max:
            return False
        if self.api_key_id and record.api_key_id != self.api_key_id:
            return False
        if self.client_ip and record.client_ip != self.client_ip:
            return False
        if self.review_status and record.review_status != self.review_status:
            return False
        if self.start:
            if record.timestamp < self.start.isoformat():
                return False
        if self.end:
            if record.timestamp > self.end.isoformat():
                return False
        return True


# ─── Review service ──────────────────────────────────────────────────


class AuditReview:
    """Query, review, and export audit records."""

    def __init__(self, audit_log: AuditLog) -> None:
        self._audit_log = audit_log
        self._lock = threading.RLock()
        # Review flags are stored separately, keyed by request_id.
        self._reviews: Dict[str, Dict[str, Any]] = {}

    # ─── Records ──────────────────────────────────────────────────

    def records(self, query: Optional[AuditQuery] = None) -> List[AuditRecord]:
        q = query or AuditQuery()
        out: List[AuditRecord] = []
        for entry in self._audit_log.all():
            record = self._record_from_entry(entry)
            if q.matches(record):
                out.append(record)
        out.sort(key=lambda r: r.timestamp, reverse=True)
        # Pagination
        return out[q.offset : q.offset + q.limit]

    def count(self, query: Optional[AuditQuery] = None) -> int:
        return len(
            self.records(
                AuditQuery(limit=10_000_000, offset=0)
                if query is None
                else AuditQuery(**{**asdict(query), "limit": 10_000_000, "offset": 0})
            )
        )

    def find(self, request_id: str) -> Optional[AuditRecord]:
        for entry in self._audit_log.all():
            if entry.request_id == request_id:
                return self._record_from_entry(entry)
        return None

    # ─── Review actions ──────────────────────────────────────────

    def mark(
        self,
        request_id: str,
        *,
        status: str,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> AuditRecord:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of {REVIEW_STATUSES}")
        record = self.find(request_id)
        if record is None:
            raise KeyError(f"audit record {request_id!r} not found")
        with self._lock:
            self._reviews[request_id] = {
                "status": status,
                "reviewer": reviewer,
                "notes": notes,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        # Re-fetch so the returned record reflects the new state.
        refreshed = self.find(request_id)
        assert refreshed is not None
        return refreshed

    def review_summary(self) -> Dict[str, int]:
        with self._lock:
            counts = {s: 0 for s in REVIEW_STATUSES}
            for entry in self._audit_log.all():
                review = self._reviews.get(entry.request_id)
                status = review["status"] if review else "pending"
                counts[status] = counts.get(status, 0) + 1
            return counts

    # ─── Export ──────────────────────────────────────────────────

    def export_jsonl(self, query: Optional[AuditQuery] = None) -> str:
        records = self.records(query)
        # JSONL: one JSON object per line, terminated by a newline. The trailing
        # newline keeps line-count and ``wc -l`` honest for streaming readers.
        if not records:
            return ""
        return "".join(json.dumps(r.to_dict()) + "\n" for r in records)

    def export_csv(self, query: Optional[AuditQuery] = None) -> str:
        records = self.records(query)
        buf = io.StringIO()
        if not records:
            return ""
        writer = csv.DictWriter(buf, fieldnames=list(records[0].to_dict().keys()))
        writer.writeheader()
        for r in records:
            writer.writerow(r.to_dict())
        return buf.getvalue()

    def write_export(
        self,
        path: Path,
        query: Optional[AuditQuery] = None,
        *,
        format: str = "jsonl",
    ) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if format == "jsonl":
            text = self.export_jsonl(query)
        elif format == "csv":
            text = self.export_csv(query)
        else:
            raise ValueError(f"unsupported export format: {format}")
        path.write_text(text, encoding="utf-8")
        return len(text)

    # ─── Internals ───────────────────────────────────────────────

    def _record_from_entry(self, entry: AuditLogEntry) -> AuditRecord:
        review = self._reviews.get(entry.request_id, {})
        return AuditRecord(
            timestamp=entry.timestamp.isoformat(),
            request_id=entry.request_id,
            method=entry.method,
            path=entry.path,
            status_code=entry.status_code,
            duration_ms=entry.duration_ms,
            api_key_id=entry.api_key_id,
            client_ip=entry.client_ip,
            user_agent=entry.user_agent,
            error=entry.error,
            metadata=entry.metadata,
            review_status=review.get("status", "pending"),
            reviewed_by=review.get("reviewer"),
            reviewed_at=review.get("at"),
            review_notes=review.get("notes"),
        )


# ─── Singleton wiring ───────────────────────────────────────────────

_audit_review_singleton: Optional[AuditReview] = None
_audit_review_lock = threading.Lock()


def get_audit_review() -> AuditReview:
    global _audit_review_singleton
    with _audit_review_lock:
        if _audit_review_singleton is None:
            # Late import avoids a hard cycle at app boot.
            from app.main import _audit_log  # type: ignore[attr-defined]

            _audit_review_singleton = AuditReview(_audit_log)
        return _audit_review_singleton


def set_audit_review(review: AuditReview) -> None:
    """Test helper: install a specific review instance."""
    global _audit_review_singleton
    _audit_review_singleton = review


def reset_audit_review() -> None:
    """Test helper."""
    global _audit_review_singleton
    _audit_review_singleton = None
