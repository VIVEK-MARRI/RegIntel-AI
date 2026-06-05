"""Module 7.4 — Regulatory Impact Analysis Engine.

Deterministic, keyword-based impact analysis: no external LLM call.

Public surface
--------------
* ``ImpactScorer``            — score 0..1 → ``ImpactLevel``
* ``AffectedEntityAnalyzer``  — rule-based entity extraction
* ``RegulatorySummaryGenerator`` — executive summary in 3-5 sentences
* ``ImpactReportStore`` (ABC) + ``InMemoryImpactStore`` (JSONL)
* ``ImpactAnalysisRepository``  — search / stats
* ``ImpactAnalysisService``     — DI facade
* ``build_default_impact_analysis_service``
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionRequest,
    ChangeDetectionResult,
    ChangeSeverity,
    ChangeType,
    ClauseChange,
    DocumentDiff,
    SectionRef,
)
from app.schemas.impact import (
    ActionPriority,
    AffectedEntity,
    BusinessImpact,
    ComplianceImpact,
    ExecutiveSummary,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    ImpactAnalysisStats,
    ImpactDimension,
    ImpactFilter,
    ImpactLevel,
    ImpactReport,
    PaginatedImpacts,
    RequiredAction,
)
from app.services.observability import (
    get_impact_analysis_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Keyword tables (deterministic) ──────────────────────────────────


_ENTITY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "bank": (
        "bank",
        "banking company",
        "scheduled bank",
        "commercial bank",
        "cooperative bank",
        "rrb",
        "regional rural bank",
    ),
    "nbfc": (
        "nbfc",
        "non-banking financial company",
        "non banking financial",
        "housing finance company",
        "hfc",
        "microfinance institution",
    ),
    "insurer": (
        "insurer",
        "insurance company",
        "life insurer",
        "general insurer",
        "health insurer",
    ),
    "pension_fund": (
        "pension fund",
        "pfrda",
        "national pension system",
        "nps",
        "subscribers pension",
    ),
    "amc": (
        "asset management company",
        "amc",
        "mutual fund",
        "portfolio manager",
    ),
    "broker_dealer": (
        "stock broker",
        "broker",
        "trading member",
        "clearing member",
        "depository participant",
        "dp",
    ),
    "fintech": (
        "fintech",
        "payment aggregator",
        "payment bank",
        "digital lending",
        "ppi",
        "prepaid payment instrument",
    ),
    "customer": (
        "customer",
        "consumer",
        "depositor",
        "borrower",
        "policyholder",
        "investor",
    ),
    "intermediary": (
        "intermediary",
        "agent",
        "distribution partner",
        "channel partner",
    ),
}


_ENTITY_TYPE_FROM_KEY: Dict[str, str] = {
    "bank": "bank",
    "nbfc": "nbfc",
    "insurer": "insurer",
    "pension_fund": "pension_fund",
    "amc": "amc",
    "broker_dealer": "broker_dealer",
    "fintech": "fintech",
    "customer": "customer",
    "intermediary": "intermediary",
}


# ─── Impact scoring ─────────────────────────────────────────────────


class ImpactScorer:
    """Compute a 0..1 impact score from severity/category/change type."""

    _SEVERITY_WEIGHT: Dict[ChangeSeverity, float] = {
        ChangeSeverity.LOW: 0.2,
        ChangeSeverity.MEDIUM: 0.5,
        ChangeSeverity.HIGH: 0.8,
        ChangeSeverity.CRITICAL: 1.0,
    }
    _CATEGORY_WEIGHT: Dict[ChangeCategory, float] = {
        ChangeCategory.PENALTY_CHANGE: 1.0,
        ChangeCategory.COMPLIANCE_DEADLINE: 0.9,
        ChangeCategory.CAPITAL_REQUIREMENT: 0.9,
        ChangeCategory.REPORTING_REQUIREMENT: 0.8,
        ChangeCategory.REGULATORY_AMENDMENT: 0.7,
        ChangeCategory.NEW_GUIDANCE: 0.6,
        ChangeCategory.SCOPE_CHANGE: 0.7,
        ChangeCategory.POLICY_UPDATE: 0.5,
        ChangeCategory.CLARIFICATION: 0.3,
        ChangeCategory.OTHER: 0.4,
    }
    _CHANGE_TYPE_WEIGHT: Dict[ChangeType, float] = {
        ChangeType.ADDED: 1.0,
        ChangeType.REMOVED: 0.8,
        ChangeType.MODIFIED: 0.7,
        ChangeType.RENUMBERED: 0.2,
        ChangeType.UNCHANGED: 0.0,
    }

    def score(
        self,
        *,
        severity: ChangeSeverity,
        category: ChangeCategory,
        change_type: ChangeType,
        change_count: int,
    ) -> Tuple[float, ImpactLevel]:
        s = self._SEVERITY_WEIGHT.get(severity, 0.3)
        c = self._CATEGORY_WEIGHT.get(category, 0.4)
        t = self._CHANGE_TYPE_WEIGHT.get(change_type, 0.3)
        breadth = min(1.0, change_count / 5.0)
        raw = 0.45 * s + 0.30 * c + 0.15 * t + 0.10 * breadth
        score = max(0.0, min(1.0, raw))
        return score, self._to_level(score)

    @staticmethod
    def _to_level(score: float) -> ImpactLevel:
        if score >= 0.85:
            return ImpactLevel.CRITICAL
        if score >= 0.65:
            return ImpactLevel.HIGH
        if score >= 0.4:
            return ImpactLevel.MEDIUM
        if score >= 0.2:
            return ImpactLevel.LOW
        return ImpactLevel.NEGLIGIBLE


# ─── Affected entity analysis ────────────────────────────────────────


class AffectedEntityAnalyzer:
    """Rule-based extraction of affected entities from change text."""

    def analyze(self, changes: Iterable[ClauseChange]) -> List[AffectedEntity]:
        text = " ".join(
            (c.old_text or "") + " " + (c.new_text or "") for c in changes
        ).lower()
        seen: Dict[str, AffectedEntity] = {}
        for key, kws in _ENTITY_KEYWORDS.items():
            hits = sum(1 for k in kws if k in text)
            if hits == 0:
                continue
            score = min(1.0, hits / max(1, len(kws)))
            ent = AffectedEntity(
                entity_type=_ENTITY_TYPE_FROM_KEY[key],  # type: ignore[arg-type]
                name=key.replace("_", " ").title(),
                rationale=f"Mentioned {hits} keyword(s) in changes",
                exposure_score=score,
            )
            seen[key] = ent
        # Always include 'other' so reports are not empty
        if not seen:
            seen["other"] = AffectedEntity(
                entity_type="other",  # type: ignore[arg-type]
                name="Other",
                rationale="No specific entity keywords detected",
                exposure_score=0.1,
            )
        return list(seen.values())


# ─── Required actions generation ─────────────────────────────────────


def _priority_for_severity(sev: ChangeSeverity) -> ActionPriority:
    if sev == ChangeSeverity.CRITICAL:
        return ActionPriority.P0
    if sev == ChangeSeverity.HIGH:
        return ActionPriority.P1
    if sev == ChangeSeverity.MEDIUM:
        return ActionPriority.P2
    return ActionPriority.P3


def _action_for_category(cat: ChangeCategory, sev: ChangeSeverity) -> RequiredAction:
    pri = _priority_for_severity(sev)
    if cat == ChangeCategory.PENALTY_CHANGE:
        return RequiredAction(
            priority=pri,
            action="Review new penalty structure and update internal control matrix.",
            owner="Compliance Officer",
            rationale="Penalty exposure requires immediate review.",
        )
    if cat == ChangeCategory.COMPLIANCE_DEADLINE:
        return RequiredAction(
            priority=pri,
            action="Capture new deadline in compliance calendar and notify owners.",
            owner="Compliance Officer",
            rationale="Time-bound obligation.",
        )
    if cat == ChangeCategory.REPORTING_REQUIREMENT:
        return RequiredAction(
            priority=pri,
            action="Update reporting templates and align with new requirements.",
            owner="Reporting Lead",
            rationale="Reporting scope changed.",
        )
    if cat == ChangeCategory.CAPITAL_REQUIREMENT:
        return RequiredAction(
            priority=pri,
            action="Re-run capital adequacy calculations and stress tests.",
            owner="Treasury / Risk",
            rationale="Capital requirements changed.",
        )
    if cat == ChangeCategory.SCOPE_CHANGE:
        return RequiredAction(
            priority=pri,
            action="Re-evaluate product/segment scope against new regulation.",
            owner="Product Team",
            rationale="Scope of applicability changed.",
        )
    return RequiredAction(
        priority=pri,
        action="Review the change and document impact in the regulatory log.",
        owner="Compliance Officer",
        rationale="General regulatory update.",
    )


# ─── Business impact (per dimension) ────────────────────────────────


def _business_impacts_for(diff: DocumentDiff) -> List[BusinessImpact]:
    impacts: List[BusinessImpact] = []
    if diff.overall_category == ChangeCategory.PENALTY_CHANGE:
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.FINANCIAL,
                score=0.9,
                description="Direct financial exposure from new penalty clauses.",
            )
        )
    if diff.overall_category == ChangeCategory.COMPLIANCE_DEADLINE:
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.COMPLIANCE,
                score=0.85,
                description="Time-bound compliance obligation.",
            )
        )
    if diff.overall_category == ChangeCategory.REPORTING_REQUIREMENT:
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.OPERATIONAL,
                score=0.7,
                description="Operational impact: reporting cadence / template changes.",
            )
        )
    if diff.overall_category == ChangeCategory.CAPITAL_REQUIREMENT:
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.FINANCIAL,
                score=0.95,
                description="Capital adequacy / balance-sheet impact.",
            )
        )
    if diff.overall_severity in (ChangeSeverity.HIGH, ChangeSeverity.CRITICAL):
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.LEGAL,
                score=0.8,
                description="High-severity legal exposure requiring counsel review.",
            )
        )
    if not impacts:
        impacts.append(
            BusinessImpact(
                dimension=ImpactDimension.OPERATIONAL,
                score=0.3,
                description="Low operational impact.",
            )
        )
    return impacts


def _compliance_impact_for(diff: DocumentDiff) -> ComplianceImpact:
    obligations: List[str] = []
    evidence: List[str] = []
    if diff.overall_category == ChangeCategory.PENALTY_CHANGE:
        obligations.append("Penalty assessment")
        evidence.append("Updated penalty schedule")
    if diff.overall_category == ChangeCategory.COMPLIANCE_DEADLINE:
        obligations.append("Deadline tracking")
        evidence.append("Compliance calendar entries")
    if diff.overall_category == ChangeCategory.REPORTING_REQUIREMENT:
        obligations.append("Reporting")
        evidence.append("New reporting template + sample submission")
    if diff.overall_category == ChangeCategory.CAPITAL_REQUIREMENT:
        obligations.append("Capital adequacy")
        evidence.append("Capital computation worksheet")
    if not obligations:
        obligations.append("General compliance review")
    return ComplianceImpact(
        obligations_affected=obligations,
        evidence_requirements=evidence,
        penalty_exposure=(
            "Elevated"
            if diff.overall_severity
            in (ChangeSeverity.HIGH, ChangeSeverity.CRITICAL)
            else "Standard"
        ),
    )


# ─── Executive summary generator ────────────────────────────────────


class RegulatorySummaryGenerator:
    """Produce a short executive summary from a diff + report."""

    def generate(
        self,
        diff: DocumentDiff,
        entities: List[AffectedEntity],
        level: ImpactLevel,
    ) -> ExecutiveSummary:
        headline = (
            f"{level.value.upper()} impact: "
            f"{diff.overall_category.value} detected in {diff.document_id or 'document'}"
        )
        points: List[str] = [
            f"Detected {diff.added_count} addition(s), {diff.removed_count} removal(s), "
            f"{diff.modified_count} modification(s).",
            f"Overall severity: {diff.overall_severity.value}.",
            f"Overall category: {diff.overall_category.value}.",
        ]
        if entities:
            names = ", ".join(e.name for e in entities[:3])
            points.append(f"Affected entities: {names}.")
        if level in (ImpactLevel.HIGH, ImpactLevel.CRITICAL):
            recommendation = (
                "Escalate to senior compliance leadership and schedule "
                "an impact-review meeting within 7 days."
            )
        elif level == ImpactLevel.MEDIUM:
            recommendation = (
                "Brief the compliance team and incorporate into the next "
                "monthly review cycle."
            )
        else:
            recommendation = "File for record; no immediate action required."
        return ExecutiveSummary(
            headline=headline, key_points=points, recommendation=recommendation
        )


# ─── Store ───────────────────────────────────────────────────────────


class ImpactReportStore(ABC):
    @abstractmethod
    def add_report(self, report: ImpactReport) -> None: ...

    @abstractmethod
    def get_report(self, report_id: str) -> Optional[ImpactReport]: ...

    @abstractmethod
    def list_reports(self) -> List[ImpactReport]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryImpactStore(ImpactReportStore):
    """Thread-safe in-memory impact store with optional JSONL persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._reports: Dict[str, ImpactReport] = {}
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
                        r = ImpactReport(**data)
                        self._reports[r.report_id] = r
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, report: ImpactReport) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(report.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add_report(self, report: ImpactReport) -> None:
        with self._lock:
            self._reports[report.report_id] = report
        self._persist(report)

    def get_report(self, report_id: str) -> Optional[ImpactReport]:
        with self._lock:
            return self._reports.get(report_id)

    def list_reports(self) -> List[ImpactReport]:
        with self._lock:
            return list(self._reports.values())

    def reset(self) -> None:
        with self._lock:
            self._reports.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Repository ──────────────────────────────────────────────────────


class ImpactAnalysisRepository:
    def __init__(self, store: ImpactReportStore) -> None:
        self._store = store

    def add(self, report: ImpactReport) -> None:
        self._store.add_report(report)

    def get(self, report_id: str) -> Optional[ImpactReport]:
        return self._store.get_report(report_id)

    def search(self, flt: ImpactFilter) -> PaginatedImpacts:
        items = self._store.list_reports()
        if flt.document_id:
            items = [r for r in items if r.document_id == flt.document_id]
        if flt.source:
            items = [r for r in items if r.source == flt.source]
        if flt.min_level is not None:
            order = {
                ImpactLevel.NEGLIGIBLE: 0,
                ImpactLevel.LOW: 1,
                ImpactLevel.MEDIUM: 2,
                ImpactLevel.HIGH: 3,
                ImpactLevel.CRITICAL: 4,
            }
            min_rank = order[flt.min_level]
            items = [r for r in items if order[r.impact_level] >= min_rank]
        items.sort(key=lambda r: r.generated_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedImpacts(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> ImpactAnalysisStats:
        all_reports = self._store.list_reports()
        s = ImpactAnalysisStats(total_reports=len(all_reports))
        if not all_reports:
            return s
        total_score = 0.0
        for r in all_reports:
            total_score += r.impact_score
            s.affected_entities_total += len(r.affected_entities)
            s.actions_recommended_total += len(r.required_actions)
            lvl = r.impact_level.value
            s.by_level[lvl] = s.by_level.get(lvl, 0) + 1
            if lvl == "critical":
                s.critical_impact += 1
            elif lvl == "high":
                s.high_impact += 1
            elif lvl == "medium":
                s.medium_impact += 1
            elif lvl == "low":
                s.low_impact += 1
            else:
                s.negligible_impact += 1
            if r.source:
                s.by_source[r.source] = s.by_source.get(r.source, 0) + 1
        s.average_impact_score = total_score / len(all_reports)
        return s


# ─── Service ─────────────────────────────────────────────────────────


class ImpactAnalysisService:
    """DI facade for impact analysis."""

    def __init__(self, store: ImpactReportStore) -> None:
        self.store = store
        self.repository = ImpactAnalysisRepository(store)
        self._scorer = ImpactScorer()
        self._entity_analyzer = AffectedEntityAnalyzer()
        self._summary_generator = RegulatorySummaryGenerator()
        self._lock = threading.Lock()
        self._running = False

    # ── core analyse ───────────────────────────────────────────────

    def analyze(
        self,
        request: ImpactAnalysisRequest,
        diff: Optional[DocumentDiff] = None,
    ) -> ImpactAnalysisResult:
        if not request.diff_id and request.diff is None and diff is None:
            raise ValueError("diff_id or diff is required")
        resolved = diff
        if resolved is None and request.diff is not None:
            try:
                resolved = DocumentDiff(**request.diff)
            except Exception as exc:
                raise ValueError(f"invalid diff payload: {exc}") from exc
        if resolved is None and request.diff_id:
            raise ValueError(
                f"diff_id {request.diff_id!r} not resolved; "
                "pass diff inline or via change_detection service"
            )
        assert resolved is not None
        return self._build_result(
            resolved, document_id=request.document_id, source=request.source
        )

    def _build_result(
        self,
        diff: DocumentDiff,
        *,
        document_id: Optional[str],
        source: Optional[str],
    ) -> ImpactAnalysisResult:
        start = time.time()
        with track_request(endpoint="/api/v1/impact/analyze", strategy="impact_analysis"):
            change_count = max(
                1, diff.added_count + diff.removed_count + diff.modified_count
            )
            score, level = self._scorer.score(
                severity=diff.overall_severity,
                category=diff.overall_category,
                change_type=ChangeType.MODIFIED,
                change_count=change_count,
            )
            entities = self._entity_analyzer.analyze(diff.changes)
            actions: List[RequiredAction] = []
            seen_actions: set = set()
            for c in diff.changes:
                key = (c.change_type.value, c.category.value)
                if key in seen_actions:
                    continue
                seen_actions.add(key)
                actions.append(_action_for_category(c.category, c.severity))
            if not actions:
                actions.append(
                    _action_for_category(
                        diff.overall_category, diff.overall_severity
                    )
                )
            business = _business_impacts_for(diff)
            compliance = _compliance_impact_for(diff)
            exec_summary = self._summary_generator.generate(diff, entities, level)
            rationale = (
                f"Score {score:.2f} derived from severity={diff.overall_severity.value}, "
                f"category={diff.overall_category.value}, change_count={change_count}."
            )
            report = ImpactReport(
                diff_id=diff.diff_id,
                document_id=document_id or diff.document_id,
                source=source or diff.source,
                impact_level=level,
                impact_score=round(score, 4),
                affected_entities=entities,
                required_actions=actions,
                business_impacts=business,
                compliance_impact=compliance,
                executive_summary=exec_summary,
                rationale=rationale,
                generated_at=time.time(),
                duration_ms=0.0,
            )
            report.duration_ms = round((time.time() - start) * 1000.0, 3)
            self.store.add_report(report)
            get_impact_analysis_metrics().record_report(report)
            return ImpactAnalysisResult(report=report, has_impact=level != ImpactLevel.NEGLIGIBLE)

    # ── queries ────────────────────────────────────────────────────

    def get(self, report_id: str) -> Optional[ImpactReport]:
        return self.store.get_report(report_id)

    def search(self, flt: ImpactFilter) -> PaginatedImpacts:
        return self.repository.search(flt)

    def stats(self) -> ImpactAnalysisStats:
        return self.repository.stats()

    def list_all(self) -> List[ImpactReport]:
        return self.store.list_reports()


# ─── Factory ────────────────────────────────────────────────────────


def build_default_impact_analysis_service() -> ImpactAnalysisService:
    persist = os.path.join(settings.STORAGE_ROOT, "impact", "impact.jsonl")
    store = InMemoryImpactStore(persist_path=persist)
    return ImpactAnalysisService(store=store)


__all__ = [
    "ImpactScorer",
    "AffectedEntityAnalyzer",
    "RegulatorySummaryGenerator",
    "ImpactReportStore",
    "InMemoryImpactStore",
    "ImpactAnalysisRepository",
    "ImpactAnalysisService",
    "build_default_impact_analysis_service",
]
