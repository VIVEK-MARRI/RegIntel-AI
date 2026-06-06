"""Module 8.7 — Audit & Compliance Platform.

Public surface
--------------
* ``AuditEngine``          — append-only hash-chained audit log
* ``AuditRepository``      — search / stats / integrity
* ``AuditTrailManager``    — end-to-end decision lineage
* ``ComplianceReporter``   — generate regulatory / internal reports
* ``AuditStore`` (ABC) + ``InMemoryAuditStore``
* ``AuditService``         — DI facade
* ``build_default_audit_service``
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.audit import (
    AuditAction,
    AuditEvidence,
    AuditEvidenceCreateRequest,
    AuditFilter,
    AuditRecord,
    AuditRecordCreateRequest,
    AuditSeverity,
    AuditStats,
    ComplianceReport,
    ComplianceReportCreateRequest,
    DecisionLineage,
    EvidenceKind,
    LineageEdge,
    LineageNode,
    PaginatedAuditRecords,
    ReportKind,
    ReportSection,
    ReportStatus,
)
from app.services.observability import (
    get_audit_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Hashing helpers ─────────────────────────────────────────────


_GENESIS_HASH = "0" * 64


def _canonical_json(record: AuditRecord) -> str:
    """Stable JSON for hashing.

    The hash is computed from a canonicalised dict so that any change to
    the record (timestamp, actor, action, details, etc.) changes the
    resulting hash.
    """
    payload = {
        "audit_id": record.audit_id,
        "timestamp": record.timestamp,
        "actor": record.actor,
        "actor_role": record.actor_role,
        "action": record.action.value,
        "severity": record.severity.value,
        "subject_type": record.subject_type,
        "subject_id": record.subject_id,
        "description": record.description,
        "details": record.details,
        "ip_address": record.ip_address,
        "user_agent": record.user_agent,
        "source_module": record.source_module,
        "prev_hash": record.prev_hash,
        "sequence": record.sequence,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(record: AuditRecord) -> str:
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


# ─── AuditEngine ────────────────────────────────────────────────


class AuditEngine:
    """Append-only log with SHA-256 hash chain."""

    def append(
        self,
        request: AuditRecordCreateRequest,
        *,
        store: "InMemoryAuditStore",
    ) -> AuditRecord:
        with track_request(
            endpoint="/api/v1/audit/append",
            strategy="audit_append",
        ):
            with store._lock:  # type: ignore[attr-defined]
                prev_hash = store._last_hash  # type: ignore[attr-defined]
                sequence = store._sequence + 1  # type: ignore[attr-defined]
                record = AuditRecord(
                    actor=request.actor,
                    actor_role=request.actor_role,
                    action=request.action,
                    severity=request.severity,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    description=request.description,
                    details=request.details,
                    ip_address=request.ip_address,
                    user_agent=request.user_agent,
                    source_module=request.source_module,
                    prev_hash=prev_hash,
                    sequence=sequence,
                    metadata=request.metadata,
                )
                record.record_hash = _compute_hash(record)
                store._records[record.audit_id] = record  # type: ignore[attr-defined]
                store._last_hash = record.record_hash  # type: ignore[attr-defined]
                store._sequence = sequence  # type: ignore[attr-defined]
                store._persist()  # type: ignore[attr-defined]
            get_audit_metrics().record_record(
                action=request.action, severity=request.severity
            )
            return record

    def verify_chain(self, store: "InMemoryAuditStore") -> Tuple[bool, str]:
        """Verify the integrity of the hash chain from genesis to head."""
        records = sorted(
            store._records.values(), key=lambda r: r.sequence  # type: ignore[attr-defined]
        )
        prev = _GENESIS_HASH
        for r in records:
            if r.prev_hash != prev:
                return False, f"break at sequence={r.sequence} audit_id={r.audit_id}"
            actual = _compute_hash(r)
            if actual != r.record_hash:
                return False, f"tamper detected at audit_id={r.audit_id}"
            prev = r.record_hash
        return True, ""


# ─── AuditRepository ────────────────────────────────────────────


class AuditRepository:
    """Search / stats over the audit log."""

    def __init__(self, store: "InMemoryAuditStore") -> None:
        self._store = store

    def search(self, flt: AuditFilter) -> PaginatedAuditRecords:
        items = self._store.list_records(flt)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedAuditRecords(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> AuditStats:
        records = self._store.list_records_unfiltered()
        by_action: Dict[str, int] = {}
        by_sev: Dict[str, int] = {}
        by_actor: Dict[str, int] = {}
        by_module: Dict[str, int] = {}
        by_subject: Dict[str, int] = {}
        for r in records:
            by_action[r.action.value] = by_action.get(r.action.value, 0) + 1
            by_sev[r.severity.value] = by_sev.get(r.severity.value, 0) + 1
            by_actor[r.actor] = by_actor.get(r.actor, 0) + 1
            if r.source_module:
                by_module[r.source_module] = by_module.get(r.source_module, 0) + 1
            if r.subject_type:
                by_subject[r.subject_type] = by_subject.get(r.subject_type, 0) + 1
        chain_intact, _ = AuditEngine().verify_chain(self._store)
        return AuditStats(
            total_records=len(records),
            by_action=by_action,
            by_severity=by_sev,
            by_actor=by_actor,
            by_module=by_module,
            by_subject_type=by_subject,
            chain_length=self._store._sequence,
            last_chain_hash=self._store._last_hash,
            chain_integrity=chain_intact,
            last_record_at=max(
                (r.timestamp for r in records), default=None
            ),
            oldest_record_at=min(
                (r.timestamp for r in records), default=None
            ),
        )


# ─── AuditTrailManager ──────────────────────────────────────────


class AuditTrailManager:
    """End-to-end decision lineage.

    The trail is a DAG. Given a root decision id we walk backwards and
    forwards through :class:`AuditRecord` entries that share subject
    ids, producing a structured lineage suitable for explainability
    and regulatory reports.
    """

    def __init__(self, store: "InMemoryAuditStore") -> None:
        self._store = store

    def build_lineage(
        self,
        root_decision_id: str,
        subject_type: str = "decision",
        subject_id: str = "",
    ) -> DecisionLineage:
        with track_request(
            endpoint="/api/v1/audit/lineage",
            strategy="lineage_build",
        ):
            # Find every record whose subject_id == root_decision_id
            all_records = self._store.list_records_unfiltered()
            root_records = [
                r for r in all_records if r.subject_id == root_decision_id
            ]
            if not root_records:
                return DecisionLineage(
                    root_decision_id=root_decision_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                )

            # Build the initial set of nodes from those records
            node_id_for_audit: Dict[str, str] = {}
            nodes: List[LineageNode] = []
            for rec in root_records:
                n = LineageNode(
                    kind="audit_record",
                    label=f"{rec.action.value}:{rec.subject_type}",
                    ref_id=rec.audit_id,
                    timestamp=rec.timestamp,
                    attributes={
                        "actor": rec.actor,
                        "action": rec.action.value,
                        "severity": rec.severity.value,
                        "description": rec.description,
                    },
                )
                node_id_for_audit[rec.audit_id] = n.node_id
                nodes.append(n)

            # Follow upstream: any records whose subject_id matches
            # the actor or subject_type of a current node.
            seen = {n.ref_id for n in nodes}
            frontier: List[LineageNode] = list(nodes)
            edges: List[LineageEdge] = []
            while frontier:
                next_frontier: List[LineageNode] = []
                for n in frontier:
                    target = n.attributes.get("actor", "")
                    all_recs = self._store.list_records_unfiltered()
                    candidates = [
                        r for r in all_recs if r.subject_id == target
                    ]
                    for c in candidates:
                        if c.audit_id in seen:
                            continue
                        new_node = LineageNode(
                            kind="audit_record",
                            label=f"{c.action.value}:{c.subject_type}",
                            ref_id=c.audit_id,
                            timestamp=c.timestamp,
                            parent_ids=[n.node_id],
                            attributes={
                                "actor": c.actor,
                                "action": c.action.value,
                                "severity": c.severity.value,
                            },
                        )
                        seen.add(c.audit_id)
                        nodes.append(new_node)
                        next_frontier.append(new_node)
                        edges.append(
                            LineageEdge(
                                from_node=c.audit_id,
                                to_node=n.node_id,
                                relation="derived_from",
                            )
                        )
                frontier = next_frontier

            # Sort by timestamp for stability
            nodes.sort(key=lambda x: x.timestamp)
            depth = max(
                (
                    1
                    + max((len(p) for p in [n.parent_ids] or [[]]), default=0)
                    for n in nodes
                ),
                default=0,
            )

            return DecisionLineage(
                root_decision_id=root_decision_id,
                subject_type=subject_type,
                subject_id=subject_id,
                nodes=nodes,
                edges=edges,
                depth=depth,
                node_count=len(nodes),
                edge_count=len(edges),
            )


# ─── ComplianceReporter ─────────────────────────────────────────


class ComplianceReporter:
    """Generate regulatory / internal compliance reports.

    A report is composed of one or more :class:`ReportSection` objects,
    each of which summarises a slice of audit activity and links the
    evidence that backs it.
    """

    DEFAULT_SECTION_TITLES = [
        "Executive Summary",
        "Audit Volume",
        "Policy Compliance",
        "Decisions and Approvals",
        "Findings and Observations",
        "Recommended Actions",
    ]

    def __init__(self, store: "InMemoryAuditStore") -> None:
        self._store = store

    def generate(
        self, request: ComplianceReportCreateRequest
    ) -> ComplianceReport:
        with track_request(
            endpoint="/api/v1/audit/report/generate",
            strategy="report_generate",
        ):
            # Build the report shell
            report = ComplianceReport(
                title=request.title,
                description=request.description,
                kind=request.kind,
                status=ReportStatus.GENERATING,
                regulator=request.regulator,
                period_start=request.period_start,
                period_end=request.period_end,
                generated_by=request.generated_by,
                metadata=request.metadata,
            )

            # Determine the section titles
            titles = request.section_titles or list(self.DEFAULT_SECTION_TITLES)

            # Pull the audit universe for the period
            all_records = self._store.list_records_unfiltered()
            records = all_records
            if request.period_start:
                records = [r for r in records if r.timestamp >= request.period_start]
            if request.period_end:
                records = [r for r in records if r.timestamp <= request.period_end]
            record_ids = [r.audit_id for r in records]

            # Build each section with concrete metrics
            sections: List[ReportSection] = []
            for idx, title in enumerate(titles):
                section = self._build_section(title, records, idx)
                sections.append(section)
                for ref in section.evidence_refs:
                    if ref not in report.evidence_refs:
                        report.evidence_refs.append(ref)

            report.sections = sections
            report.record_refs = record_ids
            report.status = ReportStatus.COMPLETE
            report.completed_at = time.time()

            self._store.add_report(report)
            get_audit_metrics().record_report(request.kind)
            return report

    @staticmethod
    def _build_section(
        title: str,
        records: List[AuditRecord],
        order: int,
    ) -> ReportSection:
        action_counts: Dict[str, int] = {}
        severity_counts: Dict[str, int] = {}
        for r in records:
            action_counts[r.action.value] = (
                action_counts.get(r.action.value, 0) + 1
            )
            severity_counts[r.severity.value] = (
                severity_counts.get(r.severity.value, 0) + 1
            )

        if title.lower().startswith("executive summary"):
            summary = (
                f"This report covers {len(records)} audit records with "
                f"{len(severity_counts)} distinct severity levels and "
                f"{len(action_counts)} distinct actions."
            )
            metrics = {
                "total_records": len(records),
                "action_counts": action_counts,
                "severity_counts": severity_counts,
            }
            findings = [
                f"Most common action: {max(action_counts, key=action_counts.get, default='n/a')}"
            ]
            recommendations = [
                "Continue to monitor high-severity events."
            ]
        elif "volume" in title.lower():
            summary = f"Total audit volume: {len(records)} records."
            metrics = {"total_records": len(records), "actions": action_counts}
            findings = []
            recommendations = []
        elif "compliance" in title.lower():
            policy_checks = [
                r for r in records if r.action == AuditAction.POLICY_CHECK
            ]
            summary = (
                f"{len(policy_checks)} policy-check events recorded in the period."
            )
            metrics = {"policy_checks": len(policy_checks)}
            findings = []
            recommendations = []
        elif "approval" in title.lower() or "decision" in title.lower():
            approvals = [
                r for r in records
                if r.action in (AuditAction.APPROVE, AuditAction.REJECT)
            ]
            summary = f"{len(approvals)} approval/rejection events recorded."
            metrics = {
                "approvals": sum(
                    1 for r in approvals if r.action == AuditAction.APPROVE
                ),
                "rejections": sum(
                    1 for r in approvals if r.action == AuditAction.REJECT
                ),
            }
            findings = []
            recommendations = []
        elif "find" in title.lower() or "observation" in title.lower():
            critical = [r for r in records if r.severity == AuditSeverity.CRITICAL]
            summary = (
                f"{len(critical)} critical events require investigation."
            )
            metrics = {"critical_events": len(critical)}
            findings = [
                f"audit_id={r.audit_id} subject={r.subject_id}"
                for r in critical[:5]
            ]
            recommendations = []
        else:
            summary = ""
            metrics = {}
            findings = []
            recommendations = []

        return ReportSection(
            title=title,
            summary=summary,
            metrics=metrics,
            evidence_refs=[r.audit_id for r in records[:10]],
            findings=findings,
            recommendations=recommendations,
            order=order,
        )

    def list_reports(self) -> List[ComplianceReport]:
        return self._store.list_reports()

    def get_report(self, report_id: str) -> Optional[ComplianceReport]:
        return self._store.get_report(report_id)


# ─── InMemoryAuditStore ─────────────────────────────────────────


class AuditStore(ABC):
    """Abstract storage for audit data."""

    @abstractmethod
    def add_record(self, record: AuditRecord) -> None: ...
    @abstractmethod
    def get_record(self, audit_id: str) -> Optional[AuditRecord]: ...
    @abstractmethod
    def list_records(self, flt: AuditFilter) -> List[AuditRecord]: ...
    @abstractmethod
    def list_records_unfiltered(self) -> List[AuditRecord]: ...
    @abstractmethod
    def add_evidence(self, evidence: AuditEvidence) -> None: ...
    @abstractmethod
    def get_evidence(self, evidence_id: str) -> Optional[AuditEvidence]: ...
    @abstractmethod
    def list_evidence(self, record_id: str = "") -> List[AuditEvidence]: ...
    @abstractmethod
    def add_report(self, report: ComplianceReport) -> None: ...
    @abstractmethod
    def get_report(self, report_id: str) -> Optional[ComplianceReport]: ...
    @abstractmethod
    def list_reports(self) -> List[ComplianceReport]: ...


class InMemoryAuditStore(AuditStore):
    """Thread-safe in-memory audit store with hash-chain + JSONL persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._records: Dict[str, AuditRecord] = {}
        self._evidence: Dict[str, AuditEvidence] = {}
        self._reports: Dict[str, ComplianceReport] = {}
        self._lock = threading.RLock()
        self._sequence = 0
        self._last_hash = _GENESIS_HASH
        self._persist_path = persist_path
        if persist_path:
            self._load()

    # ─── records ───────────────────────────────────────────

    def add_record(self, record: AuditRecord) -> None:
        with self._lock:
            self._records[record.audit_id] = record
            self._persist()

    def get_record(self, audit_id: str) -> Optional[AuditRecord]:
        with self._lock:
            return self._records.get(audit_id)

    def list_records(self, flt: AuditFilter) -> List[AuditRecord]:
        with self._lock:
            items = list(self._records.values())
        if flt.action is not None:
            items = [r for r in items if r.action == flt.action]
        if flt.severity is not None:
            items = [r for r in items if r.severity == flt.severity]
        if flt.actor is not None:
            items = [r for r in items if r.actor == flt.actor]
        if flt.subject_type is not None:
            items = [r for r in items if r.subject_type == flt.subject_type]
        if flt.subject_id is not None:
            items = [r for r in items if r.subject_id == flt.subject_id]
        if flt.source_module is not None:
            items = [r for r in items if r.source_module == flt.source_module]
        if flt.after is not None:
            items = [r for r in items if r.timestamp >= flt.after]
        if flt.before is not None:
            items = [r for r in items if r.timestamp <= flt.before]
        if flt.text_query:
            q = flt.text_query.lower()
            items = [
                r for r in items
                if q in r.description.lower()
                or q in str(r.details).lower()
                or q in r.subject_id.lower()
            ]
        return sorted(items, key=lambda r: r.sequence)

    def list_records_unfiltered(self) -> List[AuditRecord]:
        with self._lock:
            items = list(self._records.values())
        return sorted(items, key=lambda r: r.sequence)

    # ─── evidence ──────────────────────────────────────────

    def add_evidence(self, evidence: AuditEvidence) -> None:
        with self._lock:
            self._evidence[evidence.evidence_id] = evidence
            self._persist()

    def get_evidence(self, evidence_id: str) -> Optional[AuditEvidence]:
        with self._lock:
            return self._evidence.get(evidence_id)

    def list_evidence(self, record_id: str = "") -> List[AuditEvidence]:
        with self._lock:
            items = list(self._evidence.values())
        if record_id:
            items = [e for e in items if e.record_id == record_id]
        return sorted(items, key=lambda e: e.collected_at)

    # ─── reports ───────────────────────────────────────────

    def add_report(self, report: ComplianceReport) -> None:
        with self._lock:
            self._reports[report.report_id] = report
            self._persist()

    def get_report(self, report_id: str) -> Optional[ComplianceReport]:
        with self._lock:
            return self._reports.get(report_id)

    def list_reports(self) -> List[ComplianceReport]:
        with self._lock:
            return sorted(
                self._reports.values(),
                key=lambda r: r.generated_at,
            )

    # ─── persistence ──────────────────────────────────────

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            payload = {
                "sequence": self._sequence,
                "last_hash": self._last_hash,
                "records": [
                    json.loads(r.model_dump_json())
                    for r in self._records.values()
                ],
                "evidence": [
                    json.loads(e.model_dump_json())
                    for e in self._evidence.values()
                ],
                "reports": [
                    json.loads(p.model_dump_json())
                    for p in self._reports.values()
                ],
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception:  # pragma: no cover
            logger.exception("Failed to persist audit store")

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._sequence = int(payload.get("sequence", 0))
            self._last_hash = payload.get("last_hash", _GENESIS_HASH)
            for raw in payload.get("records", []):
                self._records[raw["audit_id"]] = AuditRecord(**raw)
            for raw in payload.get("evidence", []):
                self._evidence[raw["evidence_id"]] = AuditEvidence(**raw)
            for raw in payload.get("reports", []):
                self._reports[raw["report_id"]] = ComplianceReport(**raw)
        except Exception:  # pragma: no cover
            logger.exception("Failed to load audit store")


# ─── AuditService (DI facade) ──────────────────────────────────


class AuditService:
    """Single point of entry for audit / compliance operations."""

    def __init__(self, store: InMemoryAuditStore) -> None:
        self.store = store
        self.engine = AuditEngine()
        self.repository = AuditRepository(store)
        self.trail_manager = AuditTrailManager(store)
        self.reporter = ComplianceReporter(store)

    # ─── records ───────────────────────────────────────────

    def create_record(
        self, request: AuditRecordCreateRequest
    ) -> AuditRecord:
        return self.engine.append(request, store=self.store)

    def get_record(self, audit_id: str) -> Optional[AuditRecord]:
        return self.store.get_record(audit_id)

    def search_records(self, flt: AuditFilter) -> PaginatedAuditRecords:
        return self.repository.search(flt)

    # ─── evidence ──────────────────────────────────────────

    def add_evidence(
        self, request: AuditEvidenceCreateRequest
    ) -> AuditEvidence:
        content_hash = hashlib.sha256(
            json.dumps(
                request.content, sort_keys=True, default=str
            ).encode("utf-8")
        ).hexdigest()
        evidence = AuditEvidence(
            record_id=request.record_id,
            kind=request.kind,
            title=request.title,
            description=request.description,
            content=request.content,
            content_hash=content_hash,
            collected_by=request.collected_by,
            source_uri=request.source_uri,
            tags=request.tags,
        )
        self.store.add_evidence(evidence)
        get_audit_metrics().record_evidence(request.kind)
        return evidence

    def get_evidence(
        self, evidence_id: str
    ) -> Optional[AuditEvidence]:
        return self.store.get_evidence(evidence_id)

    def list_evidence(self, record_id: str = "") -> List[AuditEvidence]:
        return self.store.list_evidence(record_id=record_id)

    # ─── lineage ───────────────────────────────────────────

    def build_lineage(
        self,
        root_decision_id: str,
        *,
        subject_type: str = "decision",
        subject_id: str = "",
    ) -> DecisionLineage:
        return self.trail_manager.build_lineage(
            root_decision_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )

    # ─── reports ───────────────────────────────────────────

    def generate_report(
        self, request: ComplianceReportCreateRequest
    ) -> ComplianceReport:
        return self.reporter.generate(request)

    def list_reports(self) -> List[ComplianceReport]:
        return self.reporter.list_reports()

    def get_report(
        self, report_id: str
    ) -> Optional[ComplianceReport]:
        return self.reporter.get_report(report_id)

    # ─── integrity / stats ────────────────────────────────

    def verify_chain(self) -> Tuple[bool, str]:
        return self.engine.verify_chain(self.store)

    def stats(self) -> AuditStats:
        return self.repository.stats()

    # ─── cross-module hooks ────────────────────────────────

    def record_governance(
        self, actor: str, decision_id: str, description: str = ""
    ) -> Optional[AuditRecord]:
        return self.create_record(
            AuditRecordCreateRequest(
                actor=actor,
                action=AuditAction.POLICY_CHECK,
                severity=AuditSeverity.INFO,
                subject_type="decision",
                subject_id=decision_id,
                description=description or "policy check",
                source_module="governance",
            )
        )

    def record_admin(
        self,
        actor: str,
        action_name: str,
        subject_type: str = "admin",
        subject_id: str = "",
        severity: AuditSeverity = AuditSeverity.INFO,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditRecord]:
        try:
            act = AuditAction(action_name)
        except ValueError:
            act = AuditAction.OTHER
        return self.create_record(
            AuditRecordCreateRequest(
                actor=actor,
                action=act,
                severity=severity,
                subject_type=subject_type,
                subject_id=subject_id,
                description=f"{action_name} on {subject_type}",
                details=details or {},
                source_module="admin",
            )
        )


# ─── Default factory ────────────────────────────────────────────


def build_default_audit_service() -> AuditService:
    """Build a default :class:`AuditService` with a JSONL-backed store."""
    persist_path = os.path.join(
        settings.STORAGE_ROOT, "audit", "audit.jsonl"
    )
    store = InMemoryAuditStore(persist_path=persist_path)
    return AuditService(store)


__all__ = [
    "AuditEngine",
    "AuditRepository",
    "AuditTrailManager",
    "ComplianceReporter",
    "AuditStore",
    "InMemoryAuditStore",
    "AuditService",
    "build_default_audit_service",
    "verify_chain",
    "_GENESIS_HASH",
    "_compute_hash",
]
