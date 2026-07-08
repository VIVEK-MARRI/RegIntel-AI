"""Tests for Module 8.7 — Audit & Compliance Platform."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.audit import (
    AuditAction,
    AuditEvidenceCreateRequest,
    AuditRecord,
    AuditRecordCreateRequest,
    AuditSeverity,
    ComplianceReportCreateRequest,
    EvidenceKind,
    ReportKind,
    ReportStatus,
)
from app.services.audit import (
    AuditEngine,
    AuditService,
    AuditTrailManager,
    ComplianceReporter,
    InMemoryAuditStore,
    _GENESIS_HASH,
    _compute_hash,
    build_default_audit_service,
)


# ─── Engine / hashing ────────────────────────────────────────


class TestAuditEngine:
    def test_genesis_hash_is_zeros(self) -> None:
        assert _GENESIS_HASH == "0" * 64

    def test_compute_hash_deterministic(self) -> None:
        r = AuditRecord(
            actor="alice",
            action=AuditAction.CREATE,
            subject_type="x",
            subject_id="1",
        )
        h1 = _compute_hash(r)
        h2 = _compute_hash(r)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_hash_changes_with_actor(self) -> None:
        r1 = AuditRecord(actor="alice", action=AuditAction.CREATE)
        r2 = AuditRecord(actor="bob", action=AuditAction.CREATE)
        assert _compute_hash(r1) != _compute_hash(r2)


# ─── Audit service basics ───────────────────────────────────


@pytest.fixture
def store() -> InMemoryAuditStore:
    return InMemoryAuditStore()


@pytest.fixture
def service(store: InMemoryAuditStore) -> AuditService:
    return AuditService(store)


class TestAuditServiceRecords:
    def test_append_assigns_sequence_and_hash(self, service: AuditService) -> None:
        r1 = service.create_record(
            AuditRecordCreateRequest(
                actor="alice",
                action=AuditAction.CREATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        assert r1.sequence == 1
        assert r1.prev_hash == _GENESIS_HASH
        assert r1.record_hash != ""
        r2 = service.create_record(
            AuditRecordCreateRequest(
                actor="bob",
                action=AuditAction.UPDATE,
                subject_type="doc",
                subject_id="d1",
            )
        )
        assert r2.sequence == 2
        assert r2.prev_hash == r1.record_hash
        # hash chain is consistent
        assert _compute_hash(r2) == r2.record_hash

    def test_get_and_search(self, service: AuditService) -> None:
        for i in range(3):
            service.create_record(
                AuditRecordCreateRequest(
                    actor="alice",
                    action=AuditAction.CREATE,
                    subject_id=f"d{i}",
                )
            )
        r = service.get_record
        from app.schemas.audit import AuditFilter

        flt = AuditFilter(actor="alice", page=1, page_size=10)
        out = service.search_records(flt)
        assert out.total == 3
        assert out.items[0].sequence == 1

    def test_filter_by_severity_and_module(self, service: AuditService) -> None:
        from app.schemas.audit import AuditFilter

        service.create_record(
            AuditRecordCreateRequest(
                actor="alice",
                action=AuditAction.WORKFLOW_START,
                severity=AuditSeverity.WARNING,
                source_module="workflow",
            )
        )
        service.create_record(
            AuditRecordCreateRequest(
                actor="alice",
                action=AuditAction.POLICY_CHECK,
                severity=AuditSeverity.INFO,
                source_module="governance",
            )
        )
        out = service.search_records(
            AuditFilter(source_module="governance", page=1, page_size=10)
        )
        assert out.total == 1
        assert out.items[0].action == AuditAction.POLICY_CHECK

    def test_text_query(self, service: AuditService) -> None:
        from app.schemas.audit import AuditFilter

        service.create_record(
            AuditRecordCreateRequest(
                actor="alice",
                action=AuditAction.CREATE,
                subject_id="special-needle",
                description="unique test string",
            )
        )
        out = service.search_records(
            AuditFilter(text_query="needle", page=1, page_size=10)
        )
        assert out.total == 1


class TestChainIntegrity:
    def test_chain_is_intact_initially(self, service: AuditService) -> None:
        service.create_record(
            AuditRecordCreateRequest(actor="x", action=AuditAction.CREATE)
        )
        ok, msg = service.verify_chain()
        assert ok is True
        assert msg == ""

    def test_chain_detects_tampering(
        self, service: AuditService, store: InMemoryAuditStore
    ) -> None:
        service.create_record(
            AuditRecordCreateRequest(actor="x", action=AuditAction.CREATE)
        )
        # Tamper with the actor field directly in the store
        rec = next(iter(store._records.values()))
        rec.actor = "evil-hacker"
        ok, msg = service.verify_chain()
        assert ok is False
        assert "tamper" in msg or "break" in msg


# ─── Evidence ───────────────────────────────────────────────


class TestEvidence:
    def test_attach_evidence(self, service: AuditService) -> None:
        rec = service.create_record(
            AuditRecordCreateRequest(actor="x", action=AuditAction.CREATE)
        )
        ev = service.add_evidence(
            AuditEvidenceCreateRequest(
                record_id=rec.audit_id,
                kind=EvidenceKind.DOCUMENT,
                title="contract.pdf",
                content={"url": "s3://bucket/key"},
            )
        )
        assert ev.content_hash != ""
        # List evidence for the record
        items = service.list_evidence(record_id=rec.audit_id)
        assert len(items) == 1
        # And unfiltered
        all_items = service.list_evidence()
        assert len(all_items) == 1


# ─── Lineage ────────────────────────────────────────────────


class TestLineage:
    def test_lineage_for_isolated_decision(self, service: AuditService) -> None:
        rec = service.create_record(
            AuditRecordCreateRequest(
                actor="alice",
                action=AuditAction.POLICY_CHECK,
                subject_id="dec-1",
            )
        )
        lineage = service.build_lineage("dec-1")
        assert lineage.root_decision_id == "dec-1"
        assert lineage.node_count >= 1
        assert any(n.ref_id == rec.audit_id for n in lineage.nodes)

    def test_lineage_for_missing_decision_is_empty(self, service: AuditService) -> None:
        lineage = service.build_lineage("does-not-exist")
        assert lineage.node_count == 0
        assert lineage.edge_count == 0


# ─── Compliance reports ─────────────────────────────────────


class TestComplianceReports:
    def test_generate_report(self, service: AuditService) -> None:
        # Seed some audit activity
        for i in range(3):
            service.create_record(
                AuditRecordCreateRequest(
                    actor="alice",
                    action=AuditAction.APPROVE if i % 2 == 0 else AuditAction.REJECT,
                    subject_id=f"r{i}",
                )
            )
        report = service.generate_report(
            ComplianceReportCreateRequest(
                title="Q1 Regulatory Submission",
                kind=ReportKind.REGULATORY_SUBMISSION,
                regulator="RBI",
                section_titles=[
                    "Executive Summary",
                    "Audit Volume",
                    "Findings and Observations",
                ],
            )
        )
        assert report.status == ReportStatus.COMPLETE
        assert report.completed_at is not None
        assert report.report_id.startswith("rpt-")
        assert len(report.sections) == 3
        assert any(s.title == "Executive Summary" for s in report.sections)
        # Stored
        assert service.get_report(report.report_id) is not None
        # Listed
        assert any(r.report_id == report.report_id for r in service.list_reports())

    def test_report_default_sections(self, service: AuditService) -> None:
        report = service.generate_report(ComplianceReportCreateRequest(title="Default"))
        assert len(report.sections) >= 5

    def test_report_attestation_default(self, service: AuditService) -> None:
        report = service.generate_report(ComplianceReportCreateRequest(title="A"))
        assert report.attestation == ""


# ─── Stats ──────────────────────────────────────────────────


class TestAuditStats:
    def test_stats_aggregate(self, service: AuditService) -> None:
        service.create_record(
            AuditRecordCreateRequest(actor="alice", action=AuditAction.CREATE)
        )
        service.create_record(
            AuditRecordCreateRequest(
                actor="bob",
                action=AuditAction.APPROVE,
                severity=AuditSeverity.WARNING,
            )
        )
        s = service.stats()
        assert s.total_records == 2
        assert s.chain_length == 2
        assert s.chain_integrity is True
        assert "create" in s.by_action
        assert "alice" in s.by_actor
        assert "warning" in s.by_severity


# ─── Cross-module hooks ─────────────────────────────────────


class TestCrossModule:
    def test_record_governance(self, service: AuditService) -> None:
        rec = service.record_governance("alice", "dec-1", "policy ok")
        assert rec is not None
        assert rec.subject_id == "dec-1"
        assert rec.source_module == "governance"

    def test_record_admin_valid_action(self, service: AuditService) -> None:
        rec = service.record_admin(
            "admin-1",
            "config_change",
            subject_type="setting",
            subject_id="rate_limit",
        )
        assert rec is not None
        assert rec.action == AuditAction.CONFIG_CHANGE

    def test_record_admin_unknown_action(self, service: AuditService) -> None:
        rec = service.record_admin("admin-1", "this-action-does-not-exist")
        assert rec is not None
        assert rec.action == AuditAction.OTHER


# ─── API ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/audit/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "metrics" in body


@pytest.mark.asyncio
async def test_api_create_record(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/audit/records",
        json={
            "actor": "alice",
            "action": "create",
            "subject_type": "doc",
            "subject_id": "d1",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["actor"] == "alice"
    assert body["record_hash"] != ""


@pytest.mark.asyncio
async def test_api_get_record(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/audit/records",
        json={"actor": "alice", "action": "create"},
    )
    rid = r.json()["audit_id"]
    r2 = await client.get(f"/api/v1/audit/records/{rid}")
    assert r2.status_code == 200
    assert r2.json()["audit_id"] == rid


@pytest.mark.asyncio
async def test_api_list_records(
    client: AsyncClient,
) -> None:
    for _ in range(3):
        await client.post(
            "/api/v1/audit/records",
            json={"actor": "alice", "action": "create"},
        )
    r = await client.get("/api/v1/audit/records?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_api_chain_integrity(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/audit/records",
        json={"actor": "x", "action": "create"},
    )
    r2 = await client.get("/api/v1/audit/integrity")
    assert r2.status_code == 200
    body = r2.json()
    assert body["intact"] is True


@pytest.mark.asyncio
async def test_api_evidence_crud(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/audit/records",
        json={"actor": "x", "action": "create"},
    )
    rid = r.json()["audit_id"]
    r2 = await client.post(
        "/api/v1/audit/evidence",
        json={
            "record_id": rid,
            "kind": "document",
            "title": "doc.pdf",
            "content": {"size": 1024},
        },
    )
    assert r2.status_code == 201
    eid = r2.json()["evidence_id"]
    r3 = await client.get(f"/api/v1/audit/evidence/{eid}")
    assert r3.status_code == 200
    r4 = await client.get("/api/v1/audit/evidence")
    assert r4.status_code == 200
    assert any(e["evidence_id"] == eid for e in r4.json())


@pytest.mark.asyncio
async def test_api_lineage(
    client: AsyncClient,
) -> None:
    await client.post(
        "/api/v1/audit/records",
        json={
            "actor": "alice",
            "action": "policy_check",
            "subject_id": "dec-99",
        },
    )
    r = await client.get("/api/v1/audit/lineage/dec-99")
    assert r.status_code == 200
    body = r.json()
    assert body["root_decision_id"] == "dec-99"
    assert body["node_count"] >= 1


@pytest.mark.asyncio
async def test_api_generate_report(
    client: AsyncClient,
) -> None:
    await client.post(
        "/api/v1/audit/records",
        json={"actor": "x", "action": "create"},
    )
    r = await client.post(
        "/api/v1/audit/reports",
        json={
            "title": "Q1 Submission",
            "kind": "regulatory_submission",
            "regulator": "RBI",
            "section_titles": ["Executive Summary"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "complete"
    assert body["report_id"].startswith("rpt-")
    assert any(s["title"] == "Executive Summary" for s in body["sections"])
    rid = body["report_id"]
    r2 = await client.get(f"/api/v1/audit/reports/{rid}")
    assert r2.status_code == 200
    r3 = await client.get("/api/v1/audit/reports")
    assert r3.status_code == 200
    assert any(rep["report_id"] == rid for rep in r3.json())


@pytest.mark.asyncio
async def test_api_stats(client: AsyncClient) -> None:
    r = await client.get("/api/v1/audit/stats")
    assert r.status_code == 200
    body = r.json()
    assert "chain_length" in body
    assert "chain_integrity" in body
