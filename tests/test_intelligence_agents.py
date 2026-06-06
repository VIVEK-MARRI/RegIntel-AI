"""Tests for Module 9.4-9.6 — Intelligence Agent Layer."""

from __future__ import annotations

import asyncio
import os
import time

import pytest

# Ensure rate-limit doesn't 429 during the test sweep
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.schemas.agents import (
    AgentContext,
    AgentResult,
    AgentTask,
    CapabilityKind,
    CoordinatorRequest,
    TaskStatus,
)
from app.schemas.intelligence_agents import (
    AgentCollaboration,
    ComplianceAgentRequest,
    IntelligenceAgentMetrics,
    ResearchAgentRequest,
    ResearchFinding,
    ResearchMode,
    ResearchPlanStep,
    RiskAgentRequest,
    RiskProjection,
    RiskScenarioKind,
)
from app.schemas.recommendations import (
    ActionStatus,
    Recommendation,
    RecommendationRequest,
    RecommendationType,
)
from app.schemas.research import (
    CitationSource,
    ResearchCitation,
    ResearchKind,
    ResearchReport,
    ResearchRequest,
    ResearchStep,
    ResearchStepStatus,
    ResearchStepType,
)
from app.schemas.risk import (
    AffectedArea,
    AffectedAreaRecord,
    ComplianceGap,
    RecommendedAction,
    RecommendedActionType,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskCategory,
    RiskLevel,
)
from app.schemas.recommendations import (
    RecommendationPriority,
    ActionPlan,
    ActionPlanStep,
)
from app.services.intelligence_agents import (
    AgentCollaborationBroker,
    ComplianceAgent,
    ComplianceAnalyzer,
    ComplianceReasoner,
    ComplianceRecommendationGenerator,
    ComplianceReportBuilder,
    CoordinatorDriver,
    IntelligenceAgentFactory,
    IntelligenceAgentService,
    ResearchAgent,
    ResearchAgentExecutor,
    ResearchAgentPlanner,
    ResearchAgentReasoner,
    ResearchAgentReportGenerator,
    RiskAnalyzer,
    RiskForecastCoordinator,
    RiskIntelligenceAgent,
    RiskReportGenerator,
    ScenarioPlanner,
    build_default_intelligence_agent_service,
)
from app.services.observability import (
    get_intelligence_agent_metrics,
    reset_intelligence_agent_metrics,
)


# ─── helpers / fixtures ──────────────────────────────────────


class FakeResearchService:
    def __init__(self) -> None:
        self.runs = 0
        self.provider_items: list = []

    def run(
        self, request: ResearchRequest, *, top_k: int = 5
    ) -> ResearchReport:
        self.runs += 1
        items = self.provider_items[:top_k] or [
            {
                "id": "doc-1",
                "title": "RBI KYC Master Direction",
                "body": "Know Your Customer guidelines for banks",
            }
        ]
        citations = [
            ResearchCitation(
                source=CitationSource.SEARCH,
                title=it["title"],
                reference=it["id"],
                score=0.8,
            )
            for it in items
        ]
        steps = [
            ResearchStep(
                step_type=ResearchStepType.RETRIEVE,
                description="retrieve",
                status=ResearchStepStatus.COMPLETED,
                duration_ms=1.0,
            )
        ]
        return ResearchReport(
            plan_id="plan-x",
            query=request.query,
            kind=request.kind,
            summary="fake summary",
            key_findings=["k1"],
            citations=citations,
            steps=steps,
            generated_at=time.time(),
            duration_ms=1.0,
        )

    def add_knowledge_item(self, item):
        return self.provider_items.append(item) or item.get("id", f"k-{len(self.provider_items)}")


class FakeKGService:
    def __init__(self) -> None:
        from app.schemas.knowledge_graph import (
            GraphNode,
            EntityType,
            NodeSource,
        )
        self._nodes = [
            GraphNode(
                node_id="n1",
                entity_type=EntityType.REGULATION,
                name="RBI KYC",
                source=NodeSource.CHANGE_DETECTION,
            ),
            GraphNode(
                node_id="n2",
                entity_type=EntityType.REQUIREMENT,
                name="KYC requirement",
                source=NodeSource.CHANGE_DETECTION,
            ),
        ]
        self._rels = []

    def list_all(self):
        return list(self._nodes), list(self._rels)


class FakeComplianceRiskService:
    def __init__(self) -> None:
        self._store: dict = {}

    def add(self, a: RiskAssessment) -> None:
        self._store[a.assessment_id] = a

    def get(self, aid: str):
        return self._store.get(aid)

    def history_for(self, *, document_id=None, source=None):
        return list(self._store.values())


class FakeRecommendationService:
    def __init__(self) -> None:
        self._recs: list = []

    def generate(self, request: RecommendationRequest) -> list:
        recs = []
        for i in range(min(2, request.max_recommendations)):
            r = Recommendation(
                recommendation_id=f"rec-{i}",
                title=f"Rec {i}",
                description="desc",
                recommendation_type=RecommendationType.POLICY,
                priority=RecommendationPriority.P1,
                action_plan=ActionPlan(
                    title=f"plan {i}",
                    steps=[
                        ActionPlanStep(
                            step_id=f"ps-{i}",
                            title="step",
                        )
                    ]
                ),
                risk_assessment_id=request.risk_assessment_id,
            )
            recs.append(r)
            self._recs.append(r)
        return recs


class FakeGovernanceService:
    def check(self, **kwargs):
        class _Result:
            compliant = True
            violations = []
            rules_evaluated = []
        return _Result()


class FakeForecastingService:
    def forecast(self, request):
        from app.schemas.forecasting import (
            ForecastPoint,
            RiskForecast,
        )
        f = RiskForecast(
            forecast_id="fcast-x",
            horizon_days=request.horizon_days,
            predicted_risk_score=0.7,
            predicted_risk_level=RiskLevel.HIGH,
            method="linear_regression",
            points=[
                ForecastPoint(
                    timestamp=time.time() + 86400 * 30,
                    predicted_score=0.75,
                    lower_bound=0.65,
                    upper_bound=0.85,
                    confidence=0.7,
                )
            ],
        )
        return f


class FakeMonitoringService:
    pass


class FakeImpactService:
    pass


def _build_factory() -> IntelligenceAgentFactory:
    research = FakeResearchService()
    kg = FakeKGService()
    risk = FakeComplianceRiskService()
    rec = FakeRecommendationService()
    gov = FakeGovernanceService()
    fc = FakeForecastingService()
    factory = IntelligenceAgentFactory(
        agent_framework_service=None,
        research_service=research,
        knowledge_graph_service=kg,
        compliance_risk_service=risk,
        recommendation_service=rec,
        governance_service=gov,
        impact_analysis_service=FakeImpactService(),
        forecasting_service=fc,
        monitoring_service=FakeMonitoringService(),
    )
    return factory


def _build_service() -> IntelligenceAgentService:
    return IntelligenceAgentService(_build_factory())


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_intelligence_agent_metrics()
    yield
    reset_intelligence_agent_metrics()


# ─── M9.4 — Research Agent ───────────────────────────────────


class TestResearchAgentPlanner:
    def test_general_mode_produces_steps(self):
        planner = ResearchAgentPlanner()
        req = ResearchAgentRequest(
            query="What is KYC?",
            mode=ResearchMode.GENERAL,
        )
        steps = planner.plan(req)
        assert any(s.action == "plan" for s in steps)
        assert any(s.capability == "knowledge_graph" for s in steps)

    def test_timeline_mode_includes_timeline_synth(self):
        planner = ResearchAgentPlanner()
        req = ResearchAgentRequest(
            query="KYC changes between 2020 and 2025",
            mode=ResearchMode.TIMELINE,
        )
        steps = planner.plan(req)
        assert any(s.action == "timeline_synth" for s in steps)

    def test_comparative_mode(self):
        planner = ResearchAgentPlanner()
        req = ResearchAgentRequest(
            query="Compare RBI vs SEBI on KYC",
            mode=ResearchMode.COMPARATIVE,
        )
        steps = planner.plan(req)
        assert steps
        # The underlying ResearchPlanner maps "compare" → compare step
        assert any(s.action in {"compare", "plan"} for s in steps)


class TestResearchAgentExecutor:
    def test_run_with_fake_research(self):
        ex = ResearchAgentExecutor(
            research_service=FakeResearchService(),
            knowledge_graph_service=FakeKGService(),
        )
        req = ResearchAgentRequest(
            query="KYC regulations",
            mode=ResearchMode.GENERAL,
        )
        plan = ResearchAgentPlanner().plan(req)
        executed, findings, citations, timeline = ex.execute(req, plan)
        assert citations
        assert findings
        assert any(s.action == "kg_explore" for s in executed)

    def test_run_without_services(self):
        ex = ResearchAgentExecutor()
        req = ResearchAgentRequest(query="hello world query here")
        plan = ResearchAgentPlanner().plan(req)
        executed, findings, citations, timeline = ex.execute(req, plan)
        # Without KG service, no KG insights but plan still completes
        assert all(s.finished_at > 0 for s in executed if s.action in {
            "plan", "retrieve", "compare", "reason", "summarize"
        })


class TestResearchAgentReasoner:
    def test_with_no_findings(self):
        summary, conf = ResearchAgentReasoner().reason("q", [], [], [])
        assert "No structured findings" in summary
        assert conf == 0.3

    def test_with_findings(self):
        summary, conf = ResearchAgentReasoner().reason(
            "q",
            [ResearchFinding(statement="x", confidence=0.8)],
            [{"id": "c1"}],
            [ResearchPlanStep(action="plan", description="d")],
        )
        assert conf > 0.5
        assert "synthesis" in summary.lower()


class TestResearchAgentReportGenerator:
    def test_build_comparative(self):
        gen = ResearchAgentReportGenerator()
        req = ResearchAgentRequest(
            query="compare KYC vs AML",
            mode=ResearchMode.COMPARATIVE,
        )
        r = gen.build(
            request=req,
            plan=[],
            findings=[ResearchFinding(statement="x", confidence=0.7)],
            citations=[{"citation_id": "c1", "title": "t"}],
            timeline=[],
            summary="s",
            confidence=0.7,
            agent_id="agt-1",
            duration_ms=12.3,
        )
        assert r.agent == "research"
        assert r.comparisons
        assert r.duration_ms == 12.3


class TestResearchAgent:
    @pytest.mark.asyncio
    async def test_execute_general(self):
        agent = ResearchAgent(
            agent_metadata := __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-research",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            research_service=FakeResearchService(),
            knowledge_graph_service=FakeKGService(),
        )
        req = ResearchAgentRequest(query="KYC requirements in RBI")
        task = AgentTask(
            capability=CapabilityKind.RETRIEVAL,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["findings"]
        assert result.output["agent"] == "research"

    @pytest.mark.asyncio
    async def test_execute_timeline(self):
        agent = ResearchAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-research-t",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            research_service=FakeResearchService(),
            knowledge_graph_service=FakeKGService(),
        )
        req = ResearchAgentRequest(
            query="KYC changes between 2020 and 2025",
            mode=ResearchMode.TIMELINE,
        )
        task = AgentTask(
            capability=CapabilityKind.RETRIEVAL,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["mode"] == "timeline"

    @pytest.mark.asyncio
    async def test_execute_invalid_request(self):
        agent = ResearchAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-research-bad",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
        )
        task = AgentTask(
            capability=CapabilityKind.RETRIEVAL,
            input={"bad": "payload"},
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.FAILED


# ─── M9.5 — Compliance Agent ─────────────────────────────────


class TestComplianceAnalyzer:
    def test_no_services_seeds_keyword_obligations(self):
        analyzer = ComplianceAnalyzer()
        req = ComplianceAgentRequest(
            query="KYC gap analysis",
            focus_areas=["kyc"],
        )
        obls, gaps, areas, evals = analyzer.analyze(req, None)
        assert obls  # seed obligations
        assert "kyc" in areas
        assert evals == []

    def test_with_assessment(self):
        from app.schemas.risk import RiskExplanation
        ra = RiskAssessment(
            assessment_id="r1",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            risk_categories=[RiskCategory.COMPLIANCE_GAP],
            affected_areas=[
                AffectedAreaRecord(area=AffectedArea.KYC, exposure_score=0.6)
            ],
            compliance_gaps=[
                ComplianceGap(
                    description="KYC missing",
                    severity=RiskLevel.HIGH,
                    area=AffectedArea.KYC,
                )
            ],
            explanation=RiskExplanation(summary="x"),
        )
        analyzer = ComplianceAnalyzer()
        req = ComplianceAgentRequest(query="query text")
        obls, gaps, areas, evals = analyzer.analyze(req, ra)
        assert "kyc" in areas
        assert any("KYC" in g.title for g in gaps)
        assert len(gaps) == 1


# ─── M9.6 — Risk Intelligence Agent ─────────────────────────


class TestComplianceAgent:
    @pytest.mark.asyncio
    async def test_execute_no_assessment(self):
        agent = ComplianceAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-compliance-no",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.COMPLIANCE, name="c"
                    )
                ],
            ),
            recommendation_service=FakeRecommendationService(),
            governance_service=FakeGovernanceService(),
        )
        req = ComplianceAgentRequest(
            query="What are the compliance gaps?",
            focus_areas=["kyc", "data_privacy"],
        )
        task = AgentTask(
            capability=CapabilityKind.COMPLIANCE,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["obligations"]
        assert "kyc" in result.output["affected_areas"]

    @pytest.mark.asyncio
    async def test_execute_with_risk_assessment(self):
        from app.schemas.risk import RiskExplanation
        risk = FakeComplianceRiskService()
        a = RiskAssessment(
            assessment_id="r1",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            affected_areas=[
                AffectedAreaRecord(area=AffectedArea.AML, exposure_score=0.8)
            ],
            compliance_gaps=[
                ComplianceGap(
                    description="AML gap desc",
                    severity=RiskLevel.HIGH,
                    area=AffectedArea.AML,
                )
            ],
            explanation=RiskExplanation(summary="x"),
        )
        risk.add(a)
        agent = ComplianceAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-compliance-2",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.COMPLIANCE, name="c"
                    )
                ],
            ),
            compliance_risk_service=risk,
            recommendation_service=FakeRecommendationService(),
        )
        req = ComplianceAgentRequest(
            query="query text",
            risk_assessment_id="r1",
        )
        task = AgentTask(
            capability=CapabilityKind.COMPLIANCE,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert "aml" in result.output["affected_areas"]
        assert any("AML" in g["title"] for g in result.output["gaps"])


# ─── M9.6 — Risk Intelligence Agent ─────────────────────────


class TestRiskAnalyzer:
    def test_no_assessment(self):
        analyzer = RiskAnalyzer()
        req = RiskAgentRequest(query="valid risk query")
        a, lvl, sc, trends = analyzer.analyze(req)
        assert a is None
        assert lvl == "medium"
        assert sc == 0.5
        assert trends == []

    def test_with_assessment(self):
        from app.schemas.risk import RiskExplanation
        risk = FakeComplianceRiskService()
        a = RiskAssessment(
            assessment_id="r1",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            affected_areas=[
                AffectedAreaRecord(area=AffectedArea.AML, exposure_score=0.8)
            ],
            compliance_gaps=[
                ComplianceGap(
                    description="AML gap desc",
                    severity=RiskLevel.HIGH,
                    area=AffectedArea.AML,
                )
            ],
            explanation=RiskExplanation(summary="x"),
        )
        risk.add(a)
        analyzer = RiskAnalyzer(compliance_risk_service=risk)
        req = RiskAgentRequest(query="valid risk query", risk_assessment_id="r1")
        a2, lvl, sc, trends = analyzer.analyze(req)
        assert lvl == "high"
        assert sc == 0.7


class TestRiskForecastCoordinator:
    def test_without_forecasting_service(self):
        coord = RiskForecastCoordinator()
        req = RiskAgentRequest(query="valid query", horizon_days=90)
        projections, drift = coord.forecast(req, 0.5)
        assert projections
        assert all(0.0 <= p.lower_bound <= p.upper_bound <= 1.0 for p in projections)
        assert drift is False

    def test_with_forecasting_service(self):
        coord = RiskForecastCoordinator(forecasting_service=FakeForecastingService())
        req = RiskAgentRequest(query="valid query", horizon_days=30)
        projections, drift = coord.forecast(req, 0.5)
        assert projections
        assert projections[0].method == "linear_regression"


class TestScenarioPlanner:
    def test_generate_scenarios(self):
        planner = ScenarioPlanner()
        req = RiskAgentRequest(
            query="valid query",
            scenario_kinds=[
                RiskScenarioKind.BASELINE,
                RiskScenarioKind.WORST_CASE,
            ],
        )
        scenarios = planner.plan(req, 0.5)
        assert len(scenarios) == 2
        worst = next(s for s in scenarios if s.kind == RiskScenarioKind.WORST_CASE)
        assert worst.predicted_score > 0.5

    def test_disabled(self):
        planner = ScenarioPlanner()
        req = RiskAgentRequest(
            query="valid query", include_scenarios=False, scenario_kinds=[]
        )
        assert planner.plan(req, 0.5) == []


class TestRiskReportGenerator:
    def test_build(self):
        gen = RiskReportGenerator()
        req = RiskAgentRequest(query="valid query", horizon_days=30)
        r = gen.build(
            request=req,
            assessment=None,
            risk_level="high",
            risk_score=0.7,
            projections=[
                RiskProjection(
                    horizon_days=30,
                    predicted_score=0.75,
                    lower_bound=0.6,
                    upper_bound=0.9,
                )
            ],
            scenarios=[],
            trends=[],
            drift=False,
            recommended_actions=[],
            confidence=0.6,
            agent_id="agt-1",
            duration_ms=2.0,
        )
        assert r.risk_level == "high"
        assert r.forecast[0].predicted_score == 0.75


class TestRiskAgent:
    @pytest.mark.asyncio
    async def test_execute_basic(self):
        from app.schemas.risk import RiskExplanation
        risk_svc = FakeComplianceRiskService()
        a = RiskAssessment(
            assessment_id="r1",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            explanation=RiskExplanation(summary="x"),
        )
        risk_svc.add(a)
        agent = RiskIntelligenceAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-risk",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.RISK_ASSESSMENT, name="r"
                    )
                ],
            ),
            compliance_risk_service=risk_svc,
            forecasting_service=FakeForecastingService(),
            monitoring_service=FakeMonitoringService(),
            recommendation_service=FakeRecommendationService(),
        )
        req = RiskAgentRequest(
            query="What will happen in 90 days?",
            risk_assessment_id="r1",
            horizon_days=60,
        )
        task = AgentTask(
            capability=CapabilityKind.RISK_ASSESSMENT,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["risk_level"] == "high"
        assert result.output["scenarios"]
        assert result.output["forecast"]
        assert result.output["recommended_actions"]

    @pytest.mark.asyncio
    async def test_execute_no_services(self):
        agent = RiskIntelligenceAgent(
            __import__(
                "app.schemas.agents", fromlist=["AgentMetadata"]
            ).AgentMetadata(
                name="test-risk-2",
                capabilities=[
                    __import__(
                        "app.schemas.agents", fromlist=["AgentCapability"]
                    ).AgentCapability(
                        kind=CapabilityKind.RISK_ASSESSMENT, name="r"
                    )
                ],
            ),
        )
        req = RiskAgentRequest(query="valid query", horizon_days=30)
        task = AgentTask(
            capability=CapabilityKind.RISK_ASSESSMENT,
            input=req.model_dump(mode="json"),
            context=AgentContext(),
        )
        result = await agent.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["scenarios"]


# ─── Cross-agent collaboration ───────────────────────────────


class TestAgentCollaborationBroker:
    def test_record_and_filter(self):
        broker = AgentCollaborationBroker()
        c1 = AgentCollaboration(
            from_agent="research", to_agent="compliance", request_kind="x"
        )
        c2 = AgentCollaboration(
            from_agent="compliance", to_agent="risk", request_kind="x"
        )
        broker.record(c1)
        broker.record(c2)
        assert len(broker.list()) == 2
        assert len(broker.list(from_agent="research")) == 1
        assert len(broker.list(to_agent="risk")) == 1


class TestIntelligenceAgentFactory:
    def test_build_agents(self):
        factory = _build_factory()
        assert factory.research_agent.name == "research-agent"
        assert factory.compliance_agent.name == "compliance-agent"
        assert factory.risk_agent.name == "risk-agent"

    def test_collaborate_records(self):
        factory = _build_factory()
        c = factory.collaborate(
            "research", "compliance", "evidence_handoff",
            {"k1": 1}, {"k2": 2},
        )
        assert c.from_agent == "research"
        assert c.to_agent == "compliance"
        assert c.evidence_keys == ["k1"]
        assert c.result_keys == ["k2"]
        metrics = get_intelligence_agent_metrics().snapshot()
        assert metrics["total_collaborations"] >= 1


class TestCoordinatorDriver:
    @pytest.mark.asyncio
    async def test_research_then_compliance(self):
        factory = _build_factory()
        driver = CoordinatorDriver(factory)
        r, c, collabs = await driver.run_research_then_compliance(
            ResearchAgentRequest(query="KYC regulations")
        )
        assert r.findings
        assert c.affected_areas
        assert len(collabs) == 2

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        factory = _build_factory()
        driver = CoordinatorDriver(factory)
        out = await driver.run_full_pipeline("KYC risk in 90 days")
        assert "research" in out
        assert "compliance" in out
        assert "risk" in out
        assert "collaborations" in out


# ─── Service-level tests ─────────────────────────────────────


class TestIntelligenceAgentService:
    @pytest.mark.asyncio
    async def test_run_research(self):
        svc = _build_service()
        req = ResearchAgentRequest(query="KYC", mode=ResearchMode.GENERAL)
        r = await svc.run_research(req)
        assert r.findings
        assert r.agent == "research"

    @pytest.mark.asyncio
    async def test_run_compliance(self):
        svc = _build_service()
        req = ComplianceAgentRequest(
            query="compliance gaps",
            focus_areas=["kyc"],
        )
        r = await svc.run_compliance(req)
        assert r.obligations
        assert r.agent == "compliance"

    @pytest.mark.asyncio
    async def test_run_risk(self):
        svc = _build_service()
        req = RiskAgentRequest(query="valid risk query", horizon_days=30)
        r = await svc.run_risk(req)
        assert r.forecast
        assert r.agent == "risk"

    @pytest.mark.asyncio
    async def test_coordinate_full(self):
        svc = _build_service()
        out = await svc.coordinate("KYC pipeline")
        assert "research" in out and "compliance" in out and "risk" in out

    @pytest.mark.asyncio
    async def test_coordinate_research_compliance(self):
        svc = _build_service()
        out = await svc.coordinate_research_compliance(
            ResearchAgentRequest(query="KYC")
        )
        assert "research" in out and "compliance" in out

    def test_health_endpoints(self):
        svc = _build_service()
        h = svc.health_research()
        assert h.agent == "research"
        assert h.healthy
        h = svc.health_compliance()
        assert h.agent == "compliance"
        h = svc.health_risk()
        assert h.agent == "risk"

    def test_metrics(self):
        svc = _build_service()
        m = svc.metrics()
        assert m.research.agent == "research"
        assert m.compliance.agent == "compliance"
        assert m.risk.agent == "risk"


class TestMetricsIntegration:
    @pytest.mark.asyncio
    async def test_metrics_recorded_across_runs(self):
        svc = _build_service()
        await svc.run_research(ResearchAgentRequest(query="valid query one"))
        await svc.run_research(ResearchAgentRequest(query="valid query two"))
        await svc.run_compliance(ComplianceAgentRequest(query="valid compliance query"))
        await svc.run_risk(RiskAgentRequest(query="valid risk query four"))
        m = svc.metrics()
        assert m.research.total_invocations == 2
        assert m.compliance.total_invocations == 1
        assert m.risk.total_invocations == 1
        snap = get_intelligence_agent_metrics().snapshot()
        assert snap["research"]["invocations"] == 2
        assert snap["compliance"]["invocations"] == 1
        assert snap["risk"]["invocations"] == 1


# ─── Default factory wiring ─────────────────────────────────


class TestDefaultFactory:
    def test_build_default(self):
        svc = build_default_intelligence_agent_service()
        assert isinstance(svc, IntelligenceAgentService)
        assert svc.factory.research_agent.name == "research-agent"
        assert svc.factory.compliance_agent.name == "compliance-agent"
        assert svc.factory.risk_agent.name == "risk-agent"


# ─── API integration tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_api_research_run():
    """Smoke test the /agents/research/run endpoint."""
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/agents/research/run",
                json={"query": "KYC regulations"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["agent"] == "research"
            assert data["findings"]
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


@pytest.mark.asyncio
async def test_api_compliance_run():
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/agents/compliance/run",
                json={"query": "compliance gaps", "focus_areas": ["kyc"]},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["agent"] == "compliance"
            assert data["obligations"]
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


@pytest.mark.asyncio
async def test_api_risk_run():
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/agents/risk/run",
                json={"query": "risk 90 days", "horizon_days": 30},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["agent"] == "risk"
            assert data["forecast"]
            assert data["scenarios"]
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


@pytest.mark.asyncio
async def test_api_health_endpoints():
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in (
                "/api/v1/agents/research/health",
                "/api/v1/agents/compliance/health",
                "/api/v1/agents/risk/health",
                "/api/v1/agents/metrics",
            ):
                resp = await client.get(path)
                assert resp.status_code == 200, (path, resp.text)
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


@pytest.mark.asyncio
async def test_api_coordinate_pipeline():
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/agents/coordinate/pipeline",
                json={"query": "KYC compliance risk", "mode": "general"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert "research" in data
            assert "compliance" in data
            assert "risk" in data
            assert "collaborations" in data
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


@pytest.mark.asyncio
async def test_api_collaborations():
    from app.api.dependencies import get_intelligence_agent_service
    factory = _build_factory()
    svc = IntelligenceAgentService(factory)
    app.dependency_overrides[get_intelligence_agent_service] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Trigger a collab
            await client.post(
                "/api/v1/agents/coordinate/pipeline",
                json={"query": "KYC compliance risk", "mode": "general"},
            )
            resp = await client.get("/api/v1/agents/collaborations")
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1
    finally:
        app.dependency_overrides.pop(get_intelligence_agent_service, None)


# ─── Sanity tests for schema validation ─────────────────────


class TestSchemaValidation:
    def test_research_request_min_length(self):
        with pytest.raises(Exception):
            ResearchAgentRequest(query="x")

    def test_risk_request_horizon_bounds(self):
        with pytest.raises(Exception):
            RiskAgentRequest(query="valid", horizon_days=0)
        with pytest.raises(Exception):
            RiskAgentRequest(query="valid", horizon_days=1000)

    def test_finding_confidence_bounds(self):
        with pytest.raises(Exception):
            ResearchFinding(statement="x", confidence=2.0)
