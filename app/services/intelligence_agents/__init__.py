"""Module 9.4-9.6 — Intelligence Agent Layer.

Specialised domain agents that build on top of the Module 9 multi-agent
framework. Each agent REUSES the existing platform services; this
module does NOT re-implement retrieval, knowledge graph, compliance
risk, recommendation, forecasting, governance, monitoring or impact
analysis.

Public surface
--------------
* ``ResearchAgent``            — autonomous regulatory research
* ``ComplianceAgent``          — compliance intelligence & recommendations
* ``RiskIntelligenceAgent``    — current & future risk analysis
* Sub-components (planners, reasoners, analyzers, report generators)
* ``IntelligenceAgentFactory`` — DI wiring of all three + collaborators
* ``CoordinatorDriver``        — multi-agent coordination using the
  existing :class:`CoordinatorAgent`
* ``IntelligenceAgentService`` — DI facade exposing run/health/metrics
* ``build_default_intelligence_agent_service``
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.schemas.agents import (
    AgentCapability,
    AgentContext,
    AgentHealthCheck,
    AgentMetadata,
    AgentRegistrationRequest,
    AgentResult,
    AgentTask,
    CapabilityKind,
    CoordinatorRequest,
    TaskStatus,
)
from app.schemas.intelligence_agents import (
    AgentCollaboration,
    AgentMetricsSummary,
    ComplianceActionItem,
    ComplianceAgentHealth,
    ComplianceAgentRequest,
    ComplianceAgentResult,
    ComplianceGapDetail,
    ComplianceObligation,
    ComplianceObligationStatus,
    IntelligenceAgentMetrics,
    ResearchAgentHealth,
    ResearchAgentRequest,
    ResearchAgentResult,
    ResearchFinding,
    ResearchMode,
    ResearchPlanStep,
    RiskAgentHealth,
    RiskAgentRequest,
    RiskAgentResult,
    RiskProjection,
    RiskScenario,
    RiskScenarioKind,
)
from app.schemas.recommendations import RecommendationRequest
from app.services.agents import BaseAgent
from app.services.observability import (
    get_intelligence_agent_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Shared utilities
# ═══════════════════════════════════════════════════════════════════════


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_KYWS = (
    "kyc",
    "know your customer",
    "customer identification",
    "cdd",
    "edd",
    "customer due diligence",
)


def _now() -> float:
    return time.time()


def _tokenize_confidence(signal: float, *, baseline: float = 0.5) -> float:
    """Clamp a value into [0, 1] to use as a confidence signal."""
    try:
        v = float(signal)
    except (TypeError, ValueError):
        return baseline
    return max(0.0, min(1.0, v))


# ═══════════════════════════════════════════════════════════════════════
# 9.4 — Research Agent
# ═══════════════════════════════════════════════════════════════════════


class ResearchAgentPlanner:
    """Builds a deterministic research plan for the agent.

    Reuses the existing :class:`ResearchPlanner` (Module 7.7) for the
    heavy lifting; this wrapper just transcribes the plan into the
    agent-native :class:`ResearchPlanStep` shape and augments it with
    knowledge-graph steps when the mode asks for it.
    """

    def plan(self, request: ResearchAgentRequest) -> List[ResearchPlanStep]:
        # Defer import to avoid circulars at module import time
        from app.schemas.research import ResearchKind, ResearchRequest
        from app.services.research import ResearchPlanner

        # Map ResearchMode → ResearchKind (default to GENERAL)
        mode_to_kind = {
            ResearchMode.MULTI_HOP: ResearchKind.MULTI_HOP,
            ResearchMode.CROSS_DOCUMENT: ResearchKind.CROSS_DOCUMENT,
            ResearchMode.KNOWLEDGE_GRAPH: ResearchKind.GENERAL,
            ResearchMode.TIMELINE: ResearchKind.TIMELINE,
            ResearchMode.COMPARATIVE: ResearchKind.COMPARATIVE,
            ResearchMode.TREND: ResearchKind.GENERAL,
            ResearchMode.HISTORICAL: ResearchKind.TIMELINE,
            ResearchMode.GENERAL: ResearchKind.GENERAL,
        }
        planner = ResearchPlanner()
        research_req = ResearchRequest(
            query=request.query,
            kind=mode_to_kind.get(request.mode, ResearchKind.GENERAL),
            max_steps=request.max_steps,
        )
        plan = planner.plan(research_req)
        steps: List[ResearchPlanStep] = []
        for s in plan.steps:
            cap = {
                "plan": "reasoning",
                "retrieve": "retrieval",
                "compare": "reasoning",
                "reason": "reasoning",
                "summarize": "summarization",
            }.get(s.step_type.value, "retrieval")
            steps.append(
                ResearchPlanStep(
                    action=s.step_type.value,
                    description=s.description,
                    capability=cap,
                    inputs=dict(s.inputs),
                )
            )
        # Append a knowledge-graph exploration step when relevant
        if request.mode in (
            ResearchMode.KNOWLEDGE_GRAPH,
            ResearchMode.CROSS_DOCUMENT,
            ResearchMode.GENERAL,
        ):
            steps.append(
                ResearchPlanStep(
                    action="kg_explore",
                    description=(
                        "Traverse knowledge graph for entities mentioned "
                        "in the query"
                    ),
                    capability="knowledge_graph",
                    inputs={"query": request.query},
                )
            )
        if request.mode in (
            ResearchMode.TIMELINE,
            ResearchMode.HISTORICAL,
        ):
            years = _YEAR_RE.findall(request.query)
            steps.append(
                ResearchPlanStep(
                    action="timeline_synth",
                    description="Synthesise chronological timeline",
                    capability="reasoning",
                    inputs={"years": years},
                )
            )
        return steps


class ResearchAgentExecutor:
    """Executes the planned steps, reusing research + KG services."""

    def __init__(
        self,
        *,
        research_service: Any = None,
        knowledge_graph_service: Any = None,
    ) -> None:
        self.research_service = research_service
        self.knowledge_graph_service = knowledge_graph_service

    def execute(
        self,
        request: ResearchAgentRequest,
        steps: List[ResearchPlanStep],
    ) -> Tuple[List[ResearchPlanStep], List[ResearchFinding], List[Dict[str, Any]], List[Dict[str, Any]]]:
        from app.schemas.research import ResearchRequest

        executed: List[ResearchPlanStep] = []
        citations: List[Dict[str, Any]] = []
        kg_insights: List[Dict[str, Any]] = []
        timeline: List[Dict[str, Any]] = []
        findings: List[ResearchFinding] = []

        # 1) Run the research platform
        report = None
        if self.research_service is not None:
            try:
                rr = ResearchRequest(
                    query=request.query,
                    context=request.context.get("research_context", {}),
                    max_steps=request.max_steps,
                )
                start = _now()
                report = self.research_service.run(rr, top_k=request.top_k)
                duration = (_now() - start) * 1000.0
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Research service failed: %s", exc
                )
                report = None
                duration = 0.0
            # Mark retrieve / compare / reason / summarise steps
            for s in steps:
                if s.action in {"plan", "retrieve", "compare", "reason", "summarize"}:
                    s.started_at = _now()
                    s.outputs = {
                        "step_kind": s.action,
                        "duration_ms": round(duration, 3) if s.action == "retrieve" else 0.0,
                    }
                    s.duration_ms = s.outputs["duration_ms"]
                    s.finished_at = _now()
                    executed.append(s)
        # If no research service, still record plan steps as completed
        for s in steps:
            if s not in executed and s.action in {
                "plan",
                "retrieve",
                "compare",
                "reason",
                "summarize",
            }:
                s.started_at = _now()
                s.outputs = {"step_kind": s.action, "no_service": True}
                s.duration_ms = 0.0
                s.finished_at = _now()
                executed.append(s)

        # 2) Collect citations from report
        if report is not None:
            for c in report.citations:
                citations.append(
                    {
                        "citation_id": c.citation_id,
                        "source": c.source.value,
                        "title": c.title,
                        "reference": c.reference,
                        "url": c.url,
                        "score": c.score,
                    }
                )
            for evt in report.timeline:
                timeline.append(
                    {
                        "title": evt.get("title", ""),
                        "date": evt.get("date"),
                        "id": evt.get("id"),
                    }
                )
            # Build findings from citations
            for c in report.citations[:5]:
                findings.append(
                    ResearchFinding(
                        statement=f"Referenced: {c.title}",
                        confidence=_tokenize_confidence(c.score, baseline=0.6),
                        sources=[c.source.value],
                        citation_ids=[c.citation_id],
                    )
                )
            if not findings:
                findings.append(
                    ResearchFinding(
                        statement=(
                            f"Research run produced {len(report.citations)} "
                            f"citations and {len(report.steps)} steps."
                        ),
                        confidence=0.6,
                    )
                )

        # 3) Knowledge graph exploration step
        for s in steps:
            if s.action == "kg_explore":
                s.started_at = _now()
                if self.knowledge_graph_service is not None:
                    try:
                        nodes, rels = self.knowledge_graph_service.list_all()
                        # Pick nodes whose name appears in the query
                        query_tokens = {
                            t for t in re.findall(r"\w+", request.query.lower()) if len(t) > 3
                        }
                        hits = [
                            {
                                "node_id": n.node_id,
                                "name": n.name,
                                "entity_type": n.entity_type.value,
                                "score": sum(
                                    1 for tok in query_tokens if tok in n.name.lower()
                                ),
                            }
                            for n in nodes
                        ]
                        hits = [h for h in hits if h["score"] > 0]
                        hits.sort(key=lambda h: h["score"], reverse=True)
                        s.outputs = {
                            "kg_hits": hits[:5],
                            "total_nodes": len(nodes),
                            "total_relationships": len(rels),
                        }
                        kg_insights.extend(hits[:5])
                    except Exception as exc:  # pragma: no cover
                        s.outputs = {"error": str(exc)}
                else:
                    s.outputs = {"kg_hits": [], "no_service": True}
                s.duration_ms = (_now() - s.started_at) * 1000.0
                s.finished_at = _now()
                executed.append(s)
                if s.outputs.get("kg_hits"):
                    findings.append(
                        ResearchFinding(
                            statement=(
                                f"Knowledge graph surfaced {len(s.outputs['kg_hits'])} "
                                f"related entity nodes."
                            ),
                            confidence=0.7,
                        )
                    )
                break

        # 4) Timeline synthesis step
        for s in steps:
            if s.action == "timeline_synth":
                s.started_at = _now()
                years = s.inputs.get("years", [])
                s.outputs = {
                    "year_count": len(years),
                    "synthesised_events": timeline,
                }
                s.duration_ms = (_now() - s.started_at) * 1000.0
                s.finished_at = _now()
                executed.append(s)
                if years:
                    findings.append(
                        ResearchFinding(
                            statement=(
                                f"Timeline covers {len(years)} time anchor(s)."
                            ),
                            confidence=0.65,
                        )
                    )
                break

        return executed, findings, citations + kg_insights, timeline


class ResearchAgentReasoner:
    """Synthesises a coherent summary and confidence score from findings."""

    def reason(
        self,
        query: str,
        findings: List[ResearchFinding],
        citations: List[Dict[str, Any]],
        plan: List[ResearchPlanStep],
    ) -> Tuple[str, float]:
        if not findings:
            summary = (
                f"No structured findings produced for query {query!r}."
            )
            return summary, 0.3
        # Average confidence
        avg = sum(f.confidence for f in findings) / max(1, len(findings))
        n_cit = len(citations)
        n_steps = len(plan)
        summary = (
            f"Research synthesis for {query!r}: {len(findings)} finding(s), "
            f"{n_cit} citation(s), {n_steps} step(s) executed."
        )
        return summary, _tokenize_confidence(avg, baseline=0.5)


class ResearchAgentReportGenerator:
    """Composes the final ResearchAgentResult from the sub-components."""

    def build(
        self,
        request: ResearchAgentRequest,
        plan: List[ResearchPlanStep],
        findings: List[ResearchFinding],
        citations: List[Dict[str, Any]],
        timeline: List[Dict[str, Any]],
        summary: str,
        confidence: float,
        agent_id: str,
        duration_ms: float,
    ) -> ResearchAgentResult:
        comparisons: List[Dict[str, Any]] = []
        if request.mode == ResearchMode.COMPARATIVE and citations:
            comparisons = [
                {"citation_id": c.get("citation_id"), "title": c.get("title")}
                for c in citations
            ]
        return ResearchAgentResult(
            agent_id=agent_id,
            query=request.query,
            mode=request.mode,
            summary=summary,
            findings=findings,
            plan=plan,
            citations=citations,
            knowledge_graph_insights=[
                c for c in citations if c.get("source") == "knowledge_graph"
            ],
            timeline=timeline,
            comparisons=comparisons,
            confidence=confidence,
            duration_ms=round(duration_ms, 3),
            started_at=_now() - (duration_ms / 1000.0),
            completed_at=_now(),
            metadata={
                "mode": request.mode.value,
                "topics": request.topics,
                "document_ids": request.document_ids,
            },
        )


class ResearchAgent(BaseAgent):
    """Autonomous regulatory research agent (Module 9.4)."""

    def __init__(
        self,
        metadata: AgentMetadata,
        *,
        research_service: Any = None,
        knowledge_graph_service: Any = None,
    ) -> None:
        super().__init__(metadata)
        self._planner = ResearchAgentPlanner()
        self._executor = ResearchAgentExecutor(
            research_service=research_service,
            knowledge_graph_service=knowledge_graph_service,
        )
        self._reasoner = ResearchAgentReasoner()
        self._reporter = ResearchAgentReportGenerator()
        self._research_service = research_service
        self._knowledge_graph_service = knowledge_graph_service

    # ── public attributes used by cross-agent collaboration ──
    @property
    def research_service(self) -> Any:
        return self._research_service

    @property
    def knowledge_graph_service(self) -> Any:
        return self._knowledge_graph_service

    async def execute(self, task: AgentTask) -> AgentResult:
        start = _now()
        try:
            request = ResearchAgentRequest(**task.input)
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=f"invalid request: {exc}",
                started_at=start,
                completed_at=_now(),
                duration_ms=0.0,
            )
        try:
            with track_request(
                endpoint="/api/v1/agents/research/run",
                strategy="research_agent",
            ):
                plan = self._planner.plan(request)
                plan, findings, citations, timeline = self._executor.execute(
                    request, plan
                )
                summary, confidence = self._reasoner.reason(
                    request.query, findings, citations, plan
                )
                duration = (_now() - start) * 1000.0
                result = self._reporter.build(
                    request=request,
                    plan=plan,
                    findings=findings,
                    citations=citations,
                    timeline=timeline,
                    summary=summary,
                    confidence=confidence,
                    agent_id=self.agent_id,
                    duration_ms=duration,
                )
            get_intelligence_agent_metrics().record_research(
                duration_ms=duration,
                confidence=confidence,
                success=True,
                mode=request.mode.value,
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.SUCCEEDED,
                output=result.model_dump(mode="json"),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )
        except Exception as exc:  # pragma: no cover
            duration = (_now() - start) * 1000.0
            get_intelligence_agent_metrics().record_research(
                duration_ms=duration,
                confidence=0.0,
                success=False,
                error=str(exc),
                mode=request.mode.value if "request" in locals() else "general",
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=str(exc),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )

    def health(self) -> AgentHealthCheck:
        h = super().health()
        # Augment with research-specific last error from metrics
        metrics = get_intelligence_agent_metrics()
        if metrics.research_last_error:
            h.last_error = metrics.research_last_error
        return h


# ═══════════════════════════════════════════════════════════════════════
# 9.5 — Compliance Agent
# ═══════════════════════════════════════════════════════════════════════


class ComplianceAnalyzer:
    """Detects compliance gaps and obligations from existing assessments."""

    _KEYWORD_OBLIGATIONS = (
        ("kyc_renewal", "KYC renewal cadence must be enforced", "kyc"),
        ("incident_reporting", "Cyber incidents must be reported within 6h", "cyber_security"),
        ("data_localisation", "Customer data must be stored within India", "data_privacy"),
        ("capital_adequacy", "Capital adequacy ratio to be maintained", "capital_adequacy"),
        ("suspicious_transaction_reporting", "STRs must be filed promptly", "aml"),
        ("grievance_redressal", "Customer grievance acknowledgement within 3 days", "customer_protection"),
        ("outsourcing_due_diligence", "Vendor due-diligence required for outsourcing", "outsourcing"),
    )

    def __init__(
        self,
        *,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
        governance_service: Any = None,
        impact_analysis_service: Any = None,
        knowledge_graph_service: Any = None,
    ) -> None:
        self.compliance_risk_service = compliance_risk_service
        self.recommendation_service = recommendation_service
        self.governance_service = governance_service
        self.impact_analysis_service = impact_analysis_service
        self.knowledge_graph_service = knowledge_graph_service

    def analyze(
        self,
        request: ComplianceAgentRequest,
        assessment: Optional[Any],
    ) -> Tuple[
        List[ComplianceObligation],
        List[ComplianceGapDetail],
        List[str],
        List[Dict[str, Any]],
    ]:
        obligations: List[ComplianceObligation] = []
        gaps: List[ComplianceGapDetail] = []
        affected_areas: List[str] = []
        policy_evaluations: List[Dict[str, Any]] = []

        # 1) Pull from the risk assessment
        if assessment is not None:
            for area in getattr(assessment, "affected_areas", []) or []:
                area_name = (
                    area.area.value
                    if hasattr(area, "area")
                    else str(area)
                )
                if area_name not in affected_areas:
                    affected_areas.append(area_name)
            for g in getattr(assessment, "compliance_gaps", []) or []:
                # M8.1 ComplianceGap uses area/severity/description; fall back
                # gracefully if any field is missing.
                title = getattr(g, "description", None) or "Compliance gap"
                gaps.append(
                    ComplianceGapDetail(
                        title=title,
                        description=getattr(g, "description", ""),
                        risk_level=str(
                            getattr(g, "severity", "medium").value
                            if hasattr(getattr(g, "severity", None), "value")
                            else getattr(g, "severity", "medium")
                        ),
                        affected_areas=[
                            (
                                getattr(g, "area", "other").value
                                if hasattr(getattr(g, "area", None), "value")
                                else str(getattr(g, "area", "other"))
                            )
                        ],
                        root_cause=getattr(g, "regulatory_basis", ""),
                    )
                )
        else:
            # Use the keyword table to seed obligations
            for oid, title, area in self._KEYWORD_OBLIGATIONS:
                obligations.append(
                    ComplianceObligation(
                        title=title,
                        source="regulatory_baseline",
                        description=(
                            f"Baseline obligation inferred from keyword {area}."
                        ),
                        status=ComplianceObligationStatus.PENDING,
                        affected_areas=[area],
                    )
                )
                if area not in affected_areas:
                    affected_areas.append(area)

        # 2) Add explicit obligations inferred from focus_areas
        for fa in request.focus_areas:
            obligations.append(
                ComplianceObligation(
                    title=f"Address focus area: {fa}",
                    source="agent_focus",
                    status=ComplianceObligationStatus.PENDING,
                    affected_areas=[fa],
                )
            )
            if fa not in affected_areas:
                affected_areas.append(fa)

        # 3) Evaluate governance policies
        if self.governance_service is not None and assessment is not None:
            try:
                result = self.governance_service.check(
                    decision_type="compliance_assessment",
                    model_id="compliance-agent",
                    confidence=1.0 - getattr(assessment, "risk_score", 0.0) * 0.3,
                    risk_level=getattr(assessment, "risk_level", None),
                )
                policy_evaluations.append(
                    {
                        "compliant": result.compliant
                        if hasattr(result, "compliant")
                        else True,
                        "violation_count": len(
                            getattr(result, "violations", []) or []
                        ),
                        "rules_evaluated": len(
                            getattr(result, "rules_evaluated", []) or []
                        ),
                    }
                )
                for v in getattr(result, "violations", []) or []:
                    gaps.append(
                        ComplianceGapDetail(
                            title=getattr(v, "message", "policy_violation"),
                            description=getattr(v, "message", ""),
                            risk_level=str(
                                getattr(v, "severity", "medium")
                            ),
                            affected_areas=[getattr(assessment, "document_id", "document")],
                            root_cause="policy",
                        )
                    )
            except Exception as exc:  # pragma: no cover
                policy_evaluations.append({"error": str(exc)})

        # 4) Trim to max_gaps
        if len(gaps) > request.max_gaps:
            gaps = gaps[: request.max_gaps]

        return obligations, gaps, affected_areas, policy_evaluations


class ComplianceReasoner:
    """Assigns risk_level / risk_score to the compliance assessment."""

    def reason(
        self,
        gaps: List[ComplianceGapDetail],
        assessment: Optional[Any],
    ) -> Tuple[str, float]:
        if assessment is not None:
            return (
                str(getattr(assessment, "risk_level", "medium").value)
                if hasattr(getattr(assessment, "risk_level", None), "value")
                else str(getattr(assessment, "risk_level", "medium")),
                float(getattr(assessment, "risk_score", 0.0)),
            )
        if not gaps:
            return "low", 0.2
        level_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        score = max(level_rank.get(g.risk_level, 2) for g in gaps) / 4.0
        level = max(gaps, key=lambda g: level_rank.get(g.risk_level, 2)).risk_level
        return level, score


class ComplianceRecommendationGenerator:
    """Builds remediation action items.

    Reuses the existing :class:`RecommendationService` when a risk
    assessment is available; otherwise builds actions from the gap
    list directly.
    """

    _PRIORITY_DAYS = {
        "critical": 7,
        "high": 14,
        "medium": 30,
        "low": 60,
    }

    def __init__(self, recommendation_service: Any = None) -> None:
        self.recommendation_service = recommendation_service

    def generate(
        self,
        request: ComplianceAgentRequest,
        gaps: List[ComplianceGapDetail],
    ) -> Tuple[List[ComplianceActionItem], List[str]]:
        actions: List[ComplianceActionItem] = []
        rec_ids: List[str] = []
        # 1) Try reuse via RecommendationService
        if (
            self.recommendation_service is not None
            and request.include_recommendations
            and (request.risk_assessment_id or request.diff_id or request.impact_report_id)
        ):
            try:
                rr = RecommendationRequest(
                    document_id=request.document_id,
                    diff_id=request.diff_id,
                    risk_assessment_id=request.risk_assessment_id,
                    max_recommendations=min(5, max(1, len(gaps) or 1)),
                )
                recs = self.recommendation_service.generate(rr)
                for r in recs:
                    rec_ids.append(r.recommendation_id)
                    actions.append(
                        ComplianceActionItem(
                            title=r.title,
                            description=r.description,
                            priority=str(r.priority.value)
                            if hasattr(r.priority, "value")
                            else str(r.priority),
                            affected_areas=[
                                a.area.value
                                if hasattr(a, "area") and hasattr(a.area, "value")
                                else str(a)
                                for a in (r.affected_areas or [])
                            ]
                            or ["compliance"],
                            target_completion_days=self._PRIORITY_DAYS.get(
                                str(r.priority.value)
                                if hasattr(r.priority, "value")
                                else "medium",
                                30,
                            ),
                            recommendation_id=r.recommendation_id,
                        )
                    )
                get_intelligence_agent_metrics().record_recommendation_generated(
                    len(recs)
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Recommendation service failed: %s", exc
                )
        # 2) Build actions from gaps directly (always)
        for g in gaps:
            actions.append(
                ComplianceActionItem(
                    title=f"Remediate: {g.title}",
                    description=g.description or g.title,
                    priority=g.risk_level,
                    affected_areas=g.affected_areas or ["compliance"],
                    target_completion_days=self._PRIORITY_DAYS.get(
                        g.risk_level, 30
                    ),
                    addresses_gap_ids=[g.gap_id],
                )
            )
        return actions, rec_ids


class ComplianceReportBuilder:
    """Final assembly of the compliance agent result."""

    def build(
        self,
        request: ComplianceAgentRequest,
        obligations: List[ComplianceObligation],
        gaps: List[ComplianceGapDetail],
        actions: List[ComplianceActionItem],
        affected_areas: List[str],
        policy_evaluations: List[Dict[str, Any]],
        risk_level: str,
        risk_score: float,
        confidence: float,
        rec_ids: List[str],
        agent_id: str,
        duration_ms: float,
    ) -> ComplianceAgentResult:
        summary = (
            f"Compliance assessment: {len(gaps)} gap(s), "
            f"{len(obligations)} obligation(s), "
            f"{len(actions)} action(s); risk={risk_level} "
            f"(score={risk_score:.2f})."
        )
        return ComplianceAgentResult(
            agent_id=agent_id,
            query=request.query,
            summary=summary,
            risk_level=risk_level,
            risk_score=round(risk_score, 4),
            obligations=obligations,
            gaps=gaps,
            actions=actions,
            policy_evaluations=policy_evaluations,
            affected_areas=affected_areas,
            recommendation_ids=rec_ids,
            confidence=confidence,
            duration_ms=round(duration_ms, 3),
            started_at=_now() - (duration_ms / 1000.0),
            completed_at=_now(),
            metadata={
                "include_recommendations": request.include_recommendations,
                "focus_areas": request.focus_areas,
            },
        )


class ComplianceAgent(BaseAgent):
    """Compliance intelligence agent (Module 9.5)."""

    def __init__(
        self,
        metadata: AgentMetadata,
        *,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
        governance_service: Any = None,
        impact_analysis_service: Any = None,
        knowledge_graph_service: Any = None,
    ) -> None:
        super().__init__(metadata)
        self._analyzer = ComplianceAnalyzer(
            compliance_risk_service=compliance_risk_service,
            recommendation_service=recommendation_service,
            governance_service=governance_service,
            impact_analysis_service=impact_analysis_service,
            knowledge_graph_service=knowledge_graph_service,
        )
        self._reasoner = ComplianceReasoner()
        self._action_gen = ComplianceRecommendationGenerator(
            recommendation_service=recommendation_service
        )
        self._reporter = ComplianceReportBuilder()
        self._compliance_risk_service = compliance_risk_service
        self._recommendation_service = recommendation_service
        self._governance_service = governance_service
        self._knowledge_graph_service = knowledge_graph_service

    @property
    def compliance_risk_service(self) -> Any:
        return self._compliance_risk_service

    @property
    def recommendation_service(self) -> Any:
        return self._recommendation_service

    @property
    def governance_service(self) -> Any:
        return self._governance_service

    async def execute(self, task: AgentTask) -> AgentResult:
        start = _now()
        try:
            request = ComplianceAgentRequest(**task.input)
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=f"invalid request: {exc}",
                started_at=start,
                completed_at=_now(),
                duration_ms=0.0,
            )
        try:
            with track_request(
                endpoint="/api/v1/agents/compliance/run",
                strategy="compliance_agent",
            ):
                # 1) Pull the risk assessment (if any)
                assessment = None
                if (
                    self._compliance_risk_service is not None
                    and request.risk_assessment_id
                ):
                    try:
                        assessment = self._compliance_risk_service.get(
                            request.risk_assessment_id
                        )
                    except Exception:  # pragma: no cover
                        assessment = None
                # 2) Analyse
                obligations, gaps, affected_areas, policy_evals = (
                    self._analyzer.analyze(request, assessment)
                )
                # 3) Reason
                risk_level, risk_score = self._reasoner.reason(
                    gaps, assessment
                )
                # 4) Generate actions / recommendations
                actions, rec_ids = self._action_gen.generate(request, gaps)
                # 5) Confidence: derived from gap count + policy evals
                confidence = _tokenize_confidence(
                    0.6
                    - 0.05 * min(5, len(gaps))
                    + (0.1 if any(p.get("compliant") for p in policy_evals) else 0.0),
                    baseline=0.55,
                )
                duration = (_now() - start) * 1000.0
                result = self._reporter.build(
                    request=request,
                    obligations=obligations,
                    gaps=gaps,
                    actions=actions,
                    affected_areas=affected_areas,
                    policy_evaluations=policy_evals,
                    risk_level=risk_level,
                    risk_score=risk_score,
                    confidence=confidence,
                    rec_ids=rec_ids,
                    agent_id=self.agent_id,
                    duration_ms=duration,
                )
            get_intelligence_agent_metrics().record_compliance(
                duration_ms=duration,
                confidence=confidence,
                success=True,
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.SUCCEEDED,
                output=result.model_dump(mode="json"),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )
        except Exception as exc:  # pragma: no cover
            duration = (_now() - start) * 1000.0
            get_intelligence_agent_metrics().record_compliance(
                duration_ms=duration,
                confidence=0.0,
                success=False,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=str(exc),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )

    def health(self) -> AgentHealthCheck:
        h = super().health()
        metrics = get_intelligence_agent_metrics()
        if metrics.compliance_last_error:
            h.last_error = metrics.compliance_last_error
        return h


# ═══════════════════════════════════════════════════════════════════════
# 9.6 — Risk Intelligence Agent
# ═══════════════════════════════════════════════════════════════════════


class RiskAnalyzer:
    """Looks up or derives the baseline risk assessment."""

    def __init__(
        self,
        *,
        compliance_risk_service: Any = None,
        monitoring_service: Any = None,
        impact_analysis_service: Any = None,
    ) -> None:
        self.compliance_risk_service = compliance_risk_service
        self.monitoring_service = monitoring_service
        self.impact_analysis_service = impact_analysis_service

    def analyze(
        self,
        request: RiskAgentRequest,
    ) -> Tuple[Optional[Any], str, float, List[Dict[str, Any]]]:
        assessment = None
        if (
            self.compliance_risk_service is not None
            and request.risk_assessment_id
        ):
            try:
                assessment = self.compliance_risk_service.get(
                    request.risk_assessment_id
                )
            except Exception:  # pragma: no cover
                assessment = None
        # Default score: 0.5 if nothing
        risk_level = "medium"
        risk_score = 0.5
        if assessment is not None:
            rl = getattr(assessment, "risk_level", None)
            risk_level = (
                rl.value if hasattr(rl, "value") else str(rl or "medium")
            )
            risk_score = float(getattr(assessment, "risk_score", 0.5))
        trends: List[Dict[str, Any]] = []
        if (
            self.compliance_risk_service is not None
            and request.document_id
        ):
            try:
                history = self.compliance_risk_service.history_for(
                    document_id=request.document_id
                )
                for h in history[-5:]:
                    trends.append(
                        {
                            "assessment_id": h.assessment_id,
                            "risk_score": h.risk_score,
                            "risk_level": h.risk_level.value
                            if hasattr(h.risk_level, "value")
                            else str(h.risk_level),
                            "generated_at": h.generated_at,
                        }
                    )
            except Exception:  # pragma: no cover
                pass
        return assessment, risk_level, risk_score, trends


class RiskForecastCoordinator:
    """Coordinates a forecast run using the existing forecasting service."""

    def __init__(self, forecasting_service: Any = None) -> None:
        self.forecasting_service = forecasting_service

    def forecast(
        self,
        request: RiskAgentRequest,
        baseline_score: float,
    ) -> Tuple[List[RiskProjection], bool]:
        projections: List[RiskProjection] = []
        drift = False
        if self.forecasting_service is None:
            # Build a simple linear projection if no service
            steps = max(1, request.horizon_days // 30)
            for i in range(1, steps + 1):
                predicted = min(1.0, baseline_score + 0.03 * i)
                projections.append(
                    RiskProjection(
                        horizon_days=i * 30,
                        predicted_score=round(predicted, 4),
                        lower_bound=max(0.0, predicted - 0.1),
                        upper_bound=min(1.0, predicted + 0.1),
                        confidence=0.5,
                        method="agent_linear_proxy",
                    )
                )
            return projections, drift
        # Use real forecasting service
        from app.schemas.forecasting import (
            ForecastRequest,
            HistoryPoint,
            ScenarioRequest,
        )
        try:
            history = [
                HistoryPoint(timestamp=p.get("timestamp", _now()), value=p.get("value", 0.0))
                for p in request.history
            ]
            if not history:
                # Synthesise a tiny series from baseline
                history = [
                    HistoryPoint(timestamp=_now() - (3 - i) * 86400, value=baseline_score)
                    for i in range(3)
                ]
            fr = ForecastRequest(
                document_id=request.document_id,
                horizon_days=request.horizon_days,
                history=history,
            )
            forecast = self.forecasting_service.forecast(fr)
            drift = getattr(forecast, "drift_detected", False)
            for p in forecast.points:
                projections.append(
                    RiskProjection(
                        horizon_days=request.horizon_days,
                        predicted_score=p.predicted_score,
                        lower_bound=p.lower_bound,
                        upper_bound=p.upper_bound,
                        confidence=p.confidence,
                        method=forecast.method,
                    )
                )
            if not projections:
                # Fall back to baseline point
                projections.append(
                    RiskProjection(
                        horizon_days=request.horizon_days,
                        predicted_score=baseline_score,
                        lower_bound=max(0.0, baseline_score - 0.1),
                        upper_bound=min(1.0, baseline_score + 0.1),
                        confidence=0.5,
                        method="agent_baseline",
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Forecasting failed: %s", exc)
            projections.append(
                RiskProjection(
                    horizon_days=request.horizon_days,
                    predicted_score=baseline_score,
                    lower_bound=max(0.0, baseline_score - 0.1),
                    upper_bound=min(1.0, baseline_score + 0.1),
                    confidence=0.4,
                    method="agent_fallback",
                )
            )
        return projections, drift


class ScenarioPlanner:
    """Generates what-if scenarios."""

    _ADJUSTMENTS = {
        RiskScenarioKind.BEST_CASE: -0.15,
        RiskScenarioKind.BASELINE: 0.0,
        RiskScenarioKind.WORST_CASE: 0.20,
        RiskScenarioKind.STRESS: 0.30,
        RiskScenarioKind.TAIL_RISK: 0.40,
    }

    def _level_from_score(self, score: float) -> str:
        if score >= 0.85:
            return "critical"
        if score >= 0.65:
            return "high"
        if score >= 0.4:
            return "medium"
        return "low"

    def plan(
        self,
        request: RiskAgentRequest,
        baseline_score: float,
    ) -> List[RiskScenario]:
        if not request.include_scenarios:
            return []
        scenarios: List[RiskScenario] = []
        for kind in request.scenario_kinds:
            adj = self._ADJUSTMENTS.get(kind, 0.0)
            score = max(0.0, min(1.0, baseline_score + adj))
            scenarios.append(
                RiskScenario(
                    name=kind.value.replace("_", " ").title(),
                    kind=kind,
                    description=(
                        f"What-if scenario: {kind.value} with adjustment "
                        f"{adj:+.2f} from baseline {baseline_score:.2f}."
                    ),
                    predicted_score=round(score, 4),
                    predicted_level=self._level_from_score(score),
                    adjustments={"baseline_delta": adj},
                )
            )
            get_intelligence_agent_metrics().record_scenario_kind(kind.value)
        return scenarios


class RiskReportGenerator:
    """Builds the final RiskAgentResult."""

    def build(
        self,
        request: RiskAgentRequest,
        assessment: Optional[Any],
        risk_level: str,
        risk_score: float,
        projections: List[RiskProjection],
        scenarios: List[RiskScenario],
        trends: List[Dict[str, Any]],
        drift: bool,
        recommended_actions: List[Dict[str, Any]],
        confidence: float,
        agent_id: str,
        duration_ms: float,
    ) -> RiskAgentResult:
        summary = (
            f"Risk intelligence: baseline={risk_level} "
            f"(score={risk_score:.2f}); {len(projections)} projection(s), "
            f"{len(scenarios)} scenario(s), drift={'detected' if drift else 'none'}."
        )
        return RiskAgentResult(
            agent_id=agent_id,
            query=request.query,
            summary=summary,
            risk_score=round(risk_score, 4),
            risk_level=risk_level,
            forecast=projections,
            scenarios=scenarios,
            trends=trends,
            recommended_actions=recommended_actions,
            drift_detected=drift,
            confidence=confidence,
            duration_ms=round(duration_ms, 3),
            started_at=_now() - (duration_ms / 1000.0),
            completed_at=_now(),
            metadata={
                "horizon_days": request.horizon_days,
                "document_id": request.document_id,
                "include_scenarios": request.include_scenarios,
            },
        )


class RiskIntelligenceAgent(BaseAgent):
    """Risk intelligence agent (Module 9.6)."""

    def __init__(
        self,
        metadata: AgentMetadata,
        *,
        compliance_risk_service: Any = None,
        forecasting_service: Any = None,
        monitoring_service: Any = None,
        impact_analysis_service: Any = None,
        recommendation_service: Any = None,
    ) -> None:
        super().__init__(metadata)
        self._analyzer = RiskAnalyzer(
            compliance_risk_service=compliance_risk_service,
            monitoring_service=monitoring_service,
            impact_analysis_service=impact_analysis_service,
        )
        self._forecast_coord = RiskForecastCoordinator(
            forecasting_service=forecasting_service
        )
        self._scenario_planner = ScenarioPlanner()
        self._reporter = RiskReportGenerator()
        self._compliance_risk_service = compliance_risk_service
        self._forecasting_service = forecasting_service
        self._monitoring_service = monitoring_service
        self._recommendation_service = recommendation_service

    @property
    def forecasting_service(self) -> Any:
        return self._forecasting_service

    @property
    def compliance_risk_service(self) -> Any:
        return self._compliance_risk_service

    @property
    def monitoring_service(self) -> Any:
        return self._monitoring_service

    @property
    def recommendation_service(self) -> Any:
        return self._recommendation_service

    async def execute(self, task: AgentTask) -> AgentResult:
        start = _now()
        try:
            request = RiskAgentRequest(**task.input)
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=f"invalid request: {exc}",
                started_at=start,
                completed_at=_now(),
                duration_ms=0.0,
            )
        try:
            with track_request(
                endpoint="/api/v1/agents/risk/run",
                strategy="risk_agent",
            ):
                assessment, risk_level, risk_score, trends = (
                    self._analyzer.analyze(request)
                )
                projections, drift = self._forecast_coord.forecast(
                    request, risk_score
                )
                scenarios = self._scenario_planner.plan(
                    request, risk_score
                )
                recommended_actions: List[Dict[str, Any]] = []
                if (
                    request.include_recommendations
                    and self._recommendation_service is not None
                ):
                    try:
                        from app.schemas.recommendations import (
                            RecommendationRequest,
                        )
                        rec_req = RecommendationRequest(
                            document_id=request.document_id,
                            diff_id=request.diff_id,
                            risk_assessment_id=request.risk_assessment_id,
                            max_recommendations=3,
                        )
                        recs = self._recommendation_service.generate(rec_req)
                        for r in recs:
                            recommended_actions.append(
                                {
                                    "recommendation_id": r.recommendation_id,
                                    "title": r.title,
                                    "priority": str(r.priority.value)
                                    if hasattr(r.priority, "value")
                                    else str(r.priority),
                                }
                            )
                        get_intelligence_agent_metrics().record_recommendation_generated(
                            len(recs)
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.warning(
                            "Recommendation generation failed: %s", exc
                        )
                confidence = _tokenize_confidence(
                    0.55 + 0.1 * (1.0 if projections else 0.0)
                    + 0.1 * (1.0 if trends else 0.0)
                    - 0.05 * (1.0 if drift else 0.0),
                    baseline=0.55,
                )
                duration = (_now() - start) * 1000.0
                result = self._reporter.build(
                    request=request,
                    assessment=assessment,
                    risk_level=risk_level,
                    risk_score=risk_score,
                    projections=projections,
                    scenarios=scenarios,
                    trends=trends,
                    drift=drift,
                    recommended_actions=recommended_actions,
                    confidence=confidence,
                    agent_id=self.agent_id,
                    duration_ms=duration,
                )
            get_intelligence_agent_metrics().record_risk(
                duration_ms=duration,
                confidence=confidence,
                success=True,
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.SUCCEEDED,
                output=result.model_dump(mode="json"),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )
        except Exception as exc:  # pragma: no cover
            duration = (_now() - start) * 1000.0
            get_intelligence_agent_metrics().record_risk(
                duration_ms=duration,
                confidence=0.0,
                success=False,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                status=TaskStatus.FAILED,
                error=str(exc),
                started_at=start,
                completed_at=_now(),
                duration_ms=round(duration, 3),
            )

    def health(self) -> AgentHealthCheck:
        h = super().health()
        metrics = get_intelligence_agent_metrics()
        if metrics.risk_last_error:
            h.last_error = metrics.risk_last_error
        return h


# ═══════════════════════════════════════════════════════════════════════
# Cross-agent collaboration
# ═══════════════════════════════════════════════════════════════════════


class AgentCollaborationBroker:
    """In-process broker that records agent-to-agent calls.

    This is intentionally lightweight: it stores recent collaborations
    in memory so the framework can answer "what evidence did the
    research agent hand off to the compliance agent" type questions.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: List[AgentCollaboration] = []

    def record(self, collab: AgentCollaboration) -> None:
        with self._lock:
            self._items.append(collab)
            # cap the ring buffer
            if len(self._items) > 500:
                self._items = self._items[-500:]

    def list(
        self,
        *,
        from_agent: Optional[str] = None,
        to_agent: Optional[str] = None,
    ) -> List[AgentCollaboration]:
        with self._lock:
            items = list(self._items)
        if from_agent:
            items = [i for i in items if i.from_agent == from_agent]
        if to_agent:
            items = [i for i in items if i.to_agent == to_agent]
        return items

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class IntelligenceAgentFactory:
    """Wires the three specialised agents with shared services.

    The factory does NOT itself run agents; it is the single place
    where the agent instances are constructed and registered with the
    :class:`AgentFrameworkService`.
    """

    def __init__(
        self,
        *,
        agent_framework_service: Any = None,
        research_service: Any = None,
        knowledge_graph_service: Any = None,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
        governance_service: Any = None,
        impact_analysis_service: Any = None,
        forecasting_service: Any = None,
        monitoring_service: Any = None,
    ) -> None:
        self._framework = agent_framework_service
        self._research_service = research_service
        self._kg_service = knowledge_graph_service
        self._compliance_risk_service = compliance_risk_service
        self._recommendation_service = recommendation_service
        self._governance_service = governance_service
        self._impact_service = impact_analysis_service
        self._forecasting_service = forecasting_service
        self._monitoring_service = monitoring_service
        self.broker = AgentCollaborationBroker()
        self._build_agents()

    # ── build ──────────────────────────────────────────────

    def _make_capabilities(
        self,
        kinds: List[CapabilityKind],
    ) -> List[AgentCapability]:
        return [
            AgentCapability(
                kind=k,
                name=k.value,
                description=f"{k.value} capability for intelligence agent",
            )
            for k in kinds
        ]

    def _build_agents(self) -> None:
        # Research
        self.research_agent = ResearchAgent(
            AgentMetadata(
                name="research-agent",
                description=(
                    "Autonomous regulatory research agent "
                    "(Module 9.4). Performs multi-hop, cross-document, "
                    "timeline, comparative, KG and trend research."
                ),
                version="1.0.0",
                author="system",
                capabilities=self._make_capabilities(
                    [
                        CapabilityKind.RETRIEVAL,
                        CapabilityKind.REASONING,
                        CapabilityKind.SUMMARIZATION,
                        CapabilityKind.KNOWLEDGE_GRAPH,
                    ]
                ),
                default_max_retries=1,
                default_timeout_ms=60_000,
                priority=10,
                tags=["intelligence", "research"],
            ),
            research_service=self._research_service,
            knowledge_graph_service=self._kg_service,
        )
        # Compliance
        self.compliance_agent = ComplianceAgent(
            AgentMetadata(
                name="compliance-agent",
                description=(
                    "Compliance intelligence agent (Module 9.5). Performs "
                    "compliance gap analysis, obligation mapping, policy "
                    "evaluation and remediation planning."
                ),
                version="1.0.0",
                author="system",
                capabilities=self._make_capabilities(
                    [
                        CapabilityKind.COMPLIANCE,
                        CapabilityKind.REASONING,
                        CapabilityKind.RECOMMENDATION,
                        CapabilityKind.GOVERNANCE,
                        CapabilityKind.IMPACT_ANALYSIS,
                    ]
                ),
                default_max_retries=1,
                default_timeout_ms=60_000,
                priority=10,
                tags=["intelligence", "compliance"],
            ),
            compliance_risk_service=self._compliance_risk_service,
            recommendation_service=self._recommendation_service,
            governance_service=self._governance_service,
            impact_analysis_service=self._impact_service,
            knowledge_graph_service=self._kg_service,
        )
        # Risk
        self.risk_agent = RiskIntelligenceAgent(
            AgentMetadata(
                name="risk-agent",
                description=(
                    "Risk intelligence agent (Module 9.6). Performs risk "
                    "scoring, forecasting, scenario analysis and trend "
                    "detection."
                ),
                version="1.0.0",
                author="system",
                capabilities=self._make_capabilities(
                    [
                        CapabilityKind.RISK_ASSESSMENT,
                        CapabilityKind.FORECASTING,
                        CapabilityKind.REASONING,
                        CapabilityKind.RECOMMENDATION,
                    ]
                ),
                default_max_retries=1,
                default_timeout_ms=60_000,
                priority=10,
                tags=["intelligence", "risk"],
            ),
            compliance_risk_service=self._compliance_risk_service,
            forecasting_service=self._forecasting_service,
            monitoring_service=self._monitoring_service,
            impact_analysis_service=self._impact_service,
            recommendation_service=self._recommendation_service,
        )

    # ── register with framework ────────────────────────────

    def register_all(self) -> List[AgentMetadata]:
        if self._framework is None:
            return [
                self.research_agent.metadata,
                self.compliance_agent.metadata,
                self.risk_agent.metadata,
            ]
        out: List[AgentMetadata] = []
        for agent in (
            self.research_agent,
            self.compliance_agent,
            self.risk_agent,
        ):
            req = AgentRegistrationRequest(
                name=agent.metadata.name,
                description=agent.metadata.description,
                version=agent.metadata.version,
                author=agent.metadata.author,
                capabilities=agent.metadata.capabilities,
                default_max_retries=agent.metadata.default_max_retries,
                default_timeout_ms=agent.metadata.default_timeout_ms,
                priority=agent.metadata.priority,
                tags=agent.metadata.tags,
            )
            meta = self._framework.register(req, agent)
            out.append(meta)
        return out

    # ── cross-agent helpers ────────────────────────────────

    def collaborate(
        self,
        from_agent: str,
        to_agent: str,
        request_kind: str,
        evidence: Dict[str, Any],
        result: Dict[str, Any],
    ) -> AgentCollaboration:
        collab = AgentCollaboration(
            from_agent=from_agent,
            to_agent=to_agent,
            request_kind=request_kind,
            evidence_keys=sorted(evidence.keys()),
            result_keys=sorted(result.keys()),
            shared_context_keys=sorted(
                set(evidence.keys()) & set(result.keys())
            ),
        )
        self.broker.record(collab)
        get_intelligence_agent_metrics().record_collaboration(
            from_agent,
            to_agent,
            evidence_items=len(evidence),
        )
        return collab


# ═══════════════════════════════════════════════════════════════════════
# Coordinator driver — wraps the existing CoordinatorAgent
# ═══════════════════════════════════════════════════════════════════════


class CoordinatorDriver:
    """Drives a multi-agent coordinated run across the three agents.

    Internally uses the existing :class:`CoordinatorAgent` (Module 9)
    plus the in-process :class:`AgentCollaborationBroker` to record
    evidence sharing.
    """

    def __init__(
        self,
        factory: IntelligenceAgentFactory,
    ) -> None:
        self._factory = factory

    async def run_research_then_compliance(
        self,
        request: ResearchAgentRequest,
        context: Optional[AgentContext] = None,
    ) -> Tuple[ResearchAgentResult, ComplianceAgentResult, List[AgentCollaboration]]:
        """Run research first, then compliance with the research output."""
        context = context or AgentContext()
        # 1) Research
        ra = self._factory.research_agent
        rc = self._factory.compliance_agent
        research_task = AgentTask(
            capability=CapabilityKind.RETRIEVAL,
            input=request.model_dump(mode="json"),
            context=context,
        )
        research_result = await ra.execute(research_task)
        # 2) Build compliance request from research output
        research_output = research_result.output or {}
        compliance_req = ComplianceAgentRequest(
            query=request.query,
            focus_areas=list({m.get("statement", "") for m in research_output.get("findings", [])})[:5]
            or ["compliance"],
            metadata={"research_result_id": research_result.result_id},
        )
        collab_research_to_compliance = self._factory.collaborate(
            from_agent="research",
            to_agent="compliance",
            request_kind="evidence_handoff",
            evidence={
                "research_query": request.query,
                "research_mode": request.mode.value,
            },
            result={
                "compliance_query": compliance_req.query,
                "focus_areas": compliance_req.focus_areas,
            },
        )
        # 3) Compliance
        comp_task = AgentTask(
            capability=CapabilityKind.COMPLIANCE,
            input=compliance_req.model_dump(mode="json"),
            context=context,
        )
        comp_result = await rc.execute(comp_task)
        comp_output = comp_result.output or {}
        collab_compliance_to_risk = self._factory.collaborate(
            from_agent="compliance",
            to_agent="risk",
            request_kind="evidence_handoff",
            evidence={
                "risk_level": comp_output.get("risk_level"),
                "gap_count": len(comp_output.get("gaps", [])),
            },
            result={"forwarded": True},
        )
        return (
            ResearchAgentResult(**research_output),
            ComplianceAgentResult(**comp_output),
            [collab_research_to_compliance, collab_compliance_to_risk],
        )

    async def run_full_pipeline(
        self,
        query: str,
        *,
        mode: ResearchMode = ResearchMode.GENERAL,
        context: Optional[AgentContext] = None,
    ) -> Dict[str, Any]:
        """Convenience: research → compliance → risk pipeline."""
        context = context or AgentContext()
        research_req = ResearchAgentRequest(query=query, mode=mode)
        research_result, comp_result, collabs = (
            await self.run_research_then_compliance(research_req, context)
        )
        # Now risk on the compliance output
        risk_req = RiskAgentRequest(
            query=query,
            document_id=None,
            risk_assessment_id=comp_result.recommendation_ids[0]
            if comp_result.recommendation_ids
            else None,
        )
        risk_task = AgentTask(
            capability=CapabilityKind.RISK_ASSESSMENT,
            input=risk_req.model_dump(mode="json"),
            context=context,
        )
        risk_result = await self._factory.risk_agent.execute(risk_task)
        return {
            "research": research_result.model_dump(mode="json"),
            "compliance": comp_result.model_dump(mode="json"),
            "risk": risk_result.output,
            "collaborations": [c.model_dump(mode="json") for c in collabs],
        }


# ═══════════════════════════════════════════════════════════════════════
# DI facade
# ═══════════════════════════════════════════════════════════════════════


class IntelligenceAgentService:
    """High-level DI facade for the intelligence agent layer."""

    def __init__(
        self,
        factory: IntelligenceAgentFactory,
    ) -> None:
        self.factory = factory
        self.coordinator = CoordinatorDriver(factory)

    # ── direct agent runs ─────────────────────────────────

    async def run_research(
        self,
        request: ResearchAgentRequest,
        *,
        context: Optional[AgentContext] = None,
    ) -> ResearchAgentResult:
        ctx = context or AgentContext()
        task = AgentTask(
            capability=CapabilityKind.RETRIEVAL,
            input=request.model_dump(mode="json"),
            context=ctx,
        )
        result = await self.factory.research_agent.execute(task)
        if result.status == TaskStatus.FAILED:
            raise RuntimeError(result.error)
        return ResearchAgentResult(**(result.output or {}))

    async def run_compliance(
        self,
        request: ComplianceAgentRequest,
        *,
        context: Optional[AgentContext] = None,
    ) -> ComplianceAgentResult:
        ctx = context or AgentContext()
        task = AgentTask(
            capability=CapabilityKind.COMPLIANCE,
            input=request.model_dump(mode="json"),
            context=ctx,
        )
        result = await self.factory.compliance_agent.execute(task)
        if result.status == TaskStatus.FAILED:
            raise RuntimeError(result.error)
        return ComplianceAgentResult(**(result.output or {}))

    async def run_risk(
        self,
        request: RiskAgentRequest,
        *,
        context: Optional[AgentContext] = None,
    ) -> RiskAgentResult:
        ctx = context or AgentContext()
        task = AgentTask(
            capability=CapabilityKind.RISK_ASSESSMENT,
            input=request.model_dump(mode="json"),
            context=ctx,
        )
        result = await self.factory.risk_agent.execute(task)
        if result.status == TaskStatus.FAILED:
            raise RuntimeError(result.error)
        return RiskAgentResult(**(result.output or {}))

    # ── coordinator ───────────────────────────────────────

    async def coordinate(
        self,
        query: str,
        *,
        mode: ResearchMode = ResearchMode.GENERAL,
        context: Optional[AgentContext] = None,
    ) -> Dict[str, Any]:
        return await self.coordinator.run_full_pipeline(
            query, mode=mode, context=context
        )

    async def coordinate_research_compliance(
        self,
        request: ResearchAgentRequest,
        *,
        context: Optional[AgentContext] = None,
    ) -> Dict[str, Any]:
        r, c, collabs = await self.coordinator.run_research_then_compliance(
            request, context
        )
        return {
            "research": r.model_dump(mode="json"),
            "compliance": c.model_dump(mode="json"),
            "collaborations": [col.model_dump(mode="json") for col in collabs],
        }

    # ── health & metrics ──────────────────────────────────

    def health_research(self) -> ResearchAgentHealth:
        m = get_intelligence_agent_metrics()
        avg_dur = (
            m.research_total_duration_ms / m.research_invocations
            if m.research_invocations
            else 0.0
        )
        avg_conf = (
            m.research_confidence_total / m.research_invocations
            if m.research_invocations
            else 0.0
        )
        return ResearchAgentHealth(
            healthy=(
                self.factory.research_agent.health().healthy
                and m.research_failed < 5
            ),
            total_invocations=m.research_invocations,
            successful_invocations=m.research_successful,
            failed_invocations=m.research_failed,
            average_duration_ms=round(avg_dur, 3),
            average_confidence=round(avg_conf, 3),
            last_invocation_at=m.research_last_invocation_at,
            last_error=m.research_last_error,
        )

    def health_compliance(self) -> ComplianceAgentHealth:
        m = get_intelligence_agent_metrics()
        avg_dur = (
            m.compliance_total_duration_ms / m.compliance_invocations
            if m.compliance_invocations
            else 0.0
        )
        avg_conf = (
            m.compliance_confidence_total / m.compliance_invocations
            if m.compliance_invocations
            else 0.0
        )
        return ComplianceAgentHealth(
            healthy=(
                self.factory.compliance_agent.health().healthy
                and m.compliance_failed < 5
            ),
            total_invocations=m.compliance_invocations,
            successful_invocations=m.compliance_successful,
            failed_invocations=m.compliance_failed,
            average_duration_ms=round(avg_dur, 3),
            average_confidence=round(avg_conf, 3),
            last_invocation_at=m.compliance_last_invocation_at,
            last_error=m.compliance_last_error,
        )

    def health_risk(self) -> RiskAgentHealth:
        m = get_intelligence_agent_metrics()
        avg_dur = (
            m.risk_total_duration_ms / m.risk_invocations
            if m.risk_invocations
            else 0.0
        )
        avg_conf = (
            m.risk_confidence_total / m.risk_invocations
            if m.risk_invocations
            else 0.0
        )
        return RiskAgentHealth(
            healthy=(
                self.factory.risk_agent.health().healthy
                and m.risk_failed < 5
            ),
            total_invocations=m.risk_invocations,
            successful_invocations=m.risk_successful,
            failed_invocations=m.risk_failed,
            average_duration_ms=round(avg_dur, 3),
            average_confidence=round(avg_conf, 3),
            last_invocation_at=m.risk_last_invocation_at,
            last_error=m.risk_last_error,
        )

    def metrics(self) -> IntelligenceAgentMetrics:
        m = get_intelligence_agent_metrics()
        def _summary(agent_name: str, total: int, conf: float) -> AgentMetricsSummary:
            avg_conf = conf / total if total else 0.0
            return AgentMetricsSummary(
                agent=agent_name,
                total_invocations=total,
                average_confidence=round(avg_conf, 3),
                last_invocation_at=None,
            )
        return IntelligenceAgentMetrics(
            total_invocations=m.total_invocations,
            total_successful=m.total_successful,
            total_failed=m.total_failed,
            total_collaborations=m.total_collaborations,
            research=_summary(
                "research",
                m.research_invocations,
                m.research_confidence_total,
            ),
            compliance=_summary(
                "compliance",
                m.compliance_invocations,
                m.compliance_confidence_total,
            ),
            risk=_summary("risk", m.risk_invocations, m.risk_confidence_total),
            by_mode=dict(m.by_mode),
            by_scenario_kind=dict(m.by_scenario_kind),
        )

    def collaborations(
        self,
        *,
        from_agent: Optional[str] = None,
        to_agent: Optional[str] = None,
    ) -> List[AgentCollaboration]:
        return self.factory.broker.list(
            from_agent=from_agent, to_agent=to_agent
        )

    def reset(self) -> None:
        get_intelligence_agent_metrics().reset()
        self.factory.broker.clear()


# ═══════════════════════════════════════════════════════════════════════
# Default factory
# ═══════════════════════════════════════════════════════════════════════


def build_default_intelligence_agent_service() -> IntelligenceAgentService:
    """Build a default :class:`IntelligenceAgentService`.

    Resolves the platform service singletons through lazy imports so
    that the agent layer can be imported even if some of the
    underlying services are not yet constructed.
    """
    from app.services.agents import build_default_agent_framework_service
    from app.services.research import build_default_research_service
    from app.services.knowledge_graph import (
        build_default_knowledge_graph_service,
    )
    from app.services.compliance_risk import (
        build_default_compliance_risk_service,
    )
    from app.services.recommendations import (
        build_default_recommendation_service,
    )
    from app.services.governance import build_default_governance_service
    from app.services.impact_analysis import (
        build_default_impact_analysis_service,
    )
    from app.services.forecasting import build_default_forecasting_service
    from app.services.monitoring import build_default_monitoring_service

    framework = build_default_agent_framework_service()
    factory = IntelligenceAgentFactory(
        agent_framework_service=framework,
        research_service=build_default_research_service(),
        knowledge_graph_service=build_default_knowledge_graph_service(),
        compliance_risk_service=build_default_compliance_risk_service(),
        recommendation_service=build_default_recommendation_service(),
        governance_service=build_default_governance_service(),
        impact_analysis_service=build_default_impact_analysis_service(),
        forecasting_service=build_default_forecasting_service(),
        monitoring_service=build_default_monitoring_service(),
    )
    factory.register_all()
    return IntelligenceAgentService(factory)


__all__ = [
    # 9.4
    "ResearchAgentPlanner",
    "ResearchAgentExecutor",
    "ResearchAgentReasoner",
    "ResearchAgentReportGenerator",
    "ResearchAgent",
    # 9.5
    "ComplianceAnalyzer",
    "ComplianceReasoner",
    "ComplianceRecommendationGenerator",
    "ComplianceReportBuilder",
    "ComplianceAgent",
    # 9.6
    "RiskAnalyzer",
    "RiskForecastCoordinator",
    "ScenarioPlanner",
    "RiskReportGenerator",
    "RiskIntelligenceAgent",
    # Cross-agent
    "AgentCollaborationBroker",
    "IntelligenceAgentFactory",
    "CoordinatorDriver",
    "IntelligenceAgentService",
    "build_default_intelligence_agent_service",
]
