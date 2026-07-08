"""Phase 8 — Multi-Agent & Orchestration Validation.

Covers: schema contracts for all agent modules (M9 framework,
M9.4-9.6 intelligence agents, M9.7 audit agent, M9.8 orchestration,
M9.9 agent analytics), response orchestrator (M5.6) pipeline
validation, cross-orchestrator integration, and edge cases.
"""

from __future__ import annotations

import pytest


# ══════════════════════════════════════════════════════════════════
# 8.1 — Module 9 Framework Schema Contracts
# ══════════════════════════════════════════════════════════════════


class TestM9FrameworkSchemas:
    """Module 9 — Multi-Agent Framework schema contracts."""

    def test_capability_kind_enum(self):
        from app.schemas.agents import CapabilityKind

        assert CapabilityKind.RETRIEVAL.value == "retrieval"
        assert CapabilityKind.REASONING.value == "reasoning"
        assert CapabilityKind.AUDIT.value == "audit"
        assert CapabilityKind.ORCHESTRATION.value == "orchestration"

    def test_agent_status_enum(self):
        from app.schemas.agents import AgentStatus

        assert AgentStatus.ACTIVE.value == "active"
        assert AgentStatus.FAILED.value == "failed"

    def test_task_status_enum(self):
        from app.schemas.agents import TaskStatus

        assert TaskStatus.SUCCEEDED.value == "succeeded"
        assert TaskStatus.RETRYING.value == "retrying"

    def test_agent_capability_round_trip(self):
        from app.schemas.agents import AgentCapability, CapabilityKind

        cap = AgentCapability(kind=CapabilityKind.RETRIEVAL, name="doc-retrieval")
        assert cap.model_dump()["kind"] == "retrieval"

    def test_agent_context_defaults(self):
        from app.schemas.agents import AgentContext

        ctx = AgentContext()
        assert ctx.timeout_ms == 30_000
        assert ctx.actor == "system"

    def test_agent_task_defaults(self):
        from app.schemas.agents import AgentTask, CapabilityKind

        task = AgentTask(capability=CapabilityKind.RETRIEVAL)
        assert task.max_retries == 0
        assert task.target_agent == ""

    def test_agent_result_property(self):
        from app.schemas.agents import AgentResult, TaskStatus

        r = AgentResult(status=TaskStatus.SUCCEEDED)
        assert r.succeeded is True
        r2 = AgentResult(status=TaskStatus.FAILED)
        assert r2.succeeded is False

    def test_agent_metadata_defaults(self):
        from app.schemas.agents import AgentMetadata

        m = AgentMetadata(name="test-agent")
        assert m.version == "1.0.0"
        assert m.default_max_retries == 0
        assert m.priority == 0

    def test_coordinator_plan_defaults(self):
        from app.schemas.agents import CoordinatorPlan

        p = CoordinatorPlan()
        assert p.steps == []
        assert p.selected_agents == []

    def test_agent_registration_request_defaults(self):
        from app.schemas.agents import AgentRegistrationRequest

        r = AgentRegistrationRequest(name="test")
        assert r.version == "1.0.0"
        assert r.priority == 0

    def test_agent_execution_request_defaults(self):
        from app.schemas.agents import AgentExecutionRequest, CapabilityKind

        r = AgentExecutionRequest(agent_name="test", capability=CapabilityKind.OTHER)
        assert r.max_retries is None

    def test_coordinator_request_defaults(self):
        from app.schemas.agents import CoordinatorRequest

        r = CoordinatorRequest(query="test query here")
        assert r.max_steps == 8


# ══════════════════════════════════════════════════════════════════
# 8.2 — Intelligence Agent Schema Contracts (M9.4-9.6)
# ══════════════════════════════════════════════════════════════════


class TestIntelligenceAgentSchemas:
    """M9.4-9.6 — Research, Compliance, Risk agent schema contracts."""

    def test_research_mode_enum(self):
        from app.schemas.intelligence_agents import ResearchMode

        assert ResearchMode.MULTI_HOP.value == "multi_hop"
        assert ResearchMode.TIMELINE.value == "timeline"

    def test_research_agent_request_defaults(self):
        from app.schemas.intelligence_agents import ResearchAgentRequest

        req = ResearchAgentRequest(query="KYC requirements under RBI circulars")
        assert req.mode.value == "general"
        assert req.top_k == 5
        assert req.max_steps == 8

    def test_research_agent_result_has_required_fields(self):
        from app.schemas.intelligence_agents import ResearchAgentResult, ResearchMode

        r = ResearchAgentResult(query="test", summary="done", mode=ResearchMode.GENERAL)
        assert r.agent == "research"
        assert r.duration_ms >= 0

    def test_research_finding_defaults(self):
        from app.schemas.intelligence_agents import ResearchFinding

        f = ResearchFinding(statement="KYC is mandatory")
        assert f.confidence == 0.5
        assert f.sources == []

    def test_compliance_obligation_status_enum(self):
        from app.schemas.intelligence_agents import ComplianceObligationStatus

        assert ComplianceObligationStatus.NON_COMPLIANT.value == "non_compliant"

    def test_compliance_agent_result_has_required_fields(self):
        from app.schemas.intelligence_agents import ComplianceAgentResult

        r = ComplianceAgentResult(query="test", summary="ok")
        assert r.agent == "compliance"
        assert r.risk_level == "medium"

    def test_risk_scenario_kind_enum(self):
        from app.schemas.intelligence_agents import RiskScenarioKind

        assert RiskScenarioKind.STRESS.value == "stress"

    def test_risk_agent_result_has_required_fields(self):
        from app.schemas.intelligence_agents import RiskAgentResult

        r = RiskAgentResult(query="test", summary="done")
        assert r.agent == "risk"
        assert not r.drift_detected

    def test_risk_agent_request_defaults(self):
        from app.schemas.intelligence_agents import RiskAgentRequest

        req = RiskAgentRequest(query="valid risk query")
        assert req.horizon_days == 90
        assert req.include_scenarios

    def test_intelligence_agent_metrics_defaults(self):
        from app.schemas.intelligence_agents import IntelligenceAgentMetrics

        m = IntelligenceAgentMetrics()
        assert m.total_invocations == 0
        assert m.research.agent == "research"
        assert m.compliance.agent == "compliance"
        assert m.risk.agent == "risk"

    def test_agent_collaboration_defaults(self):
        from app.schemas.intelligence_agents import AgentCollaboration

        c = AgentCollaboration(
            from_agent="research", to_agent="compliance", request_kind="query"
        )
        assert c.shared_context_keys == []


# ══════════════════════════════════════════════════════════════════
# 8.3 — Audit Agent Schema Contracts (M9.7)
# ══════════════════════════════════════════════════════════════════


class TestAuditAgentSchemas:
    """M9.7 — Audit Agent schema contracts."""

    def test_audit_task_kind_enum(self):
        from app.schemas.audit_agent import AuditTaskKind

        assert AuditTaskKind.COMPLIANCE_VERIFICATION.value == "compliance_verification"

    def test_audit_violation_severity_enum(self):
        from app.schemas.audit_agent import AuditViolationSeverity

        assert AuditViolationSeverity.CRITICAL.value == "critical"

    def test_audit_agent_request_defaults(self):
        from app.schemas.audit_agent import AuditAgentRequest

        req = AuditAgentRequest(query="validate KYC compliance")
        assert req.task_kind.value == "compliance_verification"
        assert req.include_evidence
        assert req.max_violations == 50

    def test_audit_agent_result_has_required_fields(self):
        from app.schemas.audit_agent import AuditAgentResult, AuditTaskKind

        r = AuditAgentResult(
            query="test", task_kind=AuditTaskKind.COMPLIANCE_VERIFICATION
        )
        assert r.agent == "audit"
        assert r.audit_status.value == "unknown"

    def test_audit_evidence_item_defaults(self):
        from app.schemas.audit_agent import AuditEvidenceItem

        e = AuditEvidenceItem(title="evidence item")
        assert e.evidence_kind == "document"
        assert e.confidence == 0.5


# ══════════════════════════════════════════════════════════════════
# 8.4 — Orchestration Platform Schema Contracts (M9.8)
# ══════════════════════════════════════════════════════════════════


class TestOrchestrationPlatformSchemas:
    """M9.8 — Multi-Agent Orchestration Platform schema contracts."""

    def test_execution_mode_enum(self):
        from app.schemas.orchestration import ExecutionMode

        assert ExecutionMode.PARALLEL.value == "parallel"
        assert ExecutionMode.DYNAMIC.value == "dynamic"

    def test_workflow_status_enum(self):
        from app.schemas.orchestration import WorkflowStatus

        assert WorkflowStatus.PARTIALLY_SUCCEEDED.value == "partially_succeeded"

    def test_message_kind_enum(self):
        from app.schemas.orchestration import MessageKind

        assert MessageKind.CONTROL.value == "control"

    def test_agent_message_defaults(self):
        from app.schemas.orchestration import AgentMessage, MessageKind

        m = AgentMessage(from_agent="a", to_agent="b", kind=MessageKind.TASK)
        assert m.ttl_ms == 60_000
        assert m.payload == {}

    def test_shared_evidence_item_defaults(self):
        from app.schemas.orchestration import SharedEvidenceItem

        e = SharedEvidenceItem(producer="research", kind="citation", title="t")
        assert e.confidence == 0.5
        assert e.consumer == ""

    def test_shared_execution_context_defaults(self):
        from app.schemas.orchestration import SharedExecutionContext

        ctx = SharedExecutionContext()
        assert ctx.actor == "system"
        assert ctx.timeout_ms == 60_000

    def test_agent_execution_step_defaults(self):
        from app.schemas.orchestration import AgentExecutionStep

        s = AgentExecutionStep(agent_name="test", capability="x")
        assert s.depends_on == []
        assert s.max_retries == 0

    def test_orchestration_request_defaults(self):
        from app.schemas.orchestration import OrchestrationRequest

        req = OrchestrationRequest(query="KYC compliance check")
        assert req.mode.value == "sequential"
        assert req.consensus_threshold == 0.5

    def test_orchestration_result_defaults(self):
        from app.schemas.orchestration import (
            OrchestrationResult,
            ExecutionMode,
            AgentExecutionGraph,
            AgentExecutionStep,
        )

        graph = AgentExecutionGraph(
            steps=[AgentExecutionStep(agent_name="a", capability="x")]
        )
        r = OrchestrationResult(
            query="test", mode=ExecutionMode.SEQUENTIAL, execution_graph=graph
        )
        assert r.status.value == "succeeded"

    def test_agent_contribution_defaults(self):
        from app.schemas.orchestration import AgentContribution

        c = AgentContribution(agent_name="test")
        assert c.status == "succeeded"
        assert c.confidence == 0.5

    def test_workflow_definition_requires_name(self):
        from app.schemas.orchestration import (
            WorkflowDefinition,
            AgentExecutionGraph,
            AgentExecutionStep,
        )

        g = AgentExecutionGraph(
            steps=[AgentExecutionStep(agent_name="x", capability="y")]
        )
        d = WorkflowDefinition(name="my-workflow", graph=g)
        assert d.version == "1.0.0"

    def test_orchestration_metrics_summary_defaults(self):
        from app.schemas.orchestration import OrchestrationMetricsSummary

        m = OrchestrationMetricsSummary()
        assert m.total_executions == 0
        assert m.total_successful == 0


# ══════════════════════════════════════════════════════════════════
# 8.5 — Agent Analytics Schema Contracts (M9.9)
# ══════════════════════════════════════════════════════════════════


class TestAgentAnalyticsSchemas:
    """M9.9 — Agent Analytics Platform schema contracts."""

    def test_health_level_enum(self):
        from app.schemas.agent_analytics import HealthLevel

        assert HealthLevel.DEGRADED.value == "degraded"

    def test_agent_performance_defaults(self):
        from app.schemas.agent_analytics import AgentPerformance

        p = AgentPerformance(agent_name="research")
        assert p.health.value == "unknown"
        assert p.average_duration_ms == 0.0

    def test_latency_distribution_defaults(self):
        from app.schemas.agent_analytics import LatencyDistribution

        d = LatencyDistribution(agent_name="research")
        assert d.p95_ms == 0.0

    def test_leaderboard_entry_defaults(self):
        from app.schemas.agent_analytics import LeaderboardEntry

        e = LeaderboardEntry(agent_name="a")
        assert e.rank == 0
        assert e.score == 0.0

    def test_collaboration_stats_defaults(self):
        from app.schemas.agent_analytics import CollaborationStats

        s = CollaborationStats(from_agent="a", to_agent="b")
        assert s.count == 0

    def test_health_summary_defaults(self):
        from app.schemas.agent_analytics import HealthSummary

        h = HealthSummary()
        assert h.overall_health.value == "unknown"

    def test_agent_analytics_overview_defaults(self):
        from app.schemas.agent_analytics import AgentAnalyticsOverview

        o = AgentAnalyticsOverview()
        assert o.total_agents == 0
        assert o.total_invocations == 0

    def test_execution_summary_defaults(self):
        from app.schemas.agent_analytics import ExecutionSummary

        e = ExecutionSummary()
        assert e.status == "succeeded"
        assert e.mode == "sequential"

    def test_forecast_accuracy_defaults(self):
        from app.schemas.agent_analytics import ForecastAccuracy

        f = ForecastAccuracy(agent_name="risk")
        assert f.accuracy == 0.0

    def test_recommendation_accuracy_defaults(self):
        from app.schemas.agent_analytics import RecommendationAccuracy

        r = RecommendationAccuracy(agent_name="compliance")
        assert r.acceptance_rate == 0.0

    def test_cost_estimate_defaults(self):
        from app.schemas.agent_analytics import CostEstimate

        c = CostEstimate()
        assert c.currency == "USD"
        assert c.cost_per_invocation == 0.0


# ══════════════════════════════════════════════════════════════════
# 8.6 — Response Orchestrator Pipeline (M5.6) Validation
# ══════════════════════════════════════════════════════════════════


class TestResponseOrchestratorPipeline:
    """M5.6 — Response Orchestrator pipeline schema contracts."""

    def test_pipeline_step_enum(self):
        from app.schemas.orchestrator import PipelineStep

        assert PipelineStep.ANSWER_GENERATION.value == "answer_generation"

    def test_pipeline_status_enum(self):
        from app.schemas.orchestrator import PipelineStatus

        assert PipelineStatus.DEGRADED.value == "degraded"

    def test_orchestrator_request_enforces_min_chunks(self):
        from pydantic import ValidationError
        from app.schemas.orchestrator import OrchestratorRequest

        with pytest.raises(ValidationError):
            OrchestratorRequest(query="q", chunks=[])

    def test_orchestrator_request_enforces_min_query(self):
        from pydantic import ValidationError
        from app.schemas.orchestrator import OrchestratorRequest
        from app.schemas.answer_generation import RetrievedChunk

        chunk = RetrievedChunk(
            chunk_id="c1", document_id="d1", content="test", score=0.5
        )
        with pytest.raises(ValidationError):
            OrchestratorRequest(query="", chunks=[chunk])

    def test_step_result_defaults(self):
        from app.schemas.orchestrator import StepResult, PipelineStep, PipelineStatus

        sr = StepResult(step=PipelineStep.CITATION)
        assert sr.status == PipelineStatus.PENDING
        assert sr.latency_ms == 0.0

    def test_orchestrator_metadata_auto_generates_id(self):
        from app.schemas.orchestrator import OrchestratorMetadata

        m = OrchestratorMetadata()
        assert len(m.request_id) == 32

    def test_final_answer_response_constructs_with_all_required(self):
        from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorMetadata
        from app.schemas.answer_generation import AnswerSection
        from app.schemas.citation import AnnotatedAnswer, AnnotatedText
        from app.schemas.confidence import ConfidenceLevel
        from app.schemas.hallucination import HallucinationRiskLevel

        answer = AnswerSection(
            executive_summary="test",
            detailed_explanation="test detail",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        citations = AnnotatedAnswer(
            executive_summary=AnnotatedText(text="test", citations=[]),
            detailed_explanation=AnnotatedText(text="test", citations=[]),
            supporting_evidence=[],
            key_regulatory_references=[],
            references=[],
            citation_map={},
        )
        resp = FinalAnswerResponse(
            query="test",
            answer=answer,
            citations=citations,
            confidence_score=0.5,
            confidence_level=ConfidenceLevel.MEDIUM,
            faithfulness_score=0.5,
            hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            metadata=OrchestratorMetadata(),
        )
        assert resp.query == "test"
        assert resp.attribution_coverage_ratio == 0.0
        assert resp.latency_ms == 0.0

    def test_response_context_defaults(self):
        from app.schemas.orchestrator import ResponseContext

        ctx = ResponseContext(query="test", chunks=[])
        assert ctx.step_results == []
        assert ctx.source_attributions == []


# ══════════════════════════════════════════════════════════════════
# 8.7 — Cross-Orchestrator Integration
# ══════════════════════════════════════════════════════════════════


class TestCrossOrchestratorIntegration:
    """Integration between M5.6 Response Orchestrator and M9.8
    Multi-Agent Orchestration."""

    def test_orchestration_request_can_include_full_graph(self):
        from app.schemas.orchestration import (
            AgentExecutionGraph,
            AgentExecutionStep,
            OrchestrationRequest,
            ExecutionMode,
        )

        steps = [AgentExecutionStep(agent_name="a", capability="retrieval")]
        graph = AgentExecutionGraph(steps=steps)
        req = OrchestrationRequest(
            query="KYC", graph=graph, mode=ExecutionMode.PARALLEL
        )
        assert req.graph is not None
        assert len(req.graph.steps) == 1

    def test_shared_evidence_can_feed_into_citation(self):
        from app.schemas.orchestration import SharedEvidenceItem
        from app.schemas.citation import EvidenceChunk

        ev = SharedEvidenceItem(
            producer="research",
            kind="citation",
            title="evidence",
            content={"text": "KYC required."},
        )
        chunk = EvidenceChunk(
            chunk_id="ck1",
            document_id="d1",
            excerpt=ev.content["text"],
            page_number=1,
            section="sec",
        )
        assert chunk.excerpt == "KYC required."

    def test_final_answer_response_compatible_with_citation_coverage(self):
        from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorMetadata
        from app.schemas.answer_generation import AnswerSection
        from app.schemas.citation import AnnotatedAnswer, AnnotatedText
        from app.schemas.confidence import ConfidenceLevel
        from app.schemas.hallucination import HallucinationRiskLevel

        answer = AnswerSection(
            executive_summary="test",
            detailed_explanation="test",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        citations = AnnotatedAnswer(
            executive_summary=AnnotatedText(text="test", citations=[]),
            detailed_explanation=AnnotatedText(text="test", citations=[]),
            supporting_evidence=[],
            key_regulatory_references=[],
            references=[],
            citation_map={},
        )
        resp = FinalAnswerResponse(
            query="test",
            answer=answer,
            citations=citations,
            confidence_score=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            faithfulness_score=0.8,
            hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            source_attributions=[],
            metadata=OrchestratorMetadata(),
        )
        from app.services.evaluation import MetricsEngine

        engine = MetricsEngine()
        result = engine.citation_accuracy(resp)
        assert 0.0 <= result.score <= 1.0

    def test_agent_result_can_be_aggregated_into_coordinator_result(self):
        from app.schemas.agents import AgentResult, TaskStatus, CoordinatorPlan
        from app.services.agents import ResultAggregator

        agg = ResultAggregator()
        plan = CoordinatorPlan(query="test", steps=[], selected_agents=["a", "b"])
        r1 = AgentResult(
            agent_name="a", status=TaskStatus.SUCCEEDED, output={"summary": "ok"}
        )
        r2 = AgentResult(
            agent_name="b", status=TaskStatus.SUCCEEDED, output={"summary": "ok"}
        )
        final = agg.aggregate(plan, [r1, r2])
        assert final.status == TaskStatus.SUCCEEDED
        assert final.final_output["successful_count"] == 2

    def test_shared_evidence_store_cross_agent_lookup(self):
        from app.services.orchestration import SharedEvidenceStore
        from app.schemas.orchestration import SharedEvidenceItem

        store = SharedEvidenceStore()
        store.add(
            SharedEvidenceItem(
                producer="research", kind="citation", title="c1", consumer="compliance"
            )
        )
        store.add(
            SharedEvidenceItem(
                producer="compliance", kind="violation", title="v1", consumer="*"
            )
        )
        compliance_items = store.for_consumer("compliance")
        assert len(compliance_items) == 2
        research_items = store.for_consumer("research")
        assert len(research_items) == 1

    def test_message_bus_cross_agent_communication(self):
        from app.services.orchestration import AgentMessageBus
        from app.schemas.orchestration import AgentMessage, MessageKind

        bus = AgentMessageBus()
        messages = []
        bus.subscribe("compliance", lambda m: messages.append(m))
        bus.publish(
            AgentMessage(
                from_agent="research",
                to_agent="compliance",
                kind=MessageKind.EVIDENCE,
                payload={"finding": "KYC gap"},
            )
        )
        assert len(messages) == 1
        assert messages[0].payload["finding"] == "KYC gap"


# ══════════════════════════════════════════════════════════════════
# 8.8 — Edge Cases & Error Handling
# ══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases across the agent ecosystem."""

    def test_conflict_resolver_empty_input(self):
        from app.services.orchestration import ConflictResolver

        winner, conflicts = ConflictResolver.resolve([])
        assert winner is None
        assert conflicts == 0

    def test_consensus_builder_full_disagreement(self):
        from app.services.orchestration import ConsensusBuilder

        score = ConsensusBuilder.score([("yes", 0.5), ("no", 0.5)])
        assert score == 0.5

    def test_evidence_aggregator_empty(self):
        from app.services.orchestration import EvidenceAggregator

        merged = EvidenceAggregator.merge({})
        assert merged == []

    def test_result_synthesizer_single_contribution(self):
        from app.services.orchestration import ResultSynthesizer

        s = ResultSynthesizer()
        contrib = type(
            "C",
            (),
            {
                "agent_name": "a",
                "status": "succeeded",
                "summary": "ok",
                "output": {"key": "val"},
                "confidence": 0.8,
            },
        )()
        out, conf, cons, conflicts = s.synthesize("q", [contrib], [])
        assert out["agent_count"] == 1
        assert conf == 0.8

    def test_orchestrator_request_rejects_short_query(self):
        from pydantic import ValidationError
        from app.schemas.orchestration import OrchestrationRequest

        with pytest.raises(ValidationError):
            OrchestrationRequest(query="ab")

    def test_research_agent_request_rejects_short_query(self):
        from pydantic import ValidationError
        from app.schemas.intelligence_agents import ResearchAgentRequest

        with pytest.raises(ValidationError):
            ResearchAgentRequest(query="ab")

    def test_audit_agent_request_rejects_short_query(self):
        from pydantic import ValidationError
        from app.schemas.audit_agent import AuditAgentRequest

        with pytest.raises(ValidationError):
            AuditAgentRequest(query="ab")

    def test_agent_capability_rejects_empty_name(self):
        from pydantic import ValidationError
        from app.schemas.agents import AgentCapability, CapabilityKind

        with pytest.raises(ValidationError):
            AgentCapability(kind=CapabilityKind.OTHER, name="")

    def test_agent_metadata_rejects_empty_name(self):
        from pydantic import ValidationError
        from app.schemas.agents import AgentMetadata

        with pytest.raises(ValidationError):
            AgentMetadata(name="")

    def test_orchestration_request_rejects_high_consensus(self):
        from pydantic import ValidationError
        from app.schemas.orchestration import OrchestrationRequest

        with pytest.raises(ValidationError):
            OrchestrationRequest(query="test query", consensus_threshold=1.5)
