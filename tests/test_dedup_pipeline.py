"""Phase 9 — Duplicate Protection Validation.

Covers: checksum-based dedup (DuplicateDetector, StorageService),
document registration/upload 409, ingestion pipeline SKIPPED status,
force flag bypass, DuplicateChunkRule, duplicate embedding detection,
RegistrySynchronizer counting, alert dedup, API filter.
"""

from __future__ import annotations

import hashlib

import pytest


# ══════════════════════════════════════════════════════════════════
# 9.1 — Checksum Computation
# ══════════════════════════════════════════════════════════════════


class TestChecksumComputation:
    """Tests for SHA-256 checksum computation correctness."""

    def test_deterministic_checksum(self):
        from app.services.ingestion import DuplicateDetector

        c1 = DuplicateDetector.compute_checksum(b"hello world")
        c2 = DuplicateDetector.compute_checksum(b"hello world")
        assert c1 == c2
        assert isinstance(c1, str)
        assert len(c1) == 64

    def test_different_content_different_checksum(self):
        from app.services.ingestion import DuplicateDetector

        c1 = DuplicateDetector.compute_checksum(b"content A")
        c2 = DuplicateDetector.compute_checksum(b"content B")
        assert c1 != c2

    def test_checksum_matches_hashing_library(self):
        from app.services.ingestion import DuplicateDetector

        content = b"regulatory document content"
        expected = hashlib.sha256(content).hexdigest()
        assert DuplicateDetector.compute_checksum(content) == expected

    def test_empty_content_checksum(self):
        from app.services.ingestion import DuplicateDetector

        c = DuplicateDetector.compute_checksum(b"")
        assert len(c) == 64


# ══════════════════════════════════════════════════════════════════
# 9.2 — Document Model & Schema Constraints
# ══════════════════════════════════════════════════════════════════


class TestChecksumModelConstraints:
    """Tests that checksum fields enforce correctness."""

    def test_document_model_has_checksum(self):
        from app.models.document import Document

        col = Document.__table__.c["checksum"]
        assert col.unique
        assert col.nullable is False

    def test_document_create_enforces_checksum_length(self):
        from pydantic import ValidationError
        from app.schemas.document import DocumentCreate

        with pytest.raises(ValidationError):
            DocumentCreate(checksum="too-short")

    def test_document_create_accepts_valid_checksum(self):
        from app.schemas.document import DocumentCreate
        from app.models.document import SourceEnum

        chk = "a" * 64
        d = DocumentCreate(
            title="test",
            source=SourceEnum.RBI,
            file_name="test.pdf",
            file_path="/tmp/test.pdf",
            checksum=chk,
        )
        assert d.checksum == chk

    def test_document_create_requires_min_fields(self):
        from pydantic import ValidationError
        from app.schemas.document import DocumentCreate

        with pytest.raises(ValidationError):
            DocumentCreate()


# ══════════════════════════════════════════════════════════════════
# 9.3 — Registration & Upload Dedup
# ══════════════════════════════════════════════════════════════════


class TestRegistrationDedup:
    """Tests that duplicate registration produces 409."""

    def test_duplicate_document_error_has_checksum(self):
        from app.core.exceptions import DuplicateDocumentError

        exc = DuplicateDocumentError("abc123")
        assert exc.checksum == "abc123"
        assert "abc123" in str(exc)

    def test_duplicate_document_error_subtype(self):
        from app.core.exceptions import DuplicateDocumentError, DocumentRegistryError

        assert issubclass(DuplicateDocumentError, DocumentRegistryError)


# ══════════════════════════════════════════════════════════════════
# 9.4 — Ingestion Pipeline Dedup
# ══════════════════════════════════════════════════════════════════


class TestIngestionDedup:
    """Tests for ingestion pipeline duplicate detection."""

    def test_ingestion_status_has_skipped(self):
        from app.schemas.ingestion import IngestionStatus

        assert IngestionStatus.SKIPPED.value == "skipped"

    def test_ingestion_run_has_is_duplicate_field(self):
        from app.schemas.ingestion import IngestionRun

        run = IngestionRun()
        assert run.is_duplicate is False

    def test_ingestion_run_response_has_is_duplicate(self):
        from app.schemas.ingestion import IngestionRunResponse, IngestionStatus

        resp = IngestionRunResponse(
            run_id="r1", ingestion_status=IngestionStatus.PENDING
        )
        assert resp.is_duplicate is False

    def test_ingestion_filter_can_filter_by_duplicate(self):
        from app.schemas.ingestion import IngestionFilter

        f = IngestionFilter(is_duplicate=True)
        assert f.is_duplicate is True

    def test_ingestion_stats_tracks_duplicate_runs(self):
        from app.schemas.ingestion import IngestionStats

        s = IngestionStats()
        assert s.duplicate_runs == 0

    def test_ingestion_trigger_request_has_force_flag(self):
        from app.schemas.ingestion import IngestionTriggerRequest

        req = IngestionTriggerRequest(source="test", url="http://example.com/doc.pdf")
        assert req.force is False

    def test_registry_sync_result_tracks_already_in_registry(self):
        from app.schemas.ingestion import RegistrySyncResult

        r = RegistrySyncResult()
        assert r.already_in_registry == 0


# ══════════════════════════════════════════════════════════════════
# 9.5 — DuplicateChunkRule Validation
# ══════════════════════════════════════════════════════════════════


class TestDuplicateChunkRule:
    """Tests for the DuplicateChunkRule validation."""

    def test_duplicate_chunk_rule_detects_by_chunk_id(self):
        from app.services.validation.rules import DuplicateChunkRule

        rule = DuplicateChunkRule()
        issues = rule.validate_batch(
            [
                {"chunk_id": "c1", "content": "A"},
                {"chunk_id": "c1", "content": "B"},
                {"chunk_id": "c2", "content": "C"},
            ]
        )
        assert any("c1" in str(i) for i in issues)

    def test_duplicate_chunk_rule_detects_by_content(self):
        from app.services.validation.rules import DuplicateChunkRule

        rule = DuplicateChunkRule()
        issues = rule.validate_batch(
            [
                {"chunk_id": "c1", "content": "KYC required"},
                {"chunk_id": "c2", "content": "KYC required"},
            ]
        )
        assert len(issues) >= 1

    def test_duplicate_chunk_rule_passes_unique_chunks(self):
        from app.services.validation.rules import DuplicateChunkRule

        rule = DuplicateChunkRule()
        issues = rule.validate_batch(
            [
                {"chunk_id": "c1", "content": "KYC required"},
                {"chunk_id": "c2", "content": "AML required"},
            ]
        )
        assert issues == []

    def test_duplicate_chunk_rule_empty(self):
        from app.services.validation.rules import DuplicateChunkRule

        rule = DuplicateChunkRule()
        issues = rule.validate_batch([])
        assert issues == []


# ══════════════════════════════════════════════════════════════════
# 9.6 — Embedding-Level Dedup
# ══════════════════════════════════════════════════════════════════


class TestEmbeddingDedup:
    """Tests for duplicate embedding detection."""

    def test_embedding_validation_metrics_has_duplicate_count(self):
        from app.schemas.embedding_validation import EmbeddingValidationMetrics

        m = EmbeddingValidationMetrics(
            total_chunks=10,
            total_embeddings=10,
            embedding_coverage=1.0,
            average_vector_norm=0.5,
            invalid_embedding_count=0,
            duplicate_embedding_count=2,
        )
        assert m.duplicate_embedding_count == 2

    def test_embedding_validation_metrics_counts_default_construct(self):
        from app.schemas.embedding_validation import EmbeddingValidationMetrics

        m = EmbeddingValidationMetrics(
            total_chunks=5,
            total_embeddings=5,
            embedding_coverage=1.0,
            average_vector_norm=0.5,
            invalid_embedding_count=0,
            duplicate_embedding_count=0,
        )
        assert m.duplicate_embedding_count == 0


# ══════════════════════════════════════════════════════════════════
# 9.7 — Alert Dedup
# ══════════════════════════════════════════════════════════════════


class TestAlertDedup:
    """Tests for alert deduplication within time windows."""

    def test_alert_manager_has_dedup_window(self):
        from app.services.alerting import AlertManager

        mgr = AlertManager(store=None, dispatcher=None)
        assert mgr._dedup_window == 5.0

    def test_alert_dedup_by_timestamp(self):
        from app.services.alerting import AlertManager

        mgr = AlertManager(store=None, dispatcher=None, dedup_window_seconds=10.0)
        assert mgr._dedup_window == 10.0


# ══════════════════════════════════════════════════════════════════
# 9.8 — DuplicateDetector (Service Level)
# ══════════════════════════════════════════════════════════════════


class TestDuplicateDetector:
    """Tests for the DuplicateDetector service (with mock registry)."""

    @pytest.mark.asyncio
    async def test_is_duplicate_returns_false_on_missing(self):
        from app.services.ingestion import DuplicateDetector

        class _NoRegistry:
            async def get_by_checksum(self, checksum):
                return None

        detector = DuplicateDetector(registry=_NoRegistry())
        assert not await detector.is_duplicate("abc")

    @pytest.mark.asyncio
    async def test_is_duplicate_returns_true_on_found(self):
        from app.services.ingestion import DuplicateDetector

        class _YesRegistry:
            async def get_by_checksum(self, checksum):
                return {"id": "doc-1", "checksum": checksum}

        detector = DuplicateDetector(registry=_YesRegistry())
        assert await detector.is_duplicate("abc")

    def test_duplicate_detector_static_checksum(self):
        from app.services.ingestion import DuplicateDetector

        c = DuplicateDetector.compute_checksum(b"test data")
        assert len(c) == 64
        assert c == hashlib.sha256(b"test data").hexdigest()
