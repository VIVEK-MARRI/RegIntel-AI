"""Tests for Module 9.7 — Audit Agent."""

from __future__ import annotations

import os
from typing import Any

# Lift rate-limit ceiling for the test sweep
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.agents import (
    AgentContext,
    AgentTask,
    CapabilityKind,
    TaskStatus,
)
from app.schemas.audit import (
    AuditAction,
    AuditRecord,
    AuditSeverity,
    PaginatedAuditRecords,
)
from app.schemas.audit_agent import (
    AuditAgentRequest,
    AuditAgentResult,
    AuditStatus,
    AuditViolation,
    AuditViolationSeverity,
)
from app.schemas.governance import (
    DecisionType,
    GovernanceDecision,
)
from app.schemas.knowledge_graph import (
    EntityType,
    GraphNode,
    NodeSource,
)
from app.schemas.recommendations import (
    Recommendation,
    RecommendationPriority,
    RecommendationRequest,
    RecommendationType,
)
from app.schemas.risk import RiskAssessment, RiskExplanation, RiskLevel
from app.services.audit_agent import (
    AuditAgentService,
    AuditAnalyzer,
    AuditEvidenceCollector,
    AuditReasoner,
    AuditReportGenerator,
    build_default_audit_agent_service,
)


# ─── Fakes ───────────────────────────────────────────────────


class FakeAuditService:
    def __init__(self) -> None:
        self.records: list = []
        self.verify_ok = True
        self.verify_break = ""

    def verify_chain(self):
        return (self.verify_ok, self.verify_break)

    def search_records(self, flt):
        return PaginatedAuditRecords(
            items=self.records[: flt.page_size],
            total=len(self.records),
            page=flt.page,
            page_size=flt.page_size,
            has_more=False,
        )

    def create_record(self, rec: AuditRecord):
        self.records.append(rec)
        return rec


class FakeGovernanceService:
    def __init__(self) -> None:
        self._decisions: list = []

    def check(self, **kwargs):
        class _V:
            def __init__(self, msg, sev):
                self.message = msg
                self.severity = sev
                self.policy_id = "p-1"

        class _R:
            def __init__(self):
                self.violations = [_V("exceeded confidence threshold", "high")]

        return _R()

    def list_decisions(self, flt=None):
        return [
            GovernanceDecision(
                decision_type=DecisionType.OTHER,
                subject_id="doc-1",
                actor="audit-agent",
                metadata={"policy_id": "p-1"},
            )
        ]


class FakeKGService:
    def list_all(self):
        return [
            GraphNode(
                node_id="n1",
                entity_type=EntityType.REGULATION,
                name="RBI KYC",
                source=NodeSource.CHANGE_DETECTION,
            )
        ], []


class FakeComplianceRiskService:
    def __init__(self) -> None:
        self._store: dict = {}

    def add(self, a: RiskAssessment):
        self._store[a.assessment_id] = a

    def get(self, aid):
        return self._store.get(aid)


class FakeRecommendationService:
    def generate(self, request: RecommendationRequest):
        return [
            Recommendation(
                recommendation_id="rec-1",
                title="Rec1",
                description="d",
                recommendation_type=RecommendationType.POLICY,
                priority=RecommendationPriority.P1,
            )
        ]


def _build_service(
    *,
    audit: Any = None,
    gov: Any = None,
    kg: Any = None,
    cr: Any = None,
    rec: Any = None,
) -> AuditAgentService:
    return build_default_audit_agent_service(
        audit_service=audit,
        governance_service=gov,
        knowledge_graph_service=kg,
        compliance_risk_service=cr,
        recommendation_service=rec,
    )


# ─── Unit tests: sub-components ─────────────────────────────


def test_analyzer_keyword_violation():
    a = AuditAnalyzer()
    req = AuditAgentRequest(
        query="KYC renewal must be enforced for all branches",
        subject_id="doc-1",
    )
    violations, policies = a.analyze(req)
    titles = [v.title.lower() for v in violations]
    assert any("kyc" in t for t in titles)
    # policies entry is always present for governance source
    assert any(p.get("source") == "governance" for p in policies)


def test_analyzer_policy_violation_via_governance():
    a = AuditAnalyzer(governance_service=FakeGovernanceService())
    req = AuditAgentRequest(query="check policy compliance", subject_id="doc-1")
    violations, policies = a.analyze(req)
    assert any(v.source == "policy" for v in violations)
    assert policies and policies[0]["violation_count"] == 1


def test_analyzer_risk_violation_high_score():
    cr = FakeComplianceRiskService()
    a = RiskAssessment(
        document_id="doc-1",
        risk_level=RiskLevel.HIGH,
        risk_score=0.8,
        explanation=RiskExplanation(summary="high risk detected"),
    )
    cr.add(a)
    a2 = AuditAnalyzer(compliance_risk_service=cr)
    req = AuditAgentRequest(query="check risk", risk_assessment_id=a.assessment_id)
    violations, _ = a2.analyze(req)
    severities = [v.severity for v in violations]
    assert AuditViolationSeverity.CRITICAL in severities


def test_analyzer_truncates_to_max_violations():
    a = AuditAnalyzer()
    req = AuditAgentRequest(
        query="KYC renewal, incident_reporting, data_localisation, capital_adequacy",
        subject_id="x",
        max_violations=2,
    )
    violations, _ = a.analyze(req)
    assert len(violations) == 2


def test_evidence_collector_pulls_audit_kg_and_decisions():
    audit = FakeAuditService()
    audit.records.append(
        AuditRecord(
            action=AuditAction.OTHER,
            actor="audit-agent",
            subject_id="doc-1",
            severity=AuditSeverity.INFO,
        )
    )
    gov = FakeGovernanceService()
    kg = FakeKGService()
    c = AuditEvidenceCollector(
        audit_service=audit,
        governance_service=gov,
        knowledge_graph_service=kg,
    )
    req = AuditAgentRequest(
        query="hello world", subject_id="doc-1", include_evidence=True
    )
    items, lineage, chain = c.collect(req)
    assert any(i.evidence_kind == "audit_record" for i in items)
    assert any(i.evidence_kind == "kg_node" for i in items)
    assert any(n.kind == "governance_decision" for n in lineage)
    assert chain["verified"] is True


def test_evidence_collector_handles_missing_audit_service():
    c = AuditEvidenceCollector()
    req = AuditAgentRequest(query="hello", subject_id="y")
    items, lineage, chain = c.collect(req)
    assert items == [] and lineage == []
    assert chain["verified"] is None


def test_reasoner_compliant():
    r = AuditReasoner()
    status_, conf, aff = r.reason([], [], {"verified": None, "break_at": ""})
    assert status_ == AuditStatus.COMPLIANT
    assert conf >= 0.6
    assert aff == []


def test_reasoner_non_compliant_chain_broken():
    r = AuditReasoner()
    status_, conf, _ = r.reason([], [], {"verified": False, "break_at": "abc"})
    assert status_ == AuditStatus.NON_COMPLIANT
    assert conf >= 0.9


def test_reasoner_partially_compliant_medium_violations():
    r = AuditReasoner()
    v = AuditViolation(
        title="x", description="", severity=AuditViolationSeverity.MEDIUM
    )
    status_, _, _ = r.reason([v], [], {"verified": None, "break_at": ""})
    assert status_ == AuditStatus.PARTIALLY_COMPLIANT


def test_report_generator_builds_markdown():
    g = AuditReportGenerator()
    req = AuditAgentRequest(query="kyc", subject_id="x", include_evidence=True)
    v = AuditViolation(
        title="KYC",
        description="d",
        severity=AuditViolationSeverity.HIGH,
    )
    res = g.build(
        request=req,
        violations=[v],
        evidence=[],
        lineage=[],
        policies=[],
        chain={"verified": True, "break_at": ""},
        status=AuditStatus.PARTIALLY_COMPLIANT,
        confidence=0.8,
        affected_areas=["kyc"],
        rec_ids=[],
        audit_record_ids=[],
        decision_ids=[],
        agent_id="a-1",
        duration_ms=5.0,
    )
    assert res.audit_status == AuditStatus.PARTIALLY_COMPLIANT
    assert "KYC" in res.report_markdown
    assert "Audit Report" in res.report_markdown


# ─── Agent + service tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_audit_agent_execute_returns_result():
    svc = _build_service()
    req = AuditAgentRequest(query="kyc renewal is overdue", subject_id="doc-1")
    result = await svc.run(req, context=AgentContext(actor="t"))
    assert isinstance(result, AuditAgentResult)
    assert result.audit_status in (
        AuditStatus.PARTIALLY_COMPLIANT,
        AuditStatus.NON_COMPLIANT,
        AuditStatus.COMPLIANT,
        AuditStatus.UNKNOWN,
    )
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_audit_agent_with_full_services_writes_record_and_recommendation():
    audit = FakeAuditService()
    gov = FakeGovernanceService()
    kg = FakeKGService()
    cr = FakeComplianceRiskService()
    rec = FakeRecommendationService()
    svc = _build_service(audit=audit, gov=gov, kg=kg, cr=cr, rec=rec)
    a = RiskAssessment(
        document_id="d",
        risk_level=RiskLevel.MEDIUM,
        risk_score=0.5,
        explanation=RiskExplanation(summary="medium risk"),
    )
    cr.add(a)
    req = AuditAgentRequest(
        query="kyc",
        subject_id="d",
        risk_assessment_id=a.assessment_id,
        include_evidence=True,
        include_lineage=True,
    )
    result = await svc.run(req)
    assert result.audit_record_ids  # wrote an audit record
    assert result.recommendation_ids  # generated a recommendation
    assert result.evidence  # pulled evidence


@pytest.mark.asyncio
async def test_audit_agent_invalid_request_returns_failure():
    svc = _build_service()
    task = AgentTask(
        capability=CapabilityKind.AUDIT,
        input={"bogus": 1},
        target_agent=svc.agent.name,
    )
    res = await svc.agent.execute(task)
    assert res.status == TaskStatus.FAILED
    assert "invalid request" in res.error


def test_audit_agent_health_uses_superclass():
    svc = _build_service()
    h = svc.health()
    assert h.agent == "audit"
    assert h.healthy is True


@pytest.mark.asyncio
async def test_audit_metrics_summary_increments_after_run():
    svc = _build_service()
    req = AuditAgentRequest(query="kyc", subject_id="x")
    await svc.run(req)
    m = svc.metrics()
    assert m.total_invocations == 1
    assert m.total_successful == 1
    assert m.by_task_kind.get("compliance_verification") == 1


@pytest.mark.asyncio
async def test_audit_chain_break_sets_non_compliant():
    audit = FakeAuditService()
    audit.verify_ok = False
    audit.verify_break = "record-42"
    svc = _build_service(audit=audit)
    req = AuditAgentRequest(query="hello", subject_id="x")
    res = await svc.run(req)
    assert res.audit_status == AuditStatus.NON_COMPLIANT
    assert res.chain_verified is False
    assert res.chain_break_at == "record-42"


# ─── API integration ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_audit_run():
    from app.api.dependencies import get_audit_agent_service
    from app.api.dependencies import reset_audit_agent_service

    reset_audit_agent_service()
    svc = build_default_audit_agent_service()
    app.dependency_overrides[get_audit_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.post(
                "/api/v1/agents/audit/run",
                json={"query": "kyc", "subject_id": "x"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["agent"] == "audit"
            assert "audit_status" in body
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_audit_health():
    from app.api.dependencies import get_audit_agent_service, reset_audit_agent_service

    reset_audit_agent_service()
    svc = build_default_audit_agent_service()
    app.dependency_overrides[get_audit_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get("/api/v1/agents/audit/health")
            assert r.status_code == 200
            assert r.json()["agent"] == "audit"
            r2 = await ac.get("/api/v1/agents/audit/metrics")
            assert r2.status_code == 200
            assert "total_invocations" in r2.json()
            r3 = await ac.get("/api/v1/agents/audit/task-kinds")
            assert r3.status_code == 200
            assert "compliance_verification" in r3.json()
    finally:
        app.dependency_overrides.clear()


def test_running_mean_helper():
    from app.services.audit_agent import _running_mean

    assert _running_mean(0.0, 5.0, 1) == 5.0
    assert _running_mean(5.0, 7.0, 2) == 6.0
    assert _running_mean(6.0, 8.0, 3) == 6.667
