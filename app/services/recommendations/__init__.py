"""Module 8.2 — Regulatory Recommendation Engine.

Public surface
--------------
* ``ActionPlanner``              — sequence steps into a plan
* ``RecommendationGenerator``    — produce ranked recommendations
* ``RecommendationRepository``   — search / stats / feedback
* ``RecommendationStore`` (ABC) + ``InMemoryRecommendationStore``
* ``RecommendationService``      — DI facade
* ``build_default_recommendation_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.schemas.risk import (
    AffectedArea,
    RiskAssessment,
    RiskLevel,
)
from app.schemas.recommendations import (
    ActionPlan,
    ActionPlanStep,
    ActionStatus,
    CitationKind,
    PaginatedRecommendations,
    Recommendation,
    RecommendationCitation,
    RecommendationFeedback,
    RecommendationFilter,
    RecommendationPriority,
    RecommendationRequest,
    RecommendationStats,
    RecommendationType,
    ReasoningStep,
)
from app.services.observability import (
    get_recommendation_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Action Planner ─────────────────────────────────────────────────


class ActionPlanner:
    """Convert a free-form recommendation into a sequenced action plan."""

    def plan(
        self,
        title: str,
        steps: List[Dict[str, Any]],
        *,
        total_effort_hours: float = 0.0,
    ) -> ActionPlan:
        seq: List[ActionPlanStep] = []
        for i, raw in enumerate(steps, start=1):
            seq.append(
                ActionPlanStep(
                    sequence=i,
                    title=raw.get("title", f"Step {i}"),
                    description=raw.get("description", ""),
                    owner=raw.get("owner", ""),
                    estimated_effort_hours=float(
                        raw.get("estimated_effort_hours", 0.0)
                    ),
                    depends_on=raw.get("depends_on", []),
                )
            )
        effort = total_effort_hours or sum(s.estimated_effort_hours for s in seq)
        return ActionPlan(
            title=title,
            summary=f"Plan with {len(seq)} step(s)",
            steps=seq,
            total_effort_hours=effort,
            created_at=time.time(),
        )


# ─── Recommendation Generator ──────────────────────────────────────


class RecommendationGenerator:
    """Generate ranked, source-backed recommendations."""

    _PRIORITY_FOR_RISK: Dict[RiskLevel, RecommendationPriority] = {
        RiskLevel.CRITICAL: RecommendationPriority.P0,
        RiskLevel.HIGH: RecommendationPriority.P1,
        RiskLevel.MEDIUM: RecommendationPriority.P2,
        RiskLevel.LOW: RecommendationPriority.P3,
    }

    _AREA_TO_RECOMMENDATION: Dict[AffectedArea, List[Dict[str, Any]]] = {
        AffectedArea.KYC: [
            {
                "type": RecommendationType.COMPLIANCE,
                "title": "Update KYC procedures and re-perform periodic refresh",
                "description": (
                    "Update the KYC policy, run a fresh periodic review of "
                    "the customer base, and reissue training material to "
                    "branch staff."
                ),
                "steps": [
                    {
                        "title": "Update KYC policy",
                        "owner": "Compliance Officer",
                        "estimated_effort_hours": 8.0,
                    },
                    {
                        "title": "Schedule periodic KYC refresh",
                        "owner": "Operations",
                        "estimated_effort_hours": 16.0,
                    },
                    {
                        "title": "Train staff on updated KYC SOP",
                        "owner": "Training Lead",
                        "estimated_effort_hours": 8.0,
                    },
                ],
            }
        ],
        AffectedArea.AML: [
            {
                "type": RecommendationType.COMPLIANCE,
                "title": "Strengthen AML transaction monitoring rules",
                "description": (
                    "Update AML monitoring rules, recalibrate thresholds, "
                    "and re-baseline STR / CTR submissions."
                ),
                "steps": [
                    {
                        "title": "Update AML rules",
                        "owner": "Compliance",
                        "estimated_effort_hours": 12.0,
                    },
                    {
                        "title": "Recalibrate thresholds",
                        "owner": "Data Science",
                        "estimated_effort_hours": 16.0,
                    },
                ],
            }
        ],
        AffectedArea.CAPITAL_ADEQUACY: [
            {
                "type": RecommendationType.STRATEGIC,
                "title": "Re-run capital adequacy and stress tests",
                "description": (
                    "Recompute capital adequacy under the new requirement, "
                    "refresh the capital plan, and escalate to ALCO."
                ),
                "steps": [
                    {
                        "title": "Recompute CAR",
                        "owner": "Risk",
                        "estimated_effort_hours": 16.0,
                    },
                    {
                        "title": "Update capital plan",
                        "owner": "Treasury",
                        "estimated_effort_hours": 12.0,
                    },
                ],
            }
        ],
        AffectedArea.REPORTING: [
            {
                "type": RecommendationType.REPORTING,
                "title": "Update regulatory reporting templates and cadence",
                "description": (
                    "Align reporting templates with the new format, update "
                    "submission cadence, and notify process owners."
                ),
                "steps": [
                    {
                        "title": "Update templates",
                        "owner": "Reporting Lead",
                        "estimated_effort_hours": 8.0,
                    },
                    {
                        "title": "Notify owners",
                        "owner": "Compliance",
                        "estimated_effort_hours": 2.0,
                    },
                ],
            }
        ],
        AffectedArea.CYBER_SECURITY: [
            {
                "type": RecommendationType.TECHNOLOGY,
                "title": "Enhance cyber security controls and incident response",
                "description": (
                    "Map the new requirements to existing cyber controls, "
                    "patch gaps, and rehearse the incident-response playbook."
                ),
                "steps": [
                    {
                        "title": "Gap assessment",
                        "owner": "CISO Office",
                        "estimated_effort_hours": 8.0,
                    },
                    {
                        "title": "Patch gaps",
                        "owner": "IT Security",
                        "estimated_effort_hours": 24.0,
                    },
                ],
            }
        ],
        AffectedArea.DATA_PRIVACY: [
            {
                "type": RecommendationType.POLICY,
                "title": "Update data-privacy notice and consent flows",
                "description": (
                    "Update customer-facing privacy notice, refresh consent "
                    "capture, and run a data-mapping exercise."
                ),
                "steps": [
                    {
                        "title": "Update privacy notice",
                        "owner": "Legal",
                        "estimated_effort_hours": 4.0,
                    },
                    {
                        "title": "Refresh consent flows",
                        "owner": "Product",
                        "estimated_effort_hours": 12.0,
                    },
                ],
            }
        ],
        AffectedArea.OUTSOURCING: [
            {
                "type": RecommendationType.OPERATIONAL,
                "title": "Update vendor risk and outsourcing policy",
                "description": (
                    "Refresh the outsourcing policy, update vendor risk "
                    "questionnaires, and capture new contracts."
                ),
                "steps": [
                    {
                        "title": "Refresh policy",
                        "owner": "Procurement",
                        "estimated_effort_hours": 8.0,
                    },
                ],
            }
        ],
        AffectedArea.RISK_MANAGEMENT: [
            {
                "type": RecommendationType.STRATEGIC,
                "title": "Update enterprise risk management framework",
                "description": (
                    "Refresh the ERM framework, re-baseline the risk "
                    "register, and brief the board."
                ),
                "steps": [
                    {
                        "title": "Refresh ERM framework",
                        "owner": "Risk",
                        "estimated_effort_hours": 16.0,
                    },
                ],
            }
        ],
        AffectedArea.CUSTOMER_PROTECTION: [
            {
                "type": RecommendationType.OPERATIONAL,
                "title": "Update customer grievance redressal mechanism",
                "description": (
                    "Refresh grievance policies, update customer-facing "
                    "communication, and re-train front-line staff."
                ),
                "steps": [
                    {
                        "title": "Update grievance policy",
                        "owner": "Customer Service",
                        "estimated_effort_hours": 8.0,
                    },
                ],
            }
        ],
        AffectedArea.GOVERNANCE: [
            {
                "type": RecommendationType.POLICY,
                "title": "Update governance policies and board reporting",
                "description": (
                    "Refresh governance policies, ensure fit-and-proper "
                    "documentation is current, and align board reporting."
                ),
                "steps": [
                    {
                        "title": "Refresh policies",
                        "owner": "Company Secretary",
                        "estimated_effort_hours": 8.0,
                    },
                ],
            }
        ],
        AffectedArea.FRAUD_PREVENTION: [
            {
                "type": RecommendationType.TECHNOLOGY,
                "title": "Strengthen fraud prevention controls",
                "description": (
                    "Refresh fraud rules, recalibrate models, and rehearse "
                    "fraud-response runbooks."
                ),
                "steps": [
                    {
                        "title": "Refresh fraud rules",
                        "owner": "Fraud Risk",
                        "estimated_effort_hours": 8.0,
                    },
                ],
            }
        ],
    }

    def _priority_for(
        self,
        risk_level: RiskLevel,
        area: Optional[AffectedArea] = None,
    ) -> RecommendationPriority:
        base = self._PRIORITY_FOR_RISK.get(risk_level, RecommendationPriority.P3)
        if area in {AffectedArea.CAPITAL_ADEQUACY, AffectedArea.GOVERNANCE}:
            # Bump by 1 step (P0 stays P0)
            order = list(RecommendationPriority)
            idx = order.index(base)
            return order[min(idx, len(order) - 1)]
        return base

    def generate(
        self,
        request: RecommendationRequest,
        *,
        risk_assessment: Optional[RiskAssessment] = None,
        max_recommendations: int = 5,
    ) -> List[Recommendation]:
        with track_request(
            endpoint="/api/v1/recommendations/generate",
            strategy="rec_generate",
        ):
            if risk_assessment is None and request.risk_assessment_id:
                risk_assessment = self._fetch_risk_assessment(
                    request.risk_assessment_id
                )
            if risk_assessment is None:
                risk_assessment = self._build_default_risk_assessment(request)
            recs: List[Recommendation] = []
            for area_record in risk_assessment.affected_areas:
                templates = self._AREA_TO_RECOMMENDATION.get(area_record.area, [])
                for tpl in templates:
                    planner = ActionPlanner()
                    plan = planner.plan(
                        title=tpl["title"],
                        steps=tpl.get("steps", []),
                    )
                    rec = Recommendation(
                        title=tpl["title"],
                        description=tpl["description"],
                        recommendation_type=tpl["type"],
                        priority=self._priority_for(
                            risk_assessment.risk_level, area_record.area
                        ),
                        confidence=min(1.0, 0.5 + area_record.exposure_score),
                        reasoning=self._build_reasoning(risk_assessment, area_record),
                        citations=self._build_citations(risk_assessment, area_record),
                        action_plan=plan,
                        source="recommendation_engine",
                        document_id=request.document_id,
                        diff_id=request.diff_id,
                        risk_assessment_id=risk_assessment.assessment_id,
                        created_at=time.time(),
                    )
                    recs.append(rec)
                if len(recs) >= max_recommendations:
                    break
            # Always include at least one remediation recommendation
            if not recs:
                recs.append(
                    Recommendation(
                        title="General remediation review",
                        description=(
                            "Conduct a general review of the change and "
                            "document the outcome in the regulatory log."
                        ),
                        recommendation_type=RecommendationType.REMEDIATION,
                        priority=RecommendationPriority.P3,
                        confidence=0.5,
                        reasoning=[
                            ReasoningStep(
                                description="No specific area match; "
                                "fallback to general remediation",
                                rule="area.fallback",
                                output="recommendation.general_remediation",
                            )
                        ],
                        action_plan=ActionPlanner().plan(
                            title="General remediation",
                            steps=[
                                {
                                    "title": "Review and document",
                                    "owner": "Compliance",
                                    "estimated_effort_hours": 4.0,
                                }
                            ],
                        ),
                        source="recommendation_engine",
                        document_id=request.document_id,
                        risk_assessment_id=risk_assessment.assessment_id,
                        created_at=time.time(),
                    )
                )
            get_recommendation_metrics().record_generated(len(recs))
            return recs[:max_recommendations]

    def _build_reasoning(
        self,
        ra: RiskAssessment,
        area: Any,
    ) -> List[ReasoningStep]:
        return [
            ReasoningStep(
                description=(
                    f"Detected affected area {area.area.value} with "
                    f"exposure={area.exposure_score:.2f}"
                ),
                rule="area.detected",
                inputs={"area": area.area.value},
                output=area.area.value,
            ),
            ReasoningStep(
                description=(
                    f"Risk level {ra.risk_level.value} drives priority " f"mapping"
                ),
                rule="priority.map",
                inputs={"risk_level": ra.risk_level.value},
                output=str(self._priority_for(ra.risk_level, area.area)),
            ),
            ReasoningStep(
                description="Selected template recommendation from "
                "area-keyed catalog",
                rule="template.select",
                output="template.applied",
            ),
        ]

    def _build_citations(
        self,
        ra: RiskAssessment,
        area: Any,
    ) -> List[RecommendationCitation]:
        out: List[RecommendationCitation] = []
        if ra.document_id:
            out.append(
                RecommendationCitation(
                    kind=CitationKind.REGULATION,
                    reference=ra.document_id,
                    title=f"Source document {ra.document_id}",
                )
            )
        if ra.diff_id:
            out.append(
                RecommendationCitation(
                    kind=CitationKind.CHANGE_DIFF,
                    reference=ra.diff_id,
                    title=f"Change diff {ra.diff_id}",
                )
            )
        if ra.impact_report_id:
            out.append(
                RecommendationCitation(
                    kind=CitationKind.IMPACT_REPORT,
                    reference=ra.impact_report_id,
                    title=f"Impact report {ra.impact_report_id}",
                )
            )
        out.append(
            RecommendationCitation(
                kind=CitationKind.RESEARCH_REPORT,
                reference=f"risk-assessment:{ra.assessment_id}",
                title=f"Risk assessment {ra.assessment_id}",
                excerpt=ra.explanation.summary,
            )
        )
        return out

    @staticmethod
    def _fetch_risk_assessment(aid: str) -> Optional[RiskAssessment]:
        try:
            from app.services.compliance_risk import (
                build_default_compliance_risk_service,
            )

            return build_default_compliance_risk_service().get(aid)
        except Exception:  # pragma: no cover
            return None

    @staticmethod
    def _build_default_risk_assessment(
        request: RecommendationRequest,
    ) -> RiskAssessment:
        from app.schemas.risk import (
            AffectedArea,
            AffectedAreaRecord,
            RiskAssessment,
            RiskCategory,
            RiskExplanation,
            RiskLevel,
        )

        return RiskAssessment(
            document_id=request.document_id,
            source="auto",
            risk_level=RiskLevel.MEDIUM,
            risk_score=0.5,
            risk_categories=[RiskCategory.OPERATIONAL],
            affected_areas=[
                AffectedAreaRecord(
                    area=AffectedArea.OTHER,
                    exposure_score=0.5,
                    rationale="No specific risk assessment provided",
                )
            ],
            explanation=RiskExplanation(summary="Auto-generated assessment"),
            generated_at=time.time(),
        )


# ─── Store ───────────────────────────────────────────────────────────


class RecommendationStore(ABC):
    @abstractmethod
    def add(self, rec: Recommendation) -> None: ...

    @abstractmethod
    def get(self, rid: str) -> Optional[Recommendation]: ...

    @abstractmethod
    def list_all(self) -> List[Recommendation]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryRecommendationStore(RecommendationStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._items: Dict[str, Recommendation] = {}
        self._persist_path = persist_path
        if self._persist_path and os.path.exists(self._persist_path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        r = Recommendation(**data)
                        self._items[r.recommendation_id] = r
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, r: Recommendation) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(r.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add(self, rec: Recommendation) -> None:
        with self._lock:
            self._items[rec.recommendation_id] = rec
        self._persist(rec)

    def get(self, rid: str) -> Optional[Recommendation]:
        with self._lock:
            return self._items.get(rid)

    def list_all(self) -> List[Recommendation]:
        with self._lock:
            return list(self._items.values())

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Repository ──────────────────────────────────────────────────────


class RecommendationRepository:
    def __init__(self, store: RecommendationStore) -> None:
        self._store = store

    def add(self, r: Recommendation) -> None:
        self._store.add(r)

    def get(self, rid: str) -> Optional[Recommendation]:
        return self._store.get(rid)

    def search(self, flt: RecommendationFilter) -> PaginatedRecommendations:
        items = self._store.list_all()
        if flt.recommendation_type:
            items = [
                r for r in items if r.recommendation_type == flt.recommendation_type
            ]
        if flt.priority:
            items = [r for r in items if r.priority == flt.priority]
        if flt.status:
            items = [r for r in items if r.status == flt.status]
        if flt.document_id:
            items = [r for r in items if r.document_id == flt.document_id]
        if flt.after is not None:
            items = [r for r in items if r.created_at >= flt.after]
        if flt.before is not None:
            items = [r for r in items if r.created_at <= flt.before]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedRecommendations(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> RecommendationStats:
        items = self._store.list_all()
        s = RecommendationStats(total_recommendations=len(items))
        if not items:
            return s
        conf_total = 0.0
        for r in items:
            conf_total += r.confidence
            s.by_priority[r.priority.value] = s.by_priority.get(r.priority.value, 0) + 1
            s.by_type[r.recommendation_type.value] = (
                s.by_type.get(r.recommendation_type.value, 0) + 1
            )
            s.by_status[r.status.value] = s.by_status.get(r.status.value, 0) + 1
            if r.status == ActionStatus.ACCEPTED:
                s.accepted += 1
            elif r.status == ActionStatus.REJECTED:
                s.rejected += 1
            elif r.status == ActionStatus.PROPOSED:
                s.proposed += 1
            elif r.status == ActionStatus.IN_PROGRESS:
                s.in_progress += 1
            elif r.status == ActionStatus.COMPLETED:
                s.completed += 1
            s.last_recommendation_at = max(s.last_recommendation_at or 0, r.created_at)
        s.average_confidence = round(conf_total / len(items), 4)
        decided = s.accepted + s.rejected
        s.acceptance_rate = round(s.accepted / decided, 4) if decided > 0 else 0.0
        return s


# ─── Service (DI facade) ────────────────────────────────────────────


class RecommendationService:
    def __init__(self, store: RecommendationStore) -> None:
        self.store = store
        self.repository = RecommendationRepository(store)
        self.generator = RecommendationGenerator()
        self.planner = ActionPlanner()

    def generate(self, request: RecommendationRequest) -> List[Recommendation]:
        recs = self.generator.generate(
            request, max_recommendations=request.max_recommendations
        )
        for r in recs:
            self.store.add(r)
        return recs

    def feedback(
        self, rid: str, fb: RecommendationFeedback
    ) -> Optional[Recommendation]:
        rec = self.store.get(rid)
        if rec is None:
            return None
        rec.status = fb.status
        rec.feedback = fb.feedback
        if fb.status == ActionStatus.ACCEPTED:
            rec.accepted_at = time.time()
        elif fb.status == ActionStatus.COMPLETED:
            rec.completed_at = time.time()
        self.store.add(rec)
        get_recommendation_metrics().record_feedback(fb.status.value)
        return rec

    def get(self, rid: str) -> Optional[Recommendation]:
        return self.store.get(rid)

    def search(self, flt: RecommendationFilter) -> PaginatedRecommendations:
        return self.repository.search(flt)

    def stats(self) -> RecommendationStats:
        return self.repository.stats()

    def list_all(self) -> List[Recommendation]:
        return self.store.list_all()


# ─── Factory ────────────────────────────────────────────────────────


def build_default_recommendation_service() -> RecommendationService:
    persist = os.path.join(settings.STORAGE_ROOT, "recommendations", "recs.jsonl")
    store = InMemoryRecommendationStore(persist_path=persist)
    return RecommendationService(store=store)


__all__ = [
    "ActionPlanner",
    "RecommendationGenerator",
    "RecommendationStore",
    "InMemoryRecommendationStore",
    "RecommendationRepository",
    "RecommendationService",
    "build_default_recommendation_service",
]
