"""Module 9.7 — Audit Agent.

Provides audit intelligence and compliance verification. REUSES the
existing Governance, Audit, Knowledge Graph, Compliance and
Recommendation services — it does NOT re-implement any of that logic.

Public surface
--------------
* ``AuditAnalyzer``              — inspect evidence / policies / lineage
* ``AuditReasoner``              — synthesise status + confidence
* ``AuditEvidenceCollector``     — pull evidence from KG / audit / governance
* ``AuditReportGenerator``       — final markdown report + result assembly
* ``AuditAgent``                 — :class:`BaseAgent` implementation
* ``AuditAgentService``          — DI facade (run / health / metrics)
* ``build_default_audit_agent_service``
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.agents import (
    AgentCapability,
    AgentContext,
    AgentHealthCheck,
    AgentMetadata,
    AgentRegistrationRequest,
    AgentResult,
    AgentTask,
    CapabilityKind,
    TaskStatus,
)
from app.schemas.audit_agent import (
    AuditAgentHealth,
    AuditAgentRequest,
    AuditAgentResult,
    AuditEvidenceItem,
    AuditLineageNode,
    AuditMetricsSummary,
    AuditStatus,
    AuditTaskKind,
    AuditViolation,
    AuditViolationSeverity,
)
from app.services.agents import BaseAgent
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Shared utilities
# ═══════════════════════════════════════════════════════════════════════


def _now() -> float:
    return time.time()


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


_SEVERITY_RANK = {
    AuditViolationSeverity.LOW: 1,
    AuditViolationSeverity.MEDIUM: 2,
    AuditViolationSeverity.HIGH: 3,
    AuditViolationSeverity.CRITICAL: 4,
}


# ═══════════════════════════════════════════════════════════════════════
# Analyzer
# ═══════════════════════════════════════════════════════════════════════


class AuditAnalyzer:
    """Inspects the request, pulls evidence from the audit / governance / KG
    services and produces candidate violations and evidence items.

    Heavy logic lives in the reused services; this class is the
    thin orchestration glue that turns their outputs into the
    audit-agent-native shapes.
    """

    _KEYWORD_RULES = (
        ("kyc_renewal", AuditViolationSeverity.HIGH, "KYC renewal cadence"),
        ("incident_reporting", AuditViolationSeverity.CRITICAL, "Cyber incident reporting"),
        ("data_localisation", AuditViolationSeverity.HIGH, "Data localisation"),
        ("capital_adequacy", AuditViolationSeverity.CRITICAL, "Capital adequacy"),
        ("suspicious_transaction_reporting", AuditViolationSeverity.HIGH, "STR filing"),
        ("grievance_redressal", AuditViolationSeverity.MEDIUM, "Grievance redressal"),
        ("outsourcing_due_diligence", AuditViolationSeverity.MEDIUM, "Outsourcing due diligence"),
    )

    def __init__(
        self,
        *,
        audit_service: Any = None,
        governance_service: Any = None,
        knowledge_graph_service: Any = None,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
    ) -> None:
        self.audit_service = audit_service
        self.governance_service = governance_service
        self.knowledge_graph_service = knowledge_graph_service
        self.compliance_risk_service = compliance_risk_service
        self.recommendation_service = recommendation_service

    def _keyword_violations(self, request: AuditAgentRequest) -> List[AuditViolation]:
        out: List[AuditViolation] = []
        q = request.query.lower()
        # Tokenise the query once
        tokens = {tok for tok in q.replace("_", " ").split() if len(tok) > 1}
        for tag, severity, label in self._KEYWORD_RULES:
            # Match if the tag (or any of its parts) appears in the
            # query, OR the label appears in the query.
            tag_tokens = [t for t in tag.split("_") if len(t) > 1]
            label_tokens = [
                t for t in label.lower().split() if len(t) > 1
            ]
            if (
                any(tok in tokens for tok in tag_tokens)
                or any(tok in tokens for tok in label_tokens)
                or label.lower() in q
            ):
                out.append(
                    AuditViolation(
                        title=f"Possible breach: {label}",
                        description=(
                            f"Query references {label}; recommend verifying "
                            "with current policy text."
                        ),
                        severity=severity,
                        source="keyword_heuristic",
                        remediation=(
                            "Pull latest policy from regulatory source and "
                            "diff against current internal controls."
                        ),
                    )
                )
        return out

    def _policy_violations(self, request: AuditAgentRequest) -> List[AuditViolation]:
        out: List[AuditViolation] = []
        if self.governance_service is None:
            return out
        try:
            result = self.governance_service.check(
                decision_type="audit_verification",
                model_id="audit-agent",
                confidence=0.9,
                risk_level="medium",
            )
            for v in getattr(result, "violations", []) or []:
                sev_raw = getattr(v, "severity", "medium")
                try:
                    sev = AuditViolationSeverity(str(sev_raw))
                except ValueError:
                    sev = AuditViolationSeverity.MEDIUM
                out.append(
                    AuditViolation(
                        title=str(getattr(v, "message", "policy_violation")),
                        description=str(getattr(v, "message", "")),
                        severity=sev,
                        source="policy",
                        policy_id=str(getattr(v, "policy_id", "")),
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Governance check failed: %s", exc)
        return out

    def _risk_violations(self, request: AuditAgentRequest) -> List[AuditViolation]:
        out: List[AuditViolation] = []
        if (
            self.compliance_risk_service is not None
            and request.risk_assessment_id
        ):
            try:
                a = self.compliance_risk_service.get(
                    request.risk_assessment_id
                )
                if a is not None:
                    score = float(getattr(a, "risk_score", 0.0))
                    if score >= 0.7:
                        sev = AuditViolationSeverity.CRITICAL
                    elif score >= 0.5:
                        sev = AuditViolationSeverity.HIGH
                    elif score >= 0.3:
                        sev = AuditViolationSeverity.MEDIUM
                    else:
                        sev = AuditViolationSeverity.LOW
                    out.append(
                        AuditViolation(
                            title="Elevated risk assessment",
                            description=(
                                f"Linked risk assessment score={score:.2f}"
                            ),
                            severity=sev,
                            source="risk_assessment",
                            metadata={"risk_score": score},
                        )
                    )
                    for g in getattr(a, "compliance_gaps", []) or []:
                        out.append(
                            AuditViolation(
                                title=getattr(g, "description", "compliance_gap"),
                                description=getattr(g, "description", ""),
                                severity=AuditViolationSeverity.MEDIUM,
                                source="compliance_gap",
                                metadata={
                                    "area": str(getattr(g, "area", "other"))
                                },
                            )
                        )
            except Exception as exc:  # pragma: no cover
                logger.warning("Compliance risk lookup failed: %s", exc)
        return out

    def analyze(
        self, request: AuditAgentRequest
    ) -> Tuple[List[AuditViolation], List[Dict[str, Any]]]:
        violations: List[AuditViolation] = []
        policies: List[Dict[str, Any]] = []

        # 1) Keyword rules
        violations.extend(self._keyword_violations(request))
        # 2) Policy rules
        pol_v = self._policy_violations(request)
        policies.append(
            {
                "source": "governance",
                "violation_count": len(pol_v),
            }
        )
        violations.extend(pol_v)
        # 3) Risk assessment rules
        risk_v = self._risk_violations(request)
        violations.extend(risk_v)

        # Trim
        if len(violations) > request.max_violations:
            violations.sort(
                key=lambda x: -_SEVERITY_RANK.get(x.severity, 0)
            )
            violations = violations[: request.max_violations]
        return violations, policies


# ═══════════════════════════════════════════════════════════════════════
# Evidence collector
# ═══════════════════════════════════════════════════════════════════════


class AuditEvidenceCollector:
    """Collects evidence from the audit / governance / KG / recommendation
    services.
    """

    def __init__(
        self,
        *,
        audit_service: Any = None,
        governance_service: Any = None,
        knowledge_graph_service: Any = None,
        recommendation_service: Any = None,
    ) -> None:
        self.audit_service = audit_service
        self.governance_service = governance_service
        self.knowledge_graph_service = knowledge_graph_service
        self.recommendation_service = recommendation_service

    def collect(
        self, request: AuditAgentRequest
    ) -> Tuple[List[AuditEvidenceItem], List[AuditLineageNode], Dict[str, Any]]:
        items: List[AuditEvidenceItem] = []
        nodes: List[AuditLineageNode] = []
        chain: Dict[str, Any] = {"verified": None, "break_at": ""}

        if self.audit_service is None:
            return items, nodes, chain

        # 1) Try to verify the audit chain
        try:
            ok, break_at = self.audit_service.verify_chain()
            chain = {"verified": bool(ok), "break_at": str(break_at or "")}
        except Exception:  # pragma: no cover
            chain = {"verified": None, "break_at": ""}

        # 2) Pull recent audit records
        try:
            from app.schemas.audit import AuditFilter, AuditSeverity
            flt = AuditFilter(severity=AuditSeverity.INFO, page=1, page_size=20)
            page = self.audit_service.search_records(flt)
            for r in page.items[: request.max_evidence]:
                items.append(
                    AuditEvidenceItem(
                        title=r.action.value
                        if hasattr(r.action, "value")
                        else str(r.action),
                        evidence_kind="audit_record",
                        source=str(r.audit_id),
                        content_hash=r.record_hash,
                        citation_ids=list(r.metadata.get("citation_ids", [])),
                        confidence=1.0,
                        created_at=r.timestamp,
                        metadata={
                            "actor": r.actor,
                            "subject_id": r.subject_id,
                        },
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Audit search failed: %s", exc)

        # 3) Pull governance decisions for lineage
        try:
            for d in (
                self.governance_service.list_decisions()
                if self.governance_service is not None
                else []
            )[: request.max_evidence]:
                nodes.append(
                    AuditLineageNode(
                        kind="governance_decision",
                        label=str(d.decision_type.value)
                        if hasattr(d.decision_type, "value")
                        else str(d.decision_type),
                        subject_id=d.subject_id,
                        actor=d.actor,
                        timestamp=d.timestamp,
                        metadata={"decision_id": d.decision_id},
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Governance lineage failed: %s", exc)

        # 4) Knowledge graph exploration
        if self.knowledge_graph_service is not None:
            try:
                g_nodes, _rels = self.knowledge_graph_service.list_all()
                for n in g_nodes[: request.max_evidence]:
                    items.append(
                        AuditEvidenceItem(
                            title=n.name,
                            evidence_kind="kg_node",
                            source=n.node_id,
                            confidence=0.6,
                            metadata={
                                "entity_type": str(n.entity_type.value)
                                if hasattr(n.entity_type, "value")
                                else str(n.entity_type)
                            },
                        )
                    )
            except Exception as exc:  # pragma: no cover
                logger.warning("KG evidence failed: %s", exc)

        return items[: request.max_evidence], nodes, chain


# ═══════════════════════════════════════════════════════════════════════
# Reasoner
# ═══════════════════════════════════════════════════════════════════════


class AuditReasoner:
    """Synthesises an :class:`AuditStatus` and confidence score."""

    def reason(
        self,
        violations: List[AuditViolation],
        evidence: List[AuditEvidenceItem],
        chain: Dict[str, Any],
    ) -> Tuple[AuditStatus, float, List[str]]:
        if chain.get("verified") is False:
            return AuditStatus.NON_COMPLIANT, 0.95, [
                "audit_chain_broken"
            ]
        if not violations:
            status = AuditStatus.COMPLIANT
            confidence = _clamp(0.9 if evidence else 0.6)
            return status, confidence, []
        max_sev = max(
            (_SEVERITY_RANK.get(v.severity, 0) for v in violations),
            default=0,
        )
        if max_sev >= 3:
            status = AuditStatus.NON_COMPLIANT
        elif max_sev == 2:
            status = AuditStatus.PARTIALLY_COMPLIANT
        elif max_sev == 1:
            status = AuditStatus.PARTIALLY_COMPLIANT
        else:
            status = AuditStatus.UNKNOWN
        confidence = _clamp(0.6 + 0.05 * len(violations))
        affected = sorted(
            {
                str(v.metadata.get("area", v.source))
                for v in violations
                if v.metadata.get("area") or v.source
            }
        )
        return status, confidence, affected


# ═══════════════════════════════════════════════════════════════════════
# Report generator
# ═══════════════════════════════════════════════════════════════════════


class AuditReportGenerator:
    """Builds the final :class:`AuditAgentResult` and a markdown summary."""

    def build(
        self,
        request: AuditAgentRequest,
        violations: List[AuditViolation],
        evidence: List[AuditEvidenceItem],
        lineage: List[AuditLineageNode],
        policies: List[Dict[str, Any]],
        chain: Dict[str, Any],
        status: AuditStatus,
        confidence: float,
        affected_areas: List[str],
        rec_ids: List[str],
        audit_record_ids: List[str],
        decision_ids: List[str],
        agent_id: str,
        duration_ms: float,
    ) -> AuditAgentResult:
        summary = (
            f"Audit ({request.task_kind.value}) verdict: {status.value}; "
            f"{len(violations)} violation(s), {len(evidence)} evidence item(s), "
            f"{len(lineage)} lineage node(s); confidence={confidence:.2f}."
        )
        md = self._render_markdown(
            request, status, confidence,
            violations, evidence, lineage, chain,
        )
        return AuditAgentResult(
            agent_id=agent_id,
            task_kind=request.task_kind,
            query=request.query,
            audit_status=status,
            confidence=confidence,
            summary=summary,
            violations=violations,
            evidence=evidence,
            lineage=lineage,
            policies_evaluated=policies,
            chain_verified=chain.get("verified"),
            chain_break_at=str(chain.get("break_at", "")),
            affected_areas=affected_areas,
            recommendation_ids=rec_ids,
            audit_record_ids=audit_record_ids,
            decision_ids=decision_ids,
            report_markdown=md,
            duration_ms=round(duration_ms, 3),
            started_at=_now() - (duration_ms / 1000.0),
            completed_at=_now(),
            metadata={
                "subject_id": request.subject_id,
                "document_id": request.document_id,
            },
        )

    @staticmethod
    def _render_markdown(
        request: AuditAgentRequest,
        status: AuditStatus,
        confidence: float,
        violations: List[AuditViolation],
        evidence: List[AuditEvidenceItem],
        lineage: List[AuditLineageNode],
        chain: Dict[str, Any],
    ) -> str:
        lines: List[str] = []
        lines.append(f"# Audit Report — {request.task_kind.value}")
        lines.append("")
        lines.append(f"**Query:** {request.query}")
        lines.append("")
        lines.append(f"**Status:** `{status.value}`  ")
        lines.append(f"**Confidence:** {confidence:.2f}  ")
        if chain.get("verified") is not None:
            lines.append(
                f"**Audit chain verified:** {'yes' if chain.get('verified') else 'NO'}"
            )
            if chain.get("break_at"):
                lines.append(f"**Chain break at:** {chain.get('break_at')}")
        lines.append("")
        lines.append("## Violations")
        if not violations:
            lines.append("_No violations detected._")
        else:
            for v in violations:
                lines.append(
                    f"- **{v.severity.value.upper()}** — {v.title}  "
                    f"({v.source})"
                )
                if v.description:
                    lines.append(f"  - {v.description}")
        lines.append("")
        lines.append("## Evidence")
        if not evidence:
            lines.append("_No evidence collected._")
        else:
            for e in evidence:
                lines.append(
                    f"- `{e.evidence_kind}` — {e.title} "
                    f"(confidence {e.confidence:.2f})"
                )
        lines.append("")
        lines.append("## Lineage")
        if not lineage:
            lines.append("_No lineage nodes recorded._")
        else:
            for n in lineage:
                lines.append(
                    f"- {n.kind} — {n.label} (subject={n.subject_id})"
                )
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Agent
# ═══════════════════════════════════════════════════════════════════════


class AuditAgent(BaseAgent):
    """Audit-intelligence agent (Module 9.7).

    The agent is wired with the same services used by the compliance and
    research agents but routes them through the audit-only analyzers and
    evidence collectors defined above.
    """

    def __init__(
        self,
        metadata: AgentMetadata,
        *,
        audit_service: Any = None,
        governance_service: Any = None,
        knowledge_graph_service: Any = None,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
    ) -> None:
        super().__init__(metadata)
        self._analyzer = AuditAnalyzer(
            audit_service=audit_service,
            governance_service=governance_service,
            knowledge_graph_service=knowledge_graph_service,
            compliance_risk_service=compliance_risk_service,
            recommendation_service=recommendation_service,
        )
        self._collector = AuditEvidenceCollector(
            audit_service=audit_service,
            governance_service=governance_service,
            knowledge_graph_service=knowledge_graph_service,
            recommendation_service=recommendation_service,
        )
        self._reasoner = AuditReasoner()
        self._reporter = AuditReportGenerator()
        self._audit_service = audit_service
        self._governance_service = governance_service
        self._knowledge_graph_service = knowledge_graph_service
        self._compliance_risk_service = compliance_risk_service
        self._recommendation_service = recommendation_service

    @property
    def audit_service(self) -> Any:
        return self._audit_service

    @property
    def governance_service(self) -> Any:
        return self._governance_service

    async def execute(self, task: AgentTask) -> AgentResult:
        start = _now()
        try:
            request = AuditAgentRequest(**task.input)
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
                endpoint="/api/v1/agents/audit/run",
                strategy="audit_agent",
            ):
                violations, policies = self._analyzer.analyze(request)
                evidence, lineage, chain = (
                    [], [], {"verified": None, "break_at": ""}
                )
                if request.include_evidence:
                    evidence, lineage, chain = self._collector.collect(
                        request
                    )
                status, confidence, affected = self._reasoner.reason(
                    violations, evidence, chain
                )
                # Best-effort recs
                rec_ids: List[str] = []
                if (
                    self._recommendation_service is not None
                    and (request.risk_assessment_id or request.diff_id)
                ):
                    try:
                        from app.schemas.recommendations import (
                            RecommendationRequest,
                        )
                        rr = RecommendationRequest(
                            document_id=request.document_id,
                            diff_id=request.diff_id,
                            risk_assessment_id=request.risk_assessment_id,
                            max_recommendations=5,
                        )
                        recs = self._recommendation_service.generate(rr)
                        rec_ids.extend(
                            r.recommendation_id for r in recs
                        )
                    except Exception:  # pragma: no cover
                        logger.warning(
                            "Recommendation generation failed",
                            exc_info=True,
                        )
                # Best-effort audit record
                audit_record_ids: List[str] = []
                if self._audit_service is not None:
                    try:
                        from app.schemas.audit import (
                            AuditAction,
                            AuditRecord,
                            AuditSeverity,
                        )
                        rec = AuditRecord(
                            action=AuditAction.OTHER,
                            actor="audit-agent",
                            subject_id=request.subject_id
                            or request.document_id
                            or request.query,
                            severity=AuditSeverity.INFO,
                            description=(
                                f"Audit agent task {request.task_kind.value}"
                            ),
                            metadata={
                                "agent": "audit",
                                "task_kind": request.task_kind.value,
                                "audit_status": status.value,
                            },
                        )
                        created = self._audit_service.create_record(rec)
                        audit_record_ids = [created.audit_id]
                    except Exception:  # pragma: no cover
                        audit_record_ids = []
                decision_ids = [
                    n.metadata.get("decision_id", "")
                    for n in lineage
                    if n.kind == "governance_decision"
                    and n.metadata.get("decision_id")
                ]
                duration = (_now() - start) * 1000.0
                result = self._reporter.build(
                    request=request,
                    violations=violations,
                    evidence=evidence,
                    lineage=lineage,
                    policies=policies,
                    chain=chain,
                    status=status,
                    confidence=confidence,
                    affected_areas=affected,
                    rec_ids=rec_ids,
                    audit_record_ids=audit_record_ids,
                    decision_ids=decision_ids,
                    agent_id=self.agent_id,
                    duration_ms=duration,
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


# ═══════════════════════════════════════════════════════════════════════
# Service / facade
# ═══════════════════════════════════════════════════════════════════════


class AuditAgentService:
    """DI facade for the audit agent."""

    def __init__(
        self,
        agent: AuditAgent,
        *,
        audit_service: Any = None,
        governance_service: Any = None,
        knowledge_graph_service: Any = None,
        compliance_risk_service: Any = None,
        recommendation_service: Any = None,
    ) -> None:
        self.agent = agent
        self.audit_service = audit_service
        self.governance_service = governance_service
        self.knowledge_graph_service = knowledge_graph_service
        self.compliance_risk_service = compliance_risk_service
        self.recommendation_service = recommendation_service
        self._lock = threading.RLock()
        self._metrics = AuditMetricsSummary()

    # ─── registration helper ───────────────────────────────

    def register(self, framework_service: Any) -> None:
        """Register the audit agent with the framework service."""
        try:
            framework_service.register(
                AgentRegistrationRequest(
                    name="audit-agent",
                    description=(
                        "Audit intelligence agent: compliance "
                        "verification, evidence collection, lineage "
                        "analysis and policy validation."
                    ),
                    capabilities=[
                        AgentCapability(
                            kind=CapabilityKind.AUDIT,
                            name="audit",
                            description=(
                                "Compliance verification, audit trail "
                                "analysis, evidence collection, policy "
                                "validation, governance validation, "
                                "regulatory reporting, lineage analysis."
                            ),
                        )
                    ],
                    tags=["m9.7", "audit", "intelligence"],
                ),
                self.agent,
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to register audit agent")

    # ─── run ───────────────────────────────────────────────

    async def run(
        self,
        request: AuditAgentRequest,
        *,
        context: Optional[AgentContext] = None,
    ) -> AuditAgentResult:
        ctx = context or AgentContext(actor="api")
        task = AgentTask(
            capability=CapabilityKind.AUDIT,
            input=request.model_dump(mode="json"),
            context=ctx,
            target_agent=self.agent.name,
        )
        result = await self.agent.execute(task)
        with self._lock:
            self._metrics.total_invocations += 1
            ok = result.status == TaskStatus.SUCCEEDED
            self._metrics.total_successful += 1 if ok else 0
            self._metrics.total_failed += 0 if ok else 1
            self._metrics.by_task_kind[request.task_kind.value] = (
                self._metrics.by_task_kind.get(request.task_kind.value, 0) + 1
            )
            self._metrics.average_duration_ms = _running_mean(
                self._metrics.average_duration_ms,
                result.duration_ms,
                self._metrics.total_invocations,
            )
            if ok and result.output:
                from app.schemas.audit_agent import AuditAgentResult as _AR
                try:
                    parsed = _AR.model_validate(result.output)
                    self._metrics.by_status[parsed.audit_status.value] = (
                        self._metrics.by_status.get(
                            parsed.audit_status.value, 0
                        )
                        + 1
                    )
                    self._metrics.total_violations += len(parsed.violations)
                    self._metrics.total_evidence += len(parsed.evidence)
                    self._metrics.total_lineage_nodes += len(parsed.lineage)
                    if parsed.chain_verified is True:
                        self._metrics.chain_verifications += 1
                    elif parsed.chain_verified is False:
                        self._metrics.chain_failures += 1
                    self._metrics.average_confidence = _running_mean(
                        self._metrics.average_confidence,
                        parsed.confidence,
                        self._metrics.total_invocations,
                    )
                except Exception:  # pragma: no cover
                    pass
        if not ok:
            raise RuntimeError(result.error or "audit agent failed")
        return AuditAgentResult.model_validate(result.output)

    # ─── health / metrics ─────────────────────────────────

    def health(self) -> AuditAgentHealth:
        h = self.agent.health()
        return AuditAgentHealth(
            healthy=h.healthy,
            total_invocations=h.total_invocations,
            successful_invocations=h.successful_invocations,
            failed_invocations=h.failed_invocations,
            average_duration_ms=h.average_duration_ms,
            average_confidence=self._metrics.average_confidence,
            last_invocation_at=h.last_invocation_at,
            last_error=h.last_error,
        )

    def metrics(self) -> AuditMetricsSummary:
        with self._lock:
            return self._metrics.model_copy(deep=True)


def _running_mean(prev: float, sample: float, n: int) -> float:
    if n <= 1:
        return float(sample)
    return round(((prev * (n - 1)) + float(sample)) / n, 3)


# ═══════════════════════════════════════════════════════════════════════
# Default factory
# ═══════════════════════════════════════════════════════════════════════


def build_default_audit_agent_service(
    *,
    audit_service: Any = None,
    governance_service: Any = None,
    knowledge_graph_service: Any = None,
    compliance_risk_service: Any = None,
    recommendation_service: Any = None,
) -> AuditAgentService:
    """Build a default :class:`AuditAgentService` from the given services.

    Each dependency is optional — if ``None`` is passed, the agent still
    works but uses its keyword-based fallbacks.
    """
    metadata = AgentMetadata(
        name="audit-agent",
        description=(
            "Audit intelligence agent: compliance verification, evidence "
            "collection, lineage analysis and policy validation."
        ),
        version="1.0.0",
        author="regintel-ai",
        capabilities=[
            AgentCapability(
                kind=CapabilityKind.AUDIT,
                name="audit",
            )
        ],
        default_max_retries=1,
        default_timeout_ms=30_000,
        priority=10,
        tags=["m9.7", "audit", "intelligence"],
    )
    agent = AuditAgent(
        metadata,
        audit_service=audit_service,
        governance_service=governance_service,
        knowledge_graph_service=knowledge_graph_service,
        compliance_risk_service=compliance_risk_service,
        recommendation_service=recommendation_service,
    )
    return AuditAgentService(
        agent,
        audit_service=audit_service,
        governance_service=governance_service,
        knowledge_graph_service=knowledge_graph_service,
        compliance_risk_service=compliance_risk_service,
        recommendation_service=recommendation_service,
    )


__all__ = [
    "AuditAnalyzer",
    "AuditReasoner",
    "AuditEvidenceCollector",
    "AuditReportGenerator",
    "AuditAgent",
    "AuditAgentService",
    "build_default_audit_agent_service",
]
