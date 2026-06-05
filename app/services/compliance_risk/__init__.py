"""Module 8.1 — Compliance Risk Intelligence Engine.

Public surface
--------------
* ``RiskScorer``        — composite score + level
* ``RiskAnalyzer``      — explainable factor extraction
* ``RiskRepository``    — search / stats / history
* ``RiskStore`` (ABC) + ``InMemoryRiskStore`` (JSONL)
* ``ComplianceRiskService`` — DI facade
* ``build_default_compliance_risk_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionResult,
    ChangeSeverity,
)
from app.schemas.impact import ImpactLevel, ImpactReport
from app.schemas.risk import (
    AffectedArea,
    AffectedAreaRecord,
    ComplianceGap,
    PaginatedRiskAssessments,
    RecommendedAction,
    RecommendedActionType,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskCategory,
    RiskExplanation,
    RiskFactor,
    RiskFilter,
    RiskLevel,
    RiskStats,
    RiskTrend,
    RiskTrendPoint,
)
from app.services.observability import (
    get_risk_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Keyword tables (deterministic) ──────────────────────────────────


_AREA_KEYWORDS: Dict[AffectedArea, Tuple[str, ...]] = {
    AffectedArea.KYC: ("kyc", "know your customer", "customer identification", "cid"),
    AffectedArea.AML: ("aml", "anti-money laundering", "pmla", "suspicious transaction"),
    AffectedArea.CAPITAL_ADEQUACY: (
        "capital adequacy",
        "car",
        "tier 1",
        "tier 2",
        "capital requirement",
    ),
    AffectedArea.REPORTING: (
        "reporting",
        "submission",
        "filing",
        "return filing",
        "disclosure",
    ),
    AffectedArea.CYBER_SECURITY: (
        "cyber security",
        "cybersecurity",
        "cyber incident",
        "ransomware",
    ),
    AffectedArea.DATA_PRIVACY: (
        "data privacy",
        "data protection",
        "personal data",
        "consent",
    ),
    AffectedArea.OUTSOURCING: ("outsourcing", "third party", "vendor risk"),
    AffectedArea.RISK_MANAGEMENT: (
        "risk management",
        "risk framework",
        "risk assessment",
    ),
    AffectedArea.CUSTOMER_PROTECTION: (
        "customer protection",
        "customer grievance",
        "fair practices",
    ),
    AffectedArea.GOVERNANCE: (
        "governance",
        "board",
        "fit and proper",
    ),
    AffectedArea.FRAUD_PREVENTION: (
        "fraud",
        "fraud prevention",
        "fraud risk",
    ),
}


_ACTION_KEYWORDS: Dict[RecommendedActionType, Tuple[str, ...]] = {
    RecommendedActionType.IMMEDIATE_REVIEW: (
        "penalty",
        "violation",
        "non-compliance",
        "shall not",
        "prohibited",
        "revoke",
    ),
    RecommendedActionType.POLICY_UPDATE: (
        "policy",
        "amendment",
        "amend",
        "update",
    ),
    RecommendedActionType.PROCESS_CHANGE: (
        "process",
        "procedure",
        "workflow",
        "shall",
    ),
    RecommendedActionType.TRAINING: (
        "training",
        "awareness",
        "education",
    ),
    RecommendedActionType.REPORTING_UPDATE: (
        "reporting",
        "return",
        "filing",
        "disclosure",
    ),
    RecommendedActionType.TECHNOLOGY_UPGRADE: (
        "system",
        "technology",
        "platform",
        "automation",
    ),
    RecommendedActionType.STAKEHOLDER_ESCALATION: (
        "board",
        "senior management",
        "audit committee",
    ),
    RecommendedActionType.EXTERNAL_ADVISORY: (
        "legal",
        "consultant",
        "external advisor",
    ),
    RecommendedActionType.MONITORING_ENHANCEMENT: (
        "monitor",
        "monitoring",
        "track",
    ),
    RecommendedActionType.DOCUMENTATION: (
        "document",
        "record",
        "log",
    ),
}


# ─── Risk Scorer ─────────────────────────────────────────────────────


class RiskScorer:
    """Compute a 0..1 composite risk score + level."""

    _SEVERITY_WEIGHT: Dict[ChangeSeverity, float] = {
        ChangeSeverity.LOW: 0.2,
        ChangeSeverity.MEDIUM: 0.5,
        ChangeSeverity.HIGH: 0.8,
        ChangeSeverity.CRITICAL: 1.0,
    }
    _CATEGORY_WEIGHT: Dict[ChangeCategory, float] = {
        ChangeCategory.PENALTY_CHANGE: 1.0,
        ChangeCategory.COMPLIANCE_DEADLINE: 0.9,
        ChangeCategory.CAPITAL_REQUIREMENT: 0.95,
        ChangeCategory.REPORTING_REQUIREMENT: 0.8,
        ChangeCategory.REGULATORY_AMENDMENT: 0.7,
        ChangeCategory.NEW_GUIDANCE: 0.5,
        ChangeCategory.SCOPE_CHANGE: 0.75,
        ChangeCategory.POLICY_UPDATE: 0.6,
        ChangeCategory.CLARIFICATION: 0.2,
        ChangeCategory.OTHER: 0.4,
    }
    _IMPACT_WEIGHT: Dict[ImpactLevel, float] = {
        ImpactLevel.NEGLIGIBLE: 0.05,
        ImpactLevel.LOW: 0.25,
        ImpactLevel.MEDIUM: 0.55,
        ImpactLevel.HIGH: 0.8,
        ImpactLevel.CRITICAL: 1.0,
    }

    def score(
        self,
        *,
        severity: ChangeSeverity,
        category: ChangeCategory,
        impact_level: ImpactLevel,
        change_count: int,
        gap_count: int,
    ) -> Tuple[float, RiskLevel]:
        sev = self._SEVERITY_WEIGHT.get(severity, 0.3)
        cat = self._CATEGORY_WEIGHT.get(category, 0.4)
        imp = self._IMPACT_WEIGHT.get(impact_level, 0.3)
        breadth = min(1.0, change_count / 5.0)
        gap_pen = min(1.0, gap_count / 3.0)
        raw = 0.30 * sev + 0.25 * cat + 0.25 * imp + 0.10 * breadth + 0.10 * gap_pen
        score = max(0.0, min(1.0, raw))
        return score, self._to_level(score)

    @staticmethod
    def _to_level(score: float) -> RiskLevel:
        if score >= 0.85:
            return RiskLevel.CRITICAL
        if score >= 0.65:
            return RiskLevel.HIGH
        if score >= 0.4:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


# ─── Risk Analyzer ───────────────────────────────────────────────────


class RiskAnalyzer:
    """Extract risk factors, affected areas, gaps, and recommended actions."""

    def analyze(
        self,
        text: str,
        *,
        severity: ChangeSeverity,
        category: ChangeCategory,
        impact_level: ImpactLevel,
        change_count: int,
    ) -> Dict[str, Any]:
        text_lower = (text or "").lower()

        # Affected areas
        areas: List[AffectedAreaRecord] = []
        for area, kws in _AREA_KEYWORDS.items():
            hits = sum(1 for k in kws if k in text_lower)
            if hits == 0:
                continue
            score = min(1.0, hits / max(1, len(kws)))
            areas.append(
                AffectedAreaRecord(
                    area=area,
                    exposure_score=score,
                    rationale=f"{hits} keyword(s) matched",
                    related_changes=hits,
                )
            )
        if not areas:
            areas.append(
                AffectedAreaRecord(
                    area=AffectedArea.OTHER,
                    exposure_score=0.2,
                    rationale="No specific area keywords detected",
                    related_changes=0,
                )
            )

        # Risk factors (weighted)
        factors: List[RiskFactor] = []
        factors.append(
            RiskFactor(
                name="Change severity",
                category=RiskCategory.REGULATORY_EXPOSURE,
                weight=1.0,
                raw_value=RiskScorer()._SEVERITY_WEIGHT.get(severity, 0.3),
                contribution=0.0,
                explanation=f"Detected severity={severity.value}",
                source="change_detection",
            )
        )
        factors.append(
            RiskFactor(
                name="Change category",
                category=RiskCategory.COMPLIANCE_GAP,
                weight=1.0,
                raw_value=RiskScorer()._CATEGORY_WEIGHT.get(category, 0.4),
                contribution=0.0,
                explanation=f"Category={category.value}",
                source="change_detection",
            )
        )
        factors.append(
            RiskFactor(
                name="Impact level",
                category=RiskCategory.OPERATIONAL,
                weight=1.0,
                raw_value=RiskScorer()._IMPACT_WEIGHT.get(impact_level, 0.3),
                contribution=0.0,
                explanation=f"Impact level={impact_level.value}",
                source="impact_analysis",
            )
        )
        factors.append(
            RiskFactor(
                name="Change breadth",
                category=RiskCategory.OPERATIONAL,
                weight=0.5,
                raw_value=float(change_count),
                contribution=0.0,
                explanation=f"{change_count} clause change(s)",
                source="change_detection",
            )
        )

        # Recommended actions
        actions: List[RecommendedAction] = self._actions_for(
            text_lower, severity, category
        )

        # Compliance gaps (rule: if category in {penalty, deadline, capital, reporting} add gap)
        gaps: List[ComplianceGap] = []
        gap_categories: Dict[ChangeCategory, AffectedArea] = {
            ChangeCategory.PENALTY_CHANGE: AffectedArea.GOVERNANCE,
            ChangeCategory.COMPLIANCE_DEADLINE: AffectedArea.REPORTING,
            ChangeCategory.CAPITAL_REQUIREMENT: AffectedArea.CAPITAL_ADEQUACY,
            ChangeCategory.REPORTING_REQUIREMENT: AffectedArea.REPORTING,
            ChangeCategory.SCOPE_CHANGE: AffectedArea.GOVERNANCE,
            ChangeCategory.REGULATORY_AMENDMENT: AffectedArea.GOVERNANCE,
        }
        if category in gap_categories:
            gaps.append(
                ComplianceGap(
                    area=gap_categories[category],
                    severity=RiskScorer()._to_level(
                        0.6 if severity in (ChangeSeverity.HIGH, ChangeSeverity.CRITICAL) else 0.3
                    ),
                    description=(
                        f"Compliance gap detected for category "
                        f"{category.value} affecting "
                        f"{gap_categories[category].value}"
                    ),
                    regulatory_basis=category.value,
                )
            )

        # Determine overall risk categories
        cats: List[RiskCategory] = []
        if category in {
            ChangeCategory.PENALTY_CHANGE,
            ChangeCategory.REGULATORY_AMENDMENT,
            ChangeCategory.COMPLIANCE_DEADLINE,
        }:
            cats.append(RiskCategory.REGULATORY_EXPOSURE)
        if gaps:
            cats.append(RiskCategory.COMPLIANCE_GAP)
        if category in {
            ChangeCategory.REPORTING_REQUIREMENT,
            ChangeCategory.SCOPE_CHANGE,
        }:
            cats.append(RiskCategory.OPERATIONAL)
        if category == ChangeCategory.CAPITAL_REQUIREMENT:
            cats.append(RiskCategory.FINANCIAL)
        if not cats:
            cats.append(RiskCategory.OPERATIONAL)

        return {
            "areas": areas,
            "factors": factors,
            "actions": actions,
            "gaps": gaps,
            "categories": cats,
        }

    def _actions_for(
        self,
        text_lower: str,
        severity: ChangeSeverity,
        category: ChangeCategory,
    ) -> List[RecommendedAction]:
        out: List[RecommendedAction] = []
        # Always include a primary action based on category
        if category == ChangeCategory.PENALTY_CHANGE:
            out.append(
                RecommendedAction(
                    action_type=RecommendedActionType.IMMEDIATE_REVIEW,
                    title="Conduct immediate review of new penalty exposure",
                    description=(
                        "Review the new penalty structure, identify in-scope "
                        "products / processes, and update the internal control "
                        "matrix."
                    ),
                    priority=RiskLevel.HIGH
                    if severity == ChangeSeverity.CRITICAL
                    else RiskLevel.MEDIUM,
                    rationale="Penalty changes are immediate compliance priorities.",
                    confidence=0.9,
                    estimated_effort_hours=16.0,
                )
            )
        if category == ChangeCategory.COMPLIANCE_DEADLINE:
            out.append(
                RecommendedAction(
                    action_type=RecommendedActionType.REPORTING_UPDATE,
                    title="Capture new compliance deadline",
                    description=(
                        "Update the compliance calendar with the new deadline, "
                        "notify process owners, and confirm evidence capture."
                    ),
                    priority=RiskLevel.MEDIUM,
                    rationale="Time-bound compliance obligations require calendar updates.",
                    confidence=0.9,
                    estimated_effort_hours=4.0,
                )
            )
        if category == ChangeCategory.CAPITAL_REQUIREMENT:
            out.append(
                RecommendedAction(
                    action_type=RecommendedActionType.PROCESS_CHANGE,
                    title="Re-run capital adequacy calculations",
                    description=(
                        "Recompute capital adequacy under the new requirement, "
                        "escalate to treasury / risk, and update the capital plan."
                    ),
                    priority=RiskLevel.HIGH,
                    rationale="Capital changes have direct balance-sheet impact.",
                    confidence=0.85,
                    estimated_effort_hours=24.0,
                )
            )
        if category == ChangeCategory.REPORTING_REQUIREMENT:
            out.append(
                RecommendedAction(
                    action_type=RecommendedActionType.REPORTING_UPDATE,
                    title="Update reporting templates and cadence",
                    description=(
                        "Align the reporting templates and submission process "
                        "with the new requirement."
                    ),
                    priority=RiskLevel.MEDIUM,
                    rationale="Reporting scope / format changes require template updates.",
                    confidence=0.8,
                    estimated_effort_hours=8.0,
                )
            )
        # Keyword-driven action detection
        for action_type, kws in _ACTION_KEYWORDS.items():
            if any(k in text_lower for k in kws):
                if any(a.action_type == action_type for a in out):
                    continue
                out.append(
                    RecommendedAction(
                        action_type=action_type,
                        title=f"Consider: {action_type.value.replace('_', ' ')}",
                        description=(
                            f"Signals in the regulatory text suggest "
                            f"{action_type.value} may be required."
                        ),
                        priority=RiskLevel.MEDIUM,
                        confidence=0.6,
                        rationale="Keyword-based signal in source text.",
                    )
                )
        # Always include a documentation action
        out.append(
            RecommendedAction(
                action_type=RecommendedActionType.DOCUMENTATION,
                title="Document assessment in regulatory log",
                description=(
                    "File the assessment outcome in the regulatory change log "
                    "for audit-trail purposes."
                ),
                priority=RiskLevel.LOW,
                confidence=1.0,
                estimated_effort_hours=0.5,
            )
        )
        return out


# ─── Store ───────────────────────────────────────────────────────────


class RiskStore(ABC):
    @abstractmethod
    def add(self, assessment: RiskAssessment) -> None: ...

    @abstractmethod
    def get(self, assessment_id: str) -> Optional[RiskAssessment]: ...

    @abstractmethod
    def list_all(self) -> List[RiskAssessment]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryRiskStore(RiskStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._items: Dict[str, RiskAssessment] = {}
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
                        a = RiskAssessment(**data)
                        self._items[a.assessment_id] = a
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, a: RiskAssessment) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(a.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add(self, assessment: RiskAssessment) -> None:
        with self._lock:
            self._items[assessment.assessment_id] = assessment
        self._persist(assessment)

    def get(self, assessment_id: str) -> Optional[RiskAssessment]:
        with self._lock:
            return self._items.get(assessment_id)

    def list_all(self) -> List[RiskAssessment]:
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


class RiskRepository:
    def __init__(self, store: RiskStore) -> None:
        self._store = store

    def add(self, a: RiskAssessment) -> None:
        self._store.add(a)

    def get(self, aid: str) -> Optional[RiskAssessment]:
        return self._store.get(aid)

    def search(self, flt: RiskFilter) -> PaginatedRiskAssessments:
        items = self._store.list_all()
        if flt.risk_level:
            items = [a for a in items if a.risk_level == flt.risk_level]
        if flt.category:
            items = [a for a in items if flt.category in a.risk_categories]
        if flt.document_id:
            items = [a for a in items if a.document_id == flt.document_id]
        if flt.after is not None:
            items = [a for a in items if a.generated_at >= flt.after]
        if flt.before is not None:
            items = [a for a in items if a.generated_at <= flt.before]
        items.sort(key=lambda a: a.generated_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedRiskAssessments(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> RiskStats:
        items = self._store.list_all()
        s = RiskStats(total_assessments=len(items))
        if not items:
            return s
        total_score = 0.0
        for a in items:
            total_score += a.risk_score
            s.total_recommended_actions += len(a.recommended_actions)
            s.total_compliance_gaps += len(a.compliance_gaps)
            s.by_source[a.source] = s.by_source.get(a.source, 0) + 1
            for cat in a.risk_categories:
                s.by_category[cat.value] = s.by_category.get(cat.value, 0) + 1
            for ar in a.affected_areas:
                s.by_affected_area[ar.area.value] = (
                    s.by_affected_area.get(ar.area.value, 0) + 1
                )
            if a.risk_level == RiskLevel.CRITICAL:
                s.critical_risks += 1
            elif a.risk_level == RiskLevel.HIGH:
                s.high_risks += 1
            elif a.risk_level == RiskLevel.MEDIUM:
                s.medium_risks += 1
            else:
                s.low_risks += 1
            s.last_assessment_at = max(s.last_assessment_at or 0, a.generated_at)
        s.average_risk_score = total_score / len(items)
        return s

    def history_for(
        self, document_id: Optional[str] = None, source: Optional[str] = None
    ) -> List[RiskAssessment]:
        items = self._store.list_all()
        if document_id:
            items = [a for a in items if a.document_id == document_id]
        if source:
            items = [a for a in items if a.source == source]
        items.sort(key=lambda a: a.generated_at)
        return items

    def trend_for(
        self, document_id: Optional[str] = None
    ) -> RiskTrend:
        items = self.history_for(document_id=document_id)
        points = [
            RiskTrendPoint(
                timestamp=a.generated_at,
                risk_score=a.risk_score,
                risk_level=a.risk_level,
            )
            for a in items
        ]
        direction = "flat"
        delta = 0.0
        if len(points) >= 2:
            delta = points[-1].risk_score - points[0].risk_score
            if delta > 0.05:
                direction = "up"
            elif delta < -0.05:
                direction = "down"
        return RiskTrend(
            document_id=document_id,
            source=items[-1].source if items else None,
            points=points,
            direction=direction,
            delta=round(delta, 4),
        )


# ─── Service (DI facade) ────────────────────────────────────────────


class ComplianceRiskService:
    """DI facade for compliance risk intelligence."""

    def __init__(self, store: RiskStore) -> None:
        self.store = store
        self.repository = RiskRepository(store)
        self.scorer = RiskScorer()
        self.analyzer = RiskAnalyzer()

    # ── core assess ─────────────────────────────────────────────

    def assess(
        self,
        request: RiskAssessmentRequest,
        *,
        change_result: Optional[ChangeDetectionResult] = None,
        impact_report: Optional[ImpactReport] = None,
    ) -> RiskAssessment:
        start = time.time()
        with track_request(
            endpoint="/api/v1/compliance-risk/assess", strategy="risk_assess"
        ):
            # Resolve inputs
            if change_result is None and impact_report is None:
                # Try to fetch via DI service singletons
                if request.diff_id:
                    change_result = self._fetch_change_result(request.diff_id)
                if request.impact_report_id:
                    impact_report = self._fetch_impact_report(
                        request.impact_report_id
                    )
            severity = self._resolve_severity(change_result, impact_report)
            category = self._resolve_category(change_result)
            impact_level = self._resolve_impact_level(impact_report)
            change_count = (
                len(change_result.diff.changes) if change_result else 1
            )
            text = self._gather_text(change_result, impact_report)
            analysis = self.analyzer.analyze(
                text,
                severity=severity,
                category=category,
                impact_level=impact_level,
                change_count=change_count,
            )
            gap_count = len(analysis["gaps"])
            score, level = self.scorer.score(
                severity=severity,
                category=category,
                impact_level=impact_level,
                change_count=change_count,
                gap_count=gap_count,
            )
            # Update factor contributions
            total_weight = sum(f.weight for f in analysis["factors"]) or 1.0
            for f in analysis["factors"]:
                f.contribution = round(f.weight / total_weight * score, 4)
            explanation = RiskExplanation(
                summary=(
                    f"Risk={level.value} (score={score:.2f}) driven by "
                    f"severity={severity.value}, category={category.value}, "
                    f"impact={impact_level.value}, changes={change_count}, "
                    f"gaps={gap_count}."
                ),
                top_factors=sorted(
                    analysis["factors"],
                    key=lambda f: f.contribution,
                    reverse=True,
                )[:5],
                confidence=0.85,
            )
            # Historical reference
            history = self.repository.history_for(
                document_id=request.document_id, source=request.source
            )
            historical_score = history[-1].risk_score if history else None
            trend = "flat"
            if historical_score is not None:
                d = score - historical_score
                if d > 0.05:
                    trend = "up"
                elif d < -0.05:
                    trend = "down"
            assessment = RiskAssessment(
                document_id=request.document_id,
                diff_id=request.diff_id,
                impact_report_id=request.impact_report_id,
                source=request.source,
                risk_level=level,
                risk_score=round(score, 4),
                risk_categories=analysis["categories"],
                affected_areas=analysis["areas"],
                recommended_actions=analysis["actions"],
                compliance_gaps=analysis["gaps"],
                explanation=explanation,
                regulatory_exposure=min(
                    1.0,
                    (
                        sum(a.exposure_score for a in analysis["areas"])
                        / max(1, len(analysis["areas"]))
                    ),
                ),
                historical_risk_score=historical_score,
                trend=trend,
                generated_at=time.time(),
                duration_ms=round((time.time() - start) * 1000.0, 3),
                metadata={"context": request.context},
            )
            self.store.add(assessment)
            get_risk_metrics().record_assessment(assessment)
            return assessment

    # ── resolution helpers ──────────────────────────────────────

    @staticmethod
    def _resolve_severity(
        change_result: Optional[ChangeDetectionResult],
        impact_report: Optional[ImpactReport],
    ) -> ChangeSeverity:
        if change_result is not None:
            return change_result.diff.overall_severity
        if impact_report is not None:
            mapping = {
                ImpactLevel.CRITICAL: ChangeSeverity.CRITICAL,
                ImpactLevel.HIGH: ChangeSeverity.HIGH,
                ImpactLevel.MEDIUM: ChangeSeverity.MEDIUM,
                ImpactLevel.LOW: ChangeSeverity.LOW,
                ImpactLevel.NEGLIGIBLE: ChangeSeverity.LOW,
            }
            return mapping.get(
                impact_report.impact_level, ChangeSeverity.LOW
            )
        return ChangeSeverity.MEDIUM

    @staticmethod
    def _resolve_category(
        change_result: Optional[ChangeDetectionResult],
    ) -> ChangeCategory:
        if change_result is not None:
            return change_result.diff.overall_category
        return ChangeCategory.OTHER

    @staticmethod
    def _resolve_impact_level(
        impact_report: Optional[ImpactReport],
    ) -> ImpactLevel:
        if impact_report is not None:
            return impact_report.impact_level
        return ImpactLevel.MEDIUM

    @staticmethod
    def _gather_text(
        change_result: Optional[ChangeDetectionResult],
        impact_report: Optional[ImpactReport],
    ) -> str:
        bits: List[str] = []
        if change_result is not None:
            bits.extend(
                c.new_text or "" for c in change_result.diff.changes
            )
            bits.extend(
                c.old_text or "" for c in change_result.diff.changes
            )
        if impact_report is not None:
            for a in impact_report.affected_entities:
                bits.append(a.name)
                bits.append(a.rationale)
        return " ".join(bits)

    @staticmethod
    def _fetch_change_result(diff_id: str) -> Optional[ChangeDetectionResult]:
        try:
            from app.services.change_detection import (
                build_default_change_detection_service,
            )

            svc = build_default_change_detection_service()
            diff = svc.get(diff_id)
            if diff is None:
                return None
            return ChangeDetectionResult(
                diff=diff, affected_sections=[], has_changes=True
            )
        except Exception:  # pragma: no cover
            return None

    @staticmethod
    def _fetch_impact_report(report_id: str) -> Optional[ImpactReport]:
        try:
            from app.services.impact_analysis import (
                build_default_impact_analysis_service,
            )

            svc = build_default_impact_analysis_service()
            return svc.get(report_id)
        except Exception:  # pragma: no cover
            return None

    # ── queries ─────────────────────────────────────────────────

    def get(self, aid: str) -> Optional[RiskAssessment]:
        return self.store.get(aid)

    def search(self, flt: RiskFilter) -> PaginatedRiskAssessments:
        return self.repository.search(flt)

    def stats(self) -> RiskStats:
        return self.repository.stats()

    def history_for(
        self, document_id: Optional[str] = None, source: Optional[str] = None
    ) -> List[RiskAssessment]:
        return self.repository.history_for(document_id, source)

    def trend_for(
        self, document_id: Optional[str] = None
    ) -> RiskTrend:
        return self.repository.trend_for(document_id)


# ─── Factory ────────────────────────────────────────────────────────


def build_default_compliance_risk_service() -> ComplianceRiskService:
    persist = os.path.join(
        settings.STORAGE_ROOT, "compliance_risk", "risk.jsonl"
    )
    store = InMemoryRiskStore(persist_path=persist)
    return ComplianceRiskService(store=store)


__all__ = [
    "RiskScorer",
    "RiskAnalyzer",
    "RiskStore",
    "InMemoryRiskStore",
    "RiskRepository",
    "ComplianceRiskService",
    "build_default_compliance_risk_service",
]
