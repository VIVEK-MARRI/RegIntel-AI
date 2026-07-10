"""Phase 11 — Data Integrity Validation.

Covers: AuditEngine SHA-256 hash chain verification, AuditLog
middleware recording, ingestion audit trail, document
checksum integrity, audit stats chain integrity, governance
compliance tracking, and decision lineage.
"""

from __future__ import annotations



# ══════════════════════════════════════════════════════════════════
# 11.1 — AuditEngine Hash Chain
# ══════════════════════════════════════════════════════════════════


class TestAuditEngineHashChain:
    """Tests for the audit engine's SHA-256 hash chain integrity."""

    def test_audit_record_has_hash_fields(self):
        from app.schemas.audit import AuditRecord, AuditAction

        r = AuditRecord(
            audit_id="a1",
            actor="system",
            action=AuditAction.CREATE,
            subject_type="document",
            subject_id="d1",
        )
        assert hasattr(r, "prev_hash")
        assert hasattr(r, "record_hash")

    def test_audit_engine_append_creates_chain(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        r1 = svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        r2 = svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.UPDATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        assert r1.sequence == 1
        assert r2.sequence == 2
        assert r2.prev_hash == r1.record_hash

    def test_audit_engine_verify_valid_chain(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.UPDATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        valid, msg = svc.verify_chain()
        assert valid is True

    def test_audit_engine_verify_detects_tamper(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        r1 = svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.UPDATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        # Tamper with the first record
        store._records[r1.audit_id].record_hash = "tampered"
        valid, msg = svc.verify_chain()
        assert valid is False

    def test_audit_engine_empty_chain(self):
        from app.services.audit import AuditService, InMemoryAuditStore

        store = InMemoryAuditStore()
        svc = AuditService(store)
        valid, msg = svc.verify_chain()
        assert valid is True

    def test_audit_record_has_required_enum_fields(self):
        from app.schemas.audit import AuditRecord, AuditAction

        r = AuditRecord(
            audit_id="a1",
            actor="system",
            action=AuditAction.CREATE,
            subject_type="document",
            subject_id="d1",
        )
        assert r.audit_id == "a1"


# ══════════════════════════════════════════════════════════════════
# 11.2 — Audit Stats & Chain Integrity
# ══════════════════════════════════════════════════════════════════


class TestAuditStats:
    """Tests for audit statistics and chain integrity reporting."""

    def test_audit_stats_has_chain_integrity(self):
        from app.services.audit import AuditService, InMemoryAuditStore

        store = InMemoryAuditStore()
        svc = AuditService(store)
        stats = svc.stats()
        assert stats.chain_integrity is not None

    def test_audit_stats_chain_length(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.UPDATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        stats = svc.stats()
        assert stats.chain_length == 2

    def test_audit_stats_last_hash(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        stats = svc.stats()
        assert len(stats.last_chain_hash) == 64

    def test_audit_stats_tampered_chain(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        r1 = svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        store._records[r1.audit_id].record_hash = "tampered"
        stats = svc.stats()
        assert stats.chain_integrity is False


# ══════════════════════════════════════════════════════════════════
# 11.3 — AuditLog Middleware
# ══════════════════════════════════════════════════════════════════


class TestAuditLog:
    """Tests for the middleware AuditLog."""

    def test_audit_log_records_entry(self):
        from app.middleware import AuditLog, AuditLogEntry
        from datetime import datetime, timezone

        log = AuditLog()
        log.record(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                request_id="req1",
                method="POST",
                path="/api/v1/documents",
                status_code=201,
                duration_ms=50.0,
            )
        )
        assert len(log.all()) == 1

    def test_audit_log_entry_has_duration(self):
        from app.middleware import AuditLog, AuditLogEntry
        from datetime import datetime, timezone

        log = AuditLog()
        log.record(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                request_id="req1",
                method="GET",
                path="/health",
                status_code=200,
                duration_ms=12.3,
            )
        )
        entry = log.all()[0]
        assert entry.duration_ms == 12.3

    def test_audit_log_all_returns_all_entries(self):
        from app.middleware import AuditLog, AuditLogEntry
        from datetime import datetime, timezone

        log = AuditLog()
        log.record(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                request_id="req1",
                method="GET",
                path="/health",
                status_code=200,
                duration_ms=5.0,
            )
        )
        log.record(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                request_id="req2",
                method="POST",
                path="/api/v1/documents",
                status_code=201,
                duration_ms=50.0,
            )
        )
        entries = log.all()
        assert len(entries) == 2

    def test_audit_log_clear(self):
        from app.middleware import AuditLog, AuditLogEntry
        from datetime import datetime, timezone

        log = AuditLog()
        log.record(
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                request_id="req1",
                method="GET",
                path="/health",
                status_code=200,
                duration_ms=5.0,
            )
        )
        log.clear()
        assert len(log.all()) == 0


# ══════════════════════════════════════════════════════════════════
# 11.4 — Ingestion Audit Trail
# ══════════════════════════════════════════════════════════════════


class TestIngestionAuditTrail:
    """Tests for the ingestion pipeline audit trail."""

    def test_ingestion_audit_entry_has_required_fields(self):
        from app.schemas.ingestion import IngestionAuditEntry

        entry = IngestionAuditEntry(
            run_id="r1",
            step="download",
            event="started",
        )
        assert entry.level == "info"

    def test_ingestion_audit_entry_defaults(self):
        from app.schemas.ingestion import IngestionAuditEntry

        entry = IngestionAuditEntry(
            run_id="r1",
            step="chunk",
            event="completed",
            message="100 chunks created",
        )
        assert entry.document_id is None
        assert entry.metadata == {}

    def test_ingestion_audit_entry_timestamps(self):
        from app.schemas.ingestion import IngestionAuditEntry

        entry = IngestionAuditEntry(
            run_id="r1",
            step="embed",
            event="started",
        )
        assert entry.timestamp is not None

    def test_ingestion_audit_entry_severity_levels(self):
        from app.schemas.ingestion import IngestionAuditEntry

        entry = IngestionAuditEntry(
            run_id="r1",
            step="index",
            event="failed",
            level="error",
        )
        assert entry.level == "error"


# ══════════════════════════════════════════════════════════════════
# 11.5 — Document Checksum Integrity
# ══════════════════════════════════════════════════════════════════


class TestDocumentIntegrity:
    """Tests for document-level data integrity."""

    def test_document_has_checksum_column(self):
        from app.models.document import Document

        cols = Document.__table__.c
        checksum_col = cols["checksum"]
        assert checksum_col.unique is True
        assert checksum_col.index is True

    def test_document_checksum_length_64(self):
        from app.schemas.document import DocumentCreate
        from app.models.document import SourceEnum

        d = DocumentCreate(
            title="test",
            source=SourceEnum.RBI,
            file_name="t.pdf",
            file_path="/tmp/t.pdf",
            checksum="a" * 64,
        )
        assert len(d.checksum) == 64

    def test_audit_record_tracks_source_module(self):
        from app.schemas.audit import AuditRecord, AuditAction

        r = AuditRecord(
            audit_id="a1",
            actor="system",
            action=AuditAction.CREATE,
            subject_type="document",
            subject_id="d1",
            source_module="ingestion",
        )
        assert r.source_module == "ingestion"


# ══════════════════════════════════════════════════════════════════
# 11.6 — Governance & Compliance Tracking
# ══════════════════════════════════════════════════════════════════


class TestGovernanceTracking:
    """Tests for governance and compliance decision tracking."""

    def test_governance_metrics_tracks_decisions(self):
        from app.services.observability import GovernanceMetrics

        m = GovernanceMetrics()
        snap = m.snapshot()
        assert "decisions_registered" in snap
        assert "compliant_decisions" in snap

    def test_audit_metrics_tracks_chain_checks(self):
        from app.services.observability import AuditMetrics

        m = AuditMetrics()
        snap = m.snapshot()
        assert "chain_integrity_checks" in snap
        assert "chain_integrity_failures" in snap

    def test_audit_trail_manager_lineage(self):
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        store = InMemoryAuditStore()
        svc = AuditService(store)
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.CREATE,
                subject_type="document",
                subject_id="d1",
            )
        )
        svc.create_record(
            AuditRecordCreateRequest(
                actor="system",
                action=AuditAction.APPROVE,
                subject_type="document",
                subject_id="d1",
            )
        )
        lineage = svc.build_lineage(root_decision_id="d1")
        assert lineage.node_count > 0
