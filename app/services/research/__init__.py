"""Module 7.7 — Agentic Regulatory Research.

Public surface
--------------
* ``ResearchPlanner``             — query → ordered steps
* ``ResearchExecutor``            — execute steps (plan → retrieve → compare → reason → summarize)
* ``ResearchReportGenerator``     — produce final report with citations
* ``ResearchStore`` (ABC) + ``InMemoryResearchStore`` (JSONL)
* ``ResearchService``             — DI facade
* ``build_default_research_service``
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.core.config import settings
from app.schemas.research import (
    CitationSource,
    PaginatedResearchReports,
    ResearchCitation,
    ResearchContext,
    ResearchFilter,
    ResearchKind,
    ResearchPlan,
    ResearchReport,
    ResearchRequest,
    ResearchStats,
    ResearchStep,
    ResearchStepStatus,
    ResearchStepType,
)
from app.services.observability import (
    get_research_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Knowledge provider protocol (pluggable) ────────────────────────


@runtime_checkable
class KnowledgeProviderProtocol(Protocol):
    """Optional pluggable retrieval back-end."""

    def search(
        self, query: str, *, top_k: int = 5
    ) -> List[Dict[str, Any]]: ...

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]: ...


class InMemoryKnowledgeProvider:
    """Deterministic offline knowledge base for research."""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}
        self._next_id = 1

    def add(self, item: Dict[str, Any]) -> str:
        iid = item.get("id") or f"doc-{self._next_id}"
        self._next_id += 1
        item = {**item, "id": iid}
        self._items[iid] = item
        return iid

    def search(self, query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self._items:
            return []
        q = query.lower()
        scored: List[tuple] = []
        for iid, item in self._items.items():
            text = (item.get("title", "") + " " + item.get("body", "")).lower()
            score = sum(1 for tok in q.split() if tok in text)
            if score > 0:
                scored.append((score, iid, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, _, it in scored[:top_k]]

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._items.get(item_id)


# ─── Planner ─────────────────────────────────────────────────────────


class ResearchPlanner:
    """Decompose a research query into a multi-step plan."""

    _TIMELINE_HINTS = (
        "between",
        "from",
        "since",
        "until",
        "by",
        "timeline",
        "history",
        "evolution",
        "over time",
    )
    _COMPARATIVE_HINTS = (
        "compare",
        "versus",
        " vs ",
        " vs.",
        "difference",
        "differences",
        "compare and contrast",
    )
    _CROSS_DOC_HINTS = (
        "across",
        "multiple",
        "cross",
        "all",
        "various",
    )
    _MULTI_HOP_HINTS = (
        "impact on",
        "affects",
        "implications",
        "downstream",
        "ripple",
    )

    _YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

    def plan(self, request: ResearchRequest) -> ResearchPlan:
        plan = ResearchPlan(
            query=request.query,
            kind=request.kind,
            context=request.context,
            created_at=time.time(),
        )
        q_lower = request.query.lower()

        # Default: plan → retrieve → compare → reason → summarize
        if request.kind == ResearchKind.TIMELINE or any(
            h in q_lower for h in self._TIMELINE_HINTS
        ):
            plan.kind = ResearchKind.TIMELINE
            plan.steps = self._timeline_template(request)
        elif request.kind == ResearchKind.COMPARATIVE or any(
            h in q_lower for h in self._COMPARATIVE_HINTS
        ):
            plan.kind = ResearchKind.COMPARATIVE
            plan.steps = self._comparative_template(request)
        elif request.kind == ResearchKind.CROSS_DOCUMENT or any(
            h in q_lower for h in self._CROSS_DOC_HINTS
        ):
            plan.kind = ResearchKind.CROSS_DOCUMENT
            plan.steps = self._cross_document_template(request)
        elif request.kind == ResearchKind.MULTI_HOP or any(
            h in q_lower for h in self._MULTI_HOP_HINTS
        ):
            plan.kind = ResearchKind.MULTI_HOP
            plan.steps = self._multi_hop_template(request)
        else:
            plan.steps = self._general_template(request)

        # Honor max_steps
        if len(plan.steps) > request.max_steps:
            plan.steps = plan.steps[: request.max_steps]
        get_research_metrics().record_plan(len(plan.steps))
        return plan

    def _step(
        self,
        step_type: ResearchStepType,
        description: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> ResearchStep:
        return ResearchStep(
            step_type=step_type,
            description=description,
            inputs=inputs or {},
        )

    def _general_template(self, req: ResearchRequest) -> List[ResearchStep]:
        return [
            self._step(ResearchStepType.PLAN, "Decompose research question"),
            self._step(ResearchStepType.RETRIEVE, "Retrieve relevant documents"),
            self._step(ResearchStepType.REASON, "Synthesize findings"),
            self._step(ResearchStepType.SUMMARIZE, "Produce final report"),
        ]

    def _timeline_template(self, req: ResearchRequest) -> List[ResearchStep]:
        years = self._YEAR_RE.findall(req.query)
        return [
            self._step(
                ResearchStepType.PLAN,
                "Identify time-bounds and key events",
                {"years": years},
            ),
            self._step(ResearchStepType.RETRIEVE, "Retrieve documents in date range"),
            self._step(ResearchStepType.COMPARE, "Order events chronologically"),
            self._step(ResearchStepType.REASON, "Identify patterns and trends"),
            self._step(ResearchStepType.SUMMARIZE, "Produce timeline report"),
        ]

    def _comparative_template(self, req: ResearchRequest) -> List[ResearchStep]:
        return [
            self._step(ResearchStepType.PLAN, "Identify comparison dimensions"),
            self._step(ResearchStepType.RETRIEVE, "Retrieve all relevant items"),
            self._step(ResearchStepType.COMPARE, "Compare items side-by-side"),
            self._step(ResearchStepType.REASON, "Surface key differences"),
            self._step(ResearchStepType.SUMMARIZE, "Produce comparative report"),
        ]

    def _cross_document_template(self, req: ResearchRequest) -> List[ResearchStep]:
        return [
            self._step(ResearchStepType.PLAN, "Map cross-document scope"),
            self._step(
                ResearchStepType.RETRIEVE, "Retrieve documents from each source"
            ),
            self._step(ResearchStepType.COMPARE, "Cross-reference findings"),
            self._step(ResearchStepType.REASON, "Synthesize cross-document insights"),
            self._step(ResearchStepType.SUMMARIZE, "Produce cross-document report"),
        ]

    def _multi_hop_template(self, req: ResearchRequest) -> List[ResearchStep]:
        return [
            self._step(ResearchStepType.PLAN, "Plan multi-hop traversal"),
            self._step(ResearchStepType.RETRIEVE, "First-hop retrieval"),
            self._step(ResearchStepType.REASON, "Identify follow-up entities"),
            self._step(ResearchStepType.RETRIEVE, "Second-hop retrieval"),
            self._step(ResearchStepType.REASON, "Compose impact narrative"),
            self._step(ResearchStepType.SUMMARIZE, "Produce multi-hop report"),
        ]


# ─── Executor ────────────────────────────────────────────────────────


class ResearchExecutor:
    """Execute a plan: run each step, accumulate outputs, collect citations."""

    def __init__(self, provider: Optional[KnowledgeProviderProtocol] = None) -> None:
        self.provider = provider or InMemoryKnowledgeProvider()

    @property
    def knowledge_provider(self) -> KnowledgeProviderProtocol:
        return self.provider

    def execute(
        self,
        plan: ResearchPlan,
        *,
        top_k: int = 5,
    ) -> ResearchPlan:
        start = time.time()
        citations: List[ResearchCitation] = []
        all_outputs: Dict[str, Any] = {"citations": []}
        for step in plan.steps:
            step.started_at = time.time()
            step.status = ResearchStepStatus.RUNNING
            try:
                if step.step_type == ResearchStepType.PLAN:
                    step.outputs = {"plan_steps": len(plan.steps)}
                elif step.step_type == ResearchStepType.RETRIEVE:
                    results = self.provider.search(plan.query, top_k=top_k)
                    step.outputs = {"hits": len(results), "results": results}
                    for r in results:
                        citations.append(
                            ResearchCitation(
                                source=CitationSource.SEARCH,
                                title=r.get("title", "Untitled"),
                                reference=r.get("id", ""),
                                url=r.get("url"),
                                score=r.get("score", 1.0),
                                metadata={
                                    k: v
                                    for k, v in r.items()
                                    if k not in {"id", "title", "url", "score"}
                                },
                            )
                        )
                elif step.step_type == ResearchStepType.COMPARE:
                    step.outputs = {
                        "compared_items": all_outputs.get("hits", 0),
                    }
                elif step.step_type == ResearchStepType.REASON:
                    step.outputs = {
                        "reasoned": True,
                        "citation_count": len(citations),
                    }
                elif step.step_type == ResearchStepType.SUMMARIZE:
                    step.outputs = {"summary_ready": True}
                else:
                    step.outputs = {}
                step.status = ResearchStepStatus.COMPLETED
            except Exception as exc:  # pragma: no cover
                step.status = ResearchStepStatus.FAILED
                step.error = str(exc)
            step.finished_at = time.time()
            step.duration_ms = round(
                (step.finished_at - step.started_at) * 1000.0, 3
            )
            all_outputs[step.step_id] = step.outputs
        duration_ms = round((time.time() - start) * 1000.0, 3)
        plan.metadata = plan.metadata or {}
        plan.metadata["duration_ms"] = duration_ms
        get_research_metrics().record_execute(
            duration_ms=duration_ms, kind=plan.kind.value
        )
        # Stash citations on plan.metadata for the report generator
        plan.metadata["citations"] = [c.model_dump(mode="json") for c in citations]
        return plan


# ─── Report generator ────────────────────────────────────────────────


class ResearchReportGenerator:
    """Compose a final report from an executed plan."""

    def generate(self, plan: ResearchPlan) -> ResearchReport:
        start = time.time()
        with track_request(
            endpoint="/api/v1/research/reports", strategy="research_report"
        ):
            citations: List[ResearchCitation] = [
                ResearchCitation(**c)
                for c in plan.metadata.get("citations", [])
            ]
            summary = self._compose_summary(plan, citations)
            key_findings = self._key_findings(plan, citations)
            timeline = self._timeline_section(plan)
            comparisons = self._comparison_section(plan)
            duration_ms = plan.metadata.get("duration_ms", 0.0)
            report = ResearchReport(
                plan_id=plan.plan_id,
                query=plan.query,
                kind=plan.kind,
                summary=summary,
                key_findings=key_findings,
                timeline=timeline,
                comparisons=comparisons,
                citations=citations,
                steps=plan.steps,
                generated_at=time.time(),
                duration_ms=duration_ms,
                metadata={
                    "step_count": len(plan.steps),
                    "citation_count": len(citations),
                },
            )
            get_research_metrics().record_report()
            return report

    def _compose_summary(
        self, plan: ResearchPlan, citations: List[ResearchCitation]
    ) -> str:
        n_cit = len(citations)
        n_steps = len(plan.steps)
        if plan.kind == ResearchKind.TIMELINE:
            return (
                f"Timeline analysis of {plan.query!r}: {n_cit} sources consulted "
                f"across {n_steps} research steps."
            )
        if plan.kind == ResearchKind.COMPARATIVE:
            return (
                f"Comparative analysis of {plan.query!r}: {n_cit} references "
                f"compared across {n_steps} steps."
            )
        if plan.kind == ResearchKind.CROSS_DOCUMENT:
            return (
                f"Cross-document analysis of {plan.query!r}: {n_cit} citations "
                f"drawn from {n_steps} retrieval steps."
            )
        if plan.kind == ResearchKind.MULTI_HOP:
            return (
                f"Multi-hop analysis of {plan.query!r}: {n_cit} citations "
                f"produced from {n_steps} reasoning steps."
            )
        return (
            f"Research report for {plan.query!r}: {n_cit} citations "
            f"drawn from {n_steps} plan steps."
        )

    def _key_findings(
        self, plan: ResearchPlan, citations: List[ResearchCitation]
    ) -> List[str]:
        findings: List[str] = []
        for c in citations[:5]:
            findings.append(f"Referenced: {c.title}")
        if not findings:
            findings.append("No citations found in this run.")
        return findings

    def _timeline_section(self, plan: ResearchPlan) -> List[Dict[str, Any]]:
        if plan.kind != ResearchKind.TIMELINE:
            return []
        events: List[Dict[str, Any]] = []
        for s in plan.steps:
            if s.step_type == ResearchStepType.RETRIEVE:
                for r in s.outputs.get("results", []):
                    events.append(
                        {
                            "title": r.get("title", ""),
                            "date": r.get("date"),
                            "id": r.get("id"),
                        }
                    )
        return events

    def _comparison_section(self, plan: ResearchPlan) -> List[Dict[str, Any]]:
        if plan.kind != ResearchKind.COMPARATIVE:
            return []
        comps: List[Dict[str, Any]] = []
        for s in plan.steps:
            if s.step_type == ResearchStepType.COMPARE:
                comps.append(
                    {
                        "items_compared": s.outputs.get("compared_items", 0),
                        "step": s.description,
                    }
                )
        return comps


# ─── Store ───────────────────────────────────────────────────────────


class ResearchStore(ABC):
    @abstractmethod
    def add_report(self, report: ResearchReport) -> None: ...

    @abstractmethod
    def get_report(self, report_id: str) -> Optional[ResearchReport]: ...

    @abstractmethod
    def list_reports(self) -> List[ResearchReport]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryResearchStore(ResearchStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._reports: Dict[str, ResearchReport] = {}
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
                        r = ResearchReport(**data)
                        self._reports[r.report_id] = r
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, report: ResearchReport) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(report.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add_report(self, report: ResearchReport) -> None:
        with self._lock:
            self._reports[report.report_id] = report
        self._persist(report)

    def get_report(self, report_id: str) -> Optional[ResearchReport]:
        with self._lock:
            return self._reports.get(report_id)

    def list_reports(self) -> List[ResearchReport]:
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


# ─── Service (DI facade) ────────────────────────────────────────────


class ResearchService:
    """High-level DI facade for the agentic research pipeline."""

    def __init__(
        self,
        store: ResearchStore,
        provider: Optional[KnowledgeProviderProtocol] = None,
        top_k: int = 5,
    ) -> None:
        self.store = store
        self.provider = provider or InMemoryKnowledgeProvider()
        self.planner = ResearchPlanner()
        self.executor = ResearchExecutor(self.provider)
        self.reporter = ResearchReportGenerator()
        self.top_k = top_k

    def run(
        self,
        request: ResearchRequest,
        *,
        top_k: Optional[int] = None,
    ) -> ResearchReport:
        with track_request(
            endpoint="/api/v1/research/run", strategy="research_run"
        ):
            plan = self.planner.plan(request)
            executed = self.executor.execute(plan, top_k=top_k or self.top_k)
            report = self.reporter.generate(executed)
            self.store.add_report(report)
            return report

    def plan_only(self, request: ResearchRequest) -> ResearchPlan:
        return self.planner.plan(request)

    def get(self, report_id: str) -> Optional[ResearchReport]:
        return self.store.get_report(report_id)

    def search(self, flt: ResearchFilter) -> PaginatedResearchReports:
        items = self.store.list_reports()
        if flt.kind:
            items = [r for r in items if r.kind == flt.kind]
        if flt.after is not None:
            items = [r for r in items if r.generated_at >= flt.after]
        if flt.before is not None:
            items = [r for r in items if r.generated_at <= flt.before]
        items.sort(key=lambda r: r.generated_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedResearchReports(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> ResearchStats:
        reports = self.store.list_reports()
        s = ResearchStats(total_reports=len(reports))
        if not reports:
            return s
        total_steps = 0
        total_duration = 0.0
        for r in reports:
            s.by_kind[r.kind.value] = s.by_kind.get(r.kind.value, 0) + 1
            total_steps += len(r.steps)
            total_duration += r.duration_ms
            s.last_report_at = max(s.last_report_at or 0, r.generated_at)
        s.plans_generated = len(reports)
        s.steps_total = total_steps
        s.average_steps_per_plan = total_steps / len(reports)
        s.average_duration_ms = total_duration / len(reports)
        return s

    def list_all(self) -> List[ResearchReport]:
        return self.store.list_reports()

    def add_knowledge_item(self, item: Dict[str, Any]) -> str:
        return self.provider.add(item)

    def reset(self) -> None:
        self.store.reset()


# ─── Factory ────────────────────────────────────────────────────────


def build_default_research_service() -> ResearchService:
    persist = os.path.join(settings.STORAGE_ROOT, "research", "research.jsonl")
    store = InMemoryResearchStore(persist_path=persist)
    return ResearchService(store=store)


__all__ = [
    "KnowledgeProviderProtocol",
    "InMemoryKnowledgeProvider",
    "ResearchPlanner",
    "ResearchExecutor",
    "ResearchReportGenerator",
    "ResearchStore",
    "InMemoryResearchStore",
    "ResearchService",
    "build_default_research_service",
]
