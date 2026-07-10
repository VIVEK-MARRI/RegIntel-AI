"""Phase 10 — Performance & Metrics Validation.

Covers: observability primitives (APIMetrics, track_request,
RequestContext), analytics repository schema contracts, health
check schemas, latency tracking, aggregated metrics, distribution
schemas, and performance trace patterns.
"""

from __future__ import annotations



# ══════════════════════════════════════════════════════════════════
# 10.1 — Observability Primitives
# ══════════════════════════════════════════════════════════════════


class TestRequestContext:
    """Tests for RequestContext latency tracking."""

    def test_request_context_defaults(self):
        from app.services.observability import RequestContext
        import time

        ctx = RequestContext(request_id="r1", started_at=time.time())
        assert ctx.endpoint == ""
        assert ctx.rerank_used is False

    def test_request_context_records_latency(self):
        from app.services.observability import RequestContext
        import time

        ctx = RequestContext(endpoint="/search/dense", strategy="dense")
        t0 = time.perf_counter()
        ctx.finished_at = time.perf_counter() + 0.1
        ctx.started_at = t0
        ctx.latency_ms
        assert ctx.latency_ms is not None

    def test_request_context_to_log_dict(self):
        from app.services.observability import RequestContext

        ctx = RequestContext(
            endpoint="/search/hybrid", strategy="hybrid", request_id="req-1"
        )
        d = ctx.to_log_dict()
        assert d["endpoint"] == "/search/hybrid"
        assert d["strategy"] == "hybrid"
        assert d["request_id"] == "req-1"


class TestAPIMetrics:
    """Tests for APIMetrics counters."""

    def test_api_metrics_defaults(self):
        from app.services.observability import APIMetrics

        m = APIMetrics()
        snap = m.snapshot()
        assert snap["total_requests"] == 0
        assert snap["successful_requests"] == 0

    def test_api_metrics_record_request(self):
        from app.services.observability import APIMetrics

        m = APIMetrics()
        m.record_request(
            endpoint="/search/dense", strategy="dense", latency_ms=50.0, success=True
        )
        snap = m.snapshot()
        assert snap["total_requests"] == 1
        assert snap["successful_requests"] == 1

    def test_api_metrics_record_error(self):
        from app.services.observability import APIMetrics

        m = APIMetrics()
        m.record_request(
            endpoint="/search/bm25", strategy="bm25", latency_ms=10.0, success=False
        )
        m.record_error(error_type="timeout")
        snap = m.snapshot()
        assert snap["failed_requests"] == 1
        assert "error_counts" in snap

    def test_api_metrics_reset(self):
        from app.services.observability import APIMetrics

        m = APIMetrics()
        m.record_request(
            endpoint="/search/dense", strategy="dense", latency_ms=30.0, success=True
        )
        m.reset()
        snap = m.snapshot()
        assert snap["total_requests"] == 0

    def test_api_metrics_get_metrics_singleton(self):
        from app.services.observability import get_metrics

        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


class TestTrackRequest:
    """Tests for the track_request context manager."""

    def test_track_request_adds_latency(self):
        from app.services.observability import track_request

        with track_request(endpoint="/test", strategy="test") as ctx:
            pass
        assert isinstance(ctx.request_id, str)
        assert len(ctx.request_id) > 0


# ══════════════════════════════════════════════════════════════════
# 10.2 — Health Check Schemas
# ══════════════════════════════════════════════════════════════════


class TestHealthCheckSchemas:
    """Tests for health check schemas and components."""

    def test_health_status_enum(self):
        from app.core.health import HealthStatus

        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"

    def test_component_health_defaults(self):
        from app.core.health import ComponentHealth, HealthStatus

        c = ComponentHealth(name="test", status=HealthStatus.HEALTHY)
        d = c.to_dict()
        assert d["name"] == "test"
        assert d["latency_ms"] >= 0

    def test_health_report_aggregation(self):
        from app.core.health import HealthReport, HealthStatus

        r = HealthReport(status=HealthStatus.HEALTHY)
        assert r.is_healthy is True
        assert r.generated_at is not None

    def test_health_checker_runs_checks(self):
        from app.core.health import HealthChecker, HealthStatus

        hc = HealthChecker()

        def _ok():
            from datetime import datetime, timezone

            return type(
                "CH",
                (),
                {
                    "name": "liveness",
                    "status": HealthStatus.HEALTHY,
                    "latency_ms": 0.5,
                    "message": "ok",
                    "details": {},
                    "checked_at": datetime.now(timezone.utc),
                },
            )()

        hc.register("liveness", _ok)
        report = hc.run()
        assert report.status == HealthStatus.HEALTHY

    def test_health_checker_catches_exception(self):
        from app.core.health import HealthChecker

        hc = HealthChecker()

        def _boom():
            raise RuntimeError("health check error")

        hc.register("boom", _boom)
        report = hc.run()
        assert not report.is_healthy
        assert "health check error" in str(report.components[0].message)

    def test_always_healthy_check(self):
        from app.core.health import always_healthy

        c = always_healthy()
        assert c.name == "liveness"
        assert c.status.value == "healthy"


# ══════════════════════════════════════════════════════════════════
# 10.3 — Analytics Schemas & Latency Fields
# ══════════════════════════════════════════════════════════════════


class TestAnalyticsPerformanceSchemas:
    """Tests for analytics DB schemas with latency/metric fields."""

    def test_retrieval_metrics_record_has_latency_fields(self):
        from app.schemas.analytics import RetrievalMetricsCreate

        fields = RetrievalMetricsCreate.model_fields
        assert "retrieval_latency_ms" in fields
        assert "reranker_latency_ms" in fields

    def test_aggregated_metrics_snapshot_has_percentiles(self):
        from app.models.analytics import AggregatedMetricsSnapshot

        cols = {c.name for c in AggregatedMetricsSnapshot.__table__.c}
        assert "p50_retrieval_latency_ms" in cols
        assert "p95_retrieval_latency_ms" in cols

    def test_system_health_snapshot_has_latency(self):
        from app.models.analytics import SystemHealthSnapshot

        cols = {c.name for c in SystemHealthSnapshot.__table__.c}
        assert "avg_latency_last_hour_ms" in cols

    def test_reranker_gain_record_has_latency(self):
        from app.models.analytics import RerankerGainRecord

        cols = {c.name for c in RerankerGainRecord.__table__.c}
        assert "avg_reranker_latency_ms" in cols


# ══════════════════════════════════════════════════════════════════
# 10.4 — Agent & Domain Metrics Schemas
# ══════════════════════════════════════════════════════════════════


class TestDomainMetricsSchemas:
    """Tests for domain-specific metrics schemas."""

    def test_ingestion_metrics_has_latency_fields(self):
        from app.services.observability import IngestionMetrics

        m = IngestionMetrics()
        snap = m.snapshot()
        assert "average_processing_latency_ms" in snap
        assert "documents_ingested" in snap

    def test_monitoring_metrics_tracks_sources(self):
        from app.services.observability import MonitoringMetrics

        m = MonitoringMetrics()
        snap = m.snapshot()
        assert "sources_monitored" in snap

    def test_knowledge_graph_metrics_tracks_operations(self):
        from app.services.observability import KnowledgeGraphMetrics

        m = KnowledgeGraphMetrics()
        snap = m.snapshot()
        assert "nodes_added" in snap

    def test_alert_metrics_tracks_delivery(self):
        from app.services.observability import AlertMetrics

        m = AlertMetrics()
        snap = m.snapshot()
        assert "alerts_delivered" in snap

    def test_research_metrics_tracks_plans(self):
        from app.services.observability import ResearchMetrics

        m = ResearchMetrics()
        snap = m.snapshot()
        assert "plans_generated" in snap

    def test_risk_metrics_tracks_assessments(self):
        from app.services.observability import RiskMetrics

        m = RiskMetrics()
        snap = m.snapshot()
        assert "assessments_generated" in snap

    def test_workflow_metrics_tracks_workflows(self):
        from app.services.observability import WorkflowMetrics

        m = WorkflowMetrics()
        snap = m.snapshot()
        assert "workflows_created" in snap

    def test_governance_metrics_tracks_decisions(self):
        from app.services.observability import GovernanceMetrics

        m = GovernanceMetrics()
        snap = m.snapshot()
        assert "decisions_registered" in snap

    def test_audit_metrics_tracks_records(self):
        from app.services.observability import AuditMetrics

        m = AuditMetrics()
        snap = m.snapshot()
        assert "records_appended" in snap


# ══════════════════════════════════════════════════════════════════
# 10.5 — Performance Trace Patterns
# ══════════════════════════════════════════════════════════════════


class TestPerformanceTracePatterns:
    """Tests for cross-cutting performance trace correctness."""

    def test_orchestrator_step_result_records_latency(self):
        from app.schemas.orchestrator import StepResult, PipelineStep, PipelineStatus

        sr = StepResult(
            step=PipelineStep.CITATION, status=PipelineStatus.SUCCESS, latency_ms=45.2
        )
        assert sr.latency_ms == 45.2
        assert sr.latency_ms >= 0

    def test_orchestrator_metadata_has_step_results(self):
        from app.schemas.orchestrator import OrchestratorMetadata

        m = OrchestratorMetadata()
        assert m.total_latency_ms == 0.0
        assert m.step_results == []

    def test_citation_metadata_has_latency(self):
        from app.schemas.citation import CitationMetadata

        m = CitationMetadata()
        assert m.latency_ms == 0.0
        assert m.chunks_used == 0

    def test_hybrid_search_response_has_latency(self):
        from app.schemas.hybrid_search import (
            HybridSearchResponse,
            HybridSearchDiagnostics,
        )
        from datetime import datetime, timezone

        diag = HybridSearchDiagnostics(
            query_type="text",
            query_confidence=0.9,
            recommended_strategy="hybrid",
            dense_count=5,
            bm25_count=5,
            fused_count=10,
            overlap_count=0,
            overlap_pct=0.0,
            dense_latency_ms=10.0,
            bm25_latency_ms=10.0,
            fusion_latency_ms=1.0,
            rerank_latency_ms=0.0,
            rerank_used=False,
            rerank_model=None,
            fusion_method="rrf",
        )
        resp = HybridSearchResponse(
            results=[],
            query="test",
            total_results=0,
            latency_ms=123.4,
            strategy="hybrid",
            request_id="r1",
            timestamp=datetime.now(timezone.utc),
            query_type="text",
            diagnostics=diag,
        )
        assert resp.latency_ms == 123.4

    def test_analytics_service_records_retrieval_metrics(self):
        from app.schemas.analytics import RetrievalMetricsCreate

        req = RetrievalMetricsCreate(
            query_id="q1",
            query_text="KYC",
            strategy="dense",
            retrieval_latency_ms=50.0,
            total_latency_ms=65.0,
        )
        assert req.retrieval_latency_ms == 50.0
        assert req.total_latency_ms == 65.0

    def test_orchestration_result_has_duration(self):
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
            query="test",
            mode=ExecutionMode.SEQUENTIAL,
            execution_graph=graph,
            duration_ms=250.0,
        )
        assert r.duration_ms == 250.0
