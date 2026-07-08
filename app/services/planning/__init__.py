"""Module 6.4 — Query Planning Engine service.

Public surface
--------------
* :class:`IntentClassifier` — classifies a query into a
  :class:`QueryType` using a small rule-based model (deterministic
  + offline).
* :class:`TaskDecomposer` — turns a query into ordered
  :class:`PlanStepDefinition` instances.
* :class:`StrategySelector` — picks a :class:`PlanStrategy` based on
  the query type + number of expected documents.
* :class:`PlanValidator` — checks dependencies, uniqueness, and basic
  sanity.
* :class:`PlanExplainer` — produces a :class:`PlanExplanation` with
  step-by-step rationale.
* :class:`PlanGenerator` — composes all of the above into an
  :class:`ExecutionPlan`.
* :class:`PlanExecutor` — runs an :class:`ExecutionPlan` against a
  pluggable :class:`RetrieverProtocol` and :class:`ReasonerProtocol`.
* :class:`QueryPlanner` — top-level DI service.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from app.schemas.planning import (
    ExecutionPlan,
    PlanComplexity,
    PlanExecutionResult,
    PlanExplanation,
    PlanStepDefinition,
    PlanStepResult,
    PlanStepStatus,
    PlanStepType,
    PlanStrategy,
    PlanValidationResult,
    QueryPlanRequest,
    QueryType,
)

logger = logging.getLogger(__name__)


# ─── Heuristic intent classification ─────────────────────────────────────


_INTENT_KEYWORDS: Dict[QueryType, List[str]] = {
    QueryType.COMPARISON: [
        "compare",
        "comparison",
        "versus",
        "vs",
        "vs.",
        "difference",
        "differences",
        "differ",
        "contrast",
        "vs ",
        "compared to",
        "compared with",
        "in contrast to",
    ],
    QueryType.TIMELINE: [
        "timeline",
        "evolution",
        "history",
        "chronology",
        "over the years",
        "since",
        "from when",
        "over time",
        "evolution of",
        "progression",
    ],
    QueryType.REGULATORY_CHANGE: [
        "what changed",
        "changes in",
        "amendment",
        "amended",
        "new circular",
        "new regulation",
        "what's new",
        "modified",
        "revised",
        "updated",
        "repealed",
        "superseded",
        "new rules",
    ],
    QueryType.CROSS_DOCUMENT: [
        "across",
        "both rbi and sebi",
        "between rbi and sebi",
        "rbi and sebi",
        "rbi/sebi",
        "all regulators",
        "both regulators",
        "across all",
        "from all",
        "from various",
    ],
    QueryType.MULTI_STEP: [
        "first",
        "then",
        "next",
        "after that",
        "finally",
        "step by step",
        "and then",
        "followed by",
        "subsequently",
    ],
    QueryType.DEFINITION: [
        "what is",
        "what are",
        "define",
        "definition of",
        "meaning of",
        "explain what",
        "tell me about",
        "what does",
        "what do",
    ],
    QueryType.PROCEDURAL: [
        "how to",
        "how do i",
        "procedure",
        "process",
        "steps to",
        "method",
        "approach to",
        "how can i",
        "how should",
    ],
    QueryType.FACTUAL: [
        "when was",
        "when did",
        "when is",
        "where is",
        "who issued",
        "which regulator",
        "date of",
        "year of",
        "how many",
        "how much",
    ],
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


class IntentClassifier:
    """Rule-based query type classifier."""

    def __init__(
        self, *, keyword_map: Optional[Dict[QueryType, List[str]]] = None
    ) -> None:
        self.keyword_map = keyword_map or _INTENT_KEYWORDS

    def classify(self, query: str) -> QueryType:
        q = _normalise(query)
        # Order matters: more specific types win over general ones.
        # Multi-step is checked first because it can contain comparison/
        # timeline markers as sub-tasks.
        for qt in (
            QueryType.MULTI_STEP,
            QueryType.COMPARISON,
            QueryType.REGULATORY_CHANGE,
            QueryType.TIMELINE,
            QueryType.CROSS_DOCUMENT,
            QueryType.DEFINITION,
            QueryType.PROCEDURAL,
            QueryType.FACTUAL,
        ):
            for kw in self.keyword_map.get(qt, []):
                if kw.lower() in q:
                    return qt
        return QueryType.UNKNOWN

    def explain(self, query: str, query_type: QueryType) -> str:
        if query_type == QueryType.UNKNOWN:
            return (
                "No strong intent signal detected — treating as a generic "
                "factual question."
            )
        q = _normalise(query)
        for kw in self.keyword_map.get(query_type, []):
            if kw.lower() in q:
                return (
                    f"Detected the {query_type.value!r} intent because the query "
                    f"contains the phrase {kw!r}."
                )
        return f"Classified as {query_type.value!r} by primary signal matching."


# ─── Task decomposition ───────────────────────────────────────────────────


class TaskDecomposer:
    """Decompose a query into ordered plan steps."""

    def __init__(self, *, classifier: Optional[IntentClassifier] = None) -> None:
        self.classifier = classifier or IntentClassifier()

    def decompose(self, query: str, query_type: QueryType) -> List[PlanStepDefinition]:
        if query_type == QueryType.COMPARISON:
            return self._decompose_comparison(query)
        if query_type == QueryType.TIMELINE:
            return self._decompose_timeline(query)
        if query_type == QueryType.REGULATORY_CHANGE:
            return self._decompose_change(query)
        if query_type == QueryType.CROSS_DOCUMENT:
            return self._decompose_cross(query)
        if query_type == QueryType.MULTI_STEP:
            return self._decompose_multi_step(query)
        if query_type in (
            QueryType.DEFINITION,
            QueryType.PROCEDURAL,
            QueryType.FACTUAL,
        ):
            return self._decompose_simple(query)
        return self._decompose_simple(query)

    # ── Templates ────────────────────────────────────────────────────────

    def _decompose_simple(self, query: str) -> List[PlanStepDefinition]:
        return [
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description=f"Retrieve evidence for: {query[:60]}",
                parameters={"query": query, "top_k": 5},
                expected_output="A set of relevant chunks with citations.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Generate a grounded answer.",
                depends_on=[],  # filled in by generator
                parameters={"query": query},
                expected_output="An executive summary and detailed explanation.",
            ),
        ]

    def _decompose_comparison(self, query: str) -> List[PlanStepDefinition]:
        return [
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve documents for the first entity.",
                parameters={"query": query, "top_k": 5, "focus": "entity_a"},
                expected_output="Chunks for entity A.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve documents for the second entity.",
                parameters={"query": query, "top_k": 5, "focus": "entity_b"},
                expected_output="Chunks for entity B.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.COMPARE,
                description="Compare evidence from both sides.",
                parameters={"query": query},
                expected_output="Structured differences and similarities.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Synthesise a comparison answer.",
                parameters={"query": query},
                expected_output="A side-by-side comparison with citations.",
            ),
        ]

    def _decompose_timeline(self, query: str) -> List[PlanStepDefinition]:
        return [
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve all relevant documents across time.",
                parameters={"query": query, "top_k": 10},
                expected_output="Chronologically-ordered chunks.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.EXTRACT_TIMELINE,
                description="Extract events with dates.",
                parameters={"query": query},
                expected_output="A timeline of regulatory events.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.AGGREGATE,
                description="Aggregate timeline by period.",
                parameters={"query": query},
                expected_output="Grouped timeline by year/period.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Compose a narrative timeline answer.",
                parameters={"query": query},
                expected_output="A narrative timeline summary.",
            ),
        ]

    def _decompose_change(self, query: str) -> List[PlanStepDefinition]:
        return [
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve the latest version of the regulation.",
                parameters={"query": query, "top_k": 5, "version": "latest"},
                expected_output="Latest chunks.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve the previous version (if any).",
                parameters={"query": query, "top_k": 5, "version": "previous"},
                expected_output="Previous chunks.",
                optional=True,
            ),
            PlanStepDefinition(
                step_type=PlanStepType.DETECT_CHANGE,
                description="Detect additions, removals, and modifications.",
                parameters={"query": query},
                expected_output="A list of changes with severity.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Compose a 'what changed' answer.",
                parameters={"query": query},
                expected_output="A 'what changed' summary.",
            ),
        ]

    def _decompose_cross(self, query: str) -> List[PlanStepDefinition]:
        return [
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve from regulator A (RBI).",
                parameters={"query": query, "top_k": 5, "regulator": "RBI"},
                expected_output="RBI chunks.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description="Retrieve from regulator B (SEBI).",
                parameters={"query": query, "top_k": 5, "regulator": "SEBI"},
                expected_output="SEBI chunks.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.DETECT_CONTRADICTION,
                description="Look for contradictions between the two.",
                parameters={"query": query},
                expected_output="List of contradictions (if any).",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.AGGREGATE,
                description="Aggregate the cross-regulator view.",
                parameters={"query": query},
                expected_output="A unified cross-regulator summary.",
            ),
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Compose a cross-document answer.",
                parameters={"query": query},
                expected_output="A cross-document answer.",
            ),
        ]

    def _decompose_multi_step(self, query: str) -> List[PlanStepDefinition]:
        # Split the query on step markers; the rest is a sequential chain.
        parts = re.split(
            r"\b(?:first|then|next|after that|finally|subsequently|followed by)\b",
            query,
            flags=re.IGNORECASE,
        )
        parts = [p.strip(" .,;:") for p in parts if p.strip()]
        if len(parts) < 2:
            return self._decompose_simple(query)
        steps: List[PlanStepDefinition] = []
        prev_ids: List[str] = []
        for i, part in enumerate(parts):
            retrieve = PlanStepDefinition(
                step_type=PlanStepType.RETRIEVE,
                description=f"Step {i+1}: retrieve evidence for: {part[:60]}",
                parameters={"query": part, "top_k": 5, "step": i + 1},
                depends_on=list(prev_ids),
                expected_output=f"Chunks for step {i+1}.",
            )
            aggregate = PlanStepDefinition(
                step_type=PlanStepType.AGGREGATE,
                description=f"Step {i+1}: aggregate evidence.",
                parameters={"step": i + 1},
                depends_on=[retrieve.step_id],
                expected_output=f"Aggregated evidence for step {i+1}.",
                optional=True,
            )
            steps.extend([retrieve, aggregate])
            prev_ids = [aggregate.step_id]
        steps.append(
            PlanStepDefinition(
                step_type=PlanStepType.ANSWER,
                description="Synthesise the multi-step answer.",
                parameters={"query": query},
                depends_on=list(prev_ids),
                expected_output="A multi-step answer.",
            )
        )
        return steps


# ─── Strategy selection ───────────────────────────────────────────────────


class StrategySelector:
    """Pick a :class:`PlanStrategy` from the query type + expected docs."""

    def __init__(self) -> None:
        self._single_doc_types = {
            QueryType.DEFINITION,
            QueryType.FACTUAL,
            QueryType.PROCEDURAL,
        }
        self._multi_doc_types = {
            QueryType.COMPARISON,
            QueryType.CROSS_DOCUMENT,
            QueryType.REGULATORY_CHANGE,
        }

    def select(self, query_type: QueryType, expected_documents: int) -> PlanStrategy:
        if query_type in self._single_doc_types and expected_documents <= 1:
            return PlanStrategy.SINGLE_DOC
        if query_type in self._multi_doc_types:
            return PlanStrategy.MULTI_DOC
        if query_type == QueryType.TIMELINE:
            return PlanStrategy.ITERATIVE
        if query_type == QueryType.MULTI_STEP:
            return PlanStrategy.ITERATIVE
        if expected_documents > 1:
            return PlanStrategy.MULTI_DOC
        return PlanStrategy.EVIDENCE_BASED

    def explain(
        self, query_type: QueryType, expected_documents: int, strategy: PlanStrategy
    ) -> str:
        return (
            f"Selected {strategy.value!r} strategy because the query is of "
            f"type {query_type.value!r} and approximately {expected_documents} "
            f"document(s) are expected to be needed."
        )


# ─── Validation ────────────────────────────────────────────────────────────


class PlanValidator:
    """Validate an :class:`ExecutionPlan`."""

    def validate(self, plan: ExecutionPlan) -> PlanValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        suggestions: List[str] = []
        seen_ids: Dict[str, int] = {}
        for step in plan.steps:
            count = seen_ids.get(step.step_id, 0)
            if count:
                errors.append(
                    f"Duplicate step_id {step.step_id!r} (seen {count + 1} times)."
                )
            seen_ids[step.step_id] = count + 1
        all_ids = set(seen_ids.keys())
        # Validate dependencies.
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in all_ids:
                    errors.append(
                        f"Step {step.step_id!r} depends on missing step {dep!r}."
                    )
        # Cycle check.
        if self._has_cycle(plan):
            errors.append("Plan has a dependency cycle.")
        if not plan.steps:
            errors.append("Plan has no steps.")
        if plan.expected_documents < 1:
            errors.append("`expected_documents` must be >= 1.")
        # Suggestions.
        if plan.query_type == QueryType.COMPARISON and plan.expected_documents < 2:
            warnings.append(
                "Comparison query with < 2 expected documents may be answered "
                "with a single source."
            )
            suggestions.append("Consider raising expected_documents to 2.")
        if plan.strategy == PlanStrategy.SINGLE_DOC and plan.expected_documents > 1:
            warnings.append(
                "Strategy is SINGLE_DOC but expected_documents > 1 — "
                "consider MULTI_DOC."
            )
        return PlanValidationResult(
            plan_id=plan.plan_id,
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    def _has_cycle(self, plan: ExecutionPlan) -> bool:
        state: Dict[str, int] = {s.step_id: 0 for s in plan.steps}  # 0=unvisited
        graph = {s.step_id: s.depends_on for s in plan.steps}

        def visit(node: str) -> bool:
            if state.get(node) == 1:  # visiting → cycle
                return True
            if state.get(node) == 2:
                return False
            state[node] = 1
            for dep in graph.get(node, []):
                if visit(dep):
                    return True
            state[node] = 2
            return False

        for n in list(state.keys()):
            if visit(n):
                return True
        return False


# ─── Explanation ───────────────────────────────────────────────────────────


class PlanExplainer:
    """Produce a :class:`PlanExplanation`."""

    def __init__(
        self,
        *,
        classifier: Optional[IntentClassifier] = None,
        selector: Optional[StrategySelector] = None,
    ) -> None:
        self.classifier = classifier or IntentClassifier()
        self.selector = selector or StrategySelector()

    def explain(self, plan: ExecutionPlan) -> PlanExplanation:
        step_rationale: Dict[str, str] = {}
        for s in plan.steps:
            step_rationale[s.step_id] = (
                f"{s.description} (expected: {s.expected_output or 'n/a'})"
            )
        return PlanExplanation(
            plan_id=plan.plan_id,
            summary=(
                f"Plan to answer a {plan.query_type.value!r} query using the "
                f"{plan.strategy.value!r} strategy across {len(plan.steps)} step(s)."
            ),
            query_type_reason=self.classifier.explain(plan.query, plan.query_type),
            strategy_reason=self.selector.explain(
                plan.query_type, plan.expected_documents, plan.strategy
            ),
            step_rationale=step_rationale,
        )


# ─── Plan generator ────────────────────────────────────────────────────────


class PlanGenerator:
    """Compose an :class:`ExecutionPlan` from a query."""

    def __init__(
        self,
        *,
        classifier: Optional[IntentClassifier] = None,
        decomposer: Optional[TaskDecomposer] = None,
        selector: Optional[StrategySelector] = None,
    ) -> None:
        self.classifier = classifier or IntentClassifier()
        self.decomposer = decomposer or TaskDecomposer(classifier=self.classifier)
        self.selector = selector or StrategySelector()

    def generate(self, request: QueryPlanRequest) -> ExecutionPlan:
        qt = self.classifier.classify(request.query)
        steps = self.decomposer.decompose(request.query, qt)
        # Resolve expected_documents.
        ed = request.expected_documents
        if ed is None:
            ed = self._default_expected_documents(qt)
        # Resolve strategy.
        strategy = self.selector.select(qt, ed)
        # Fill in dependencies for simple plans (the answer step depends on
        # all preceding retrieve/compare/etc. steps).
        steps = self._resolve_dependencies(steps)
        complexity = self._estimate_complexity(len(steps), ed)
        return ExecutionPlan(
            query=request.query,
            query_type=qt,
            strategy=strategy,
            steps=steps,
            estimated_complexity=complexity,
            expected_documents=ed,
            metadata=dict(request.metadata),
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _default_expected_documents(self, qt: QueryType) -> int:
        if qt in (QueryType.COMPARISON, QueryType.CROSS_DOCUMENT):
            return 2
        if qt in (QueryType.TIMELINE, QueryType.REGULATORY_CHANGE):
            return 3
        if qt == QueryType.MULTI_STEP:
            return 3
        return 1

    def _resolve_dependencies(
        self, steps: List[PlanStepDefinition]
    ) -> List[PlanStepDefinition]:
        # If the LAST step is ANSWER and has no depends_on, make it depend
        # on all preceding steps.
        if not steps:
            return steps
        last = steps[-1]
        if last.step_type == PlanStepType.ANSWER and not last.depends_on:
            steps = list(steps)
            steps[-1] = last.model_copy(
                update={"depends_on": [s.step_id for s in steps[:-1]]}
            )
        return steps

    def _estimate_complexity(
        self, step_count: int, expected_documents: int
    ) -> PlanComplexity:
        if step_count <= 2 and expected_documents <= 1:
            return PlanComplexity.SIMPLE
        if step_count <= 5 and expected_documents <= 3:
            return PlanComplexity.MODERATE
        return PlanComplexity.COMPLEX


# ─── Pluggable retriever / reasoner protocols ────────────────────────────


class RetrieverProtocol(Protocol):
    """Pluggable retrieval interface for the executor."""

    async def retrieve(
        self, query: str, *, top_k: int = 5, **kwargs: Any
    ) -> List[Dict[str, Any]]: ...


class ReasonerProtocol(Protocol):
    """Pluggable reasoning interface for the executor."""

    async def reason(
        self, step_type: PlanStepType, *, query: str, **kwargs: Any
    ) -> Dict[str, Any]: ...


# ─── Default retriever / reasoner ──────────────────────────────────────────


class InMemoryRetriever:
    """Default retriever: returns a small set of synthetic chunks.

    Useful for offline operation and tests.  In production this is
    replaced by the HybridRetriever.
    """

    async def retrieve(
        self, query: str, *, top_k: int = 5, **kwargs: Any
    ) -> List[Dict[str, Any]]:
        # Synthesise a single chunk that mentions the query.
        return [
            {
                "chunk_id": f"chunk-{abs(hash(query)) % 10000}",
                "document_id": "doc-default",
                "content": (
                    f"Stub evidence for: {query}. This chunk is provided by "
                    "the default in-memory retriever."
                ),
                "score": 0.5,
                "rank": 1,
            }
        ][: max(1, min(top_k, 1))]


class InMemoryReasoner:
    """Default reasoner: returns a stub result for each step type."""

    async def reason(
        self, step_type: PlanStepType, *, query: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "step_type": step_type.value,
            "query": query,
            "summary": f"Stub output for {step_type.value} step on query: {query!r}.",
            "result": "ok",
        }


# ─── Plan executor ────────────────────────────────────────────────────────


class PlanExecutor:
    """Run an :class:`ExecutionPlan` end-to-end."""

    def __init__(
        self,
        *,
        retriever: Optional[RetrieverProtocol] = None,
        reasoner: Optional[ReasonerProtocol] = None,
        pre_supplied_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.retriever = retriever or InMemoryRetriever()
        self.reasoner = reasoner or InMemoryReasoner()
        self.pre_supplied_chunks = pre_supplied_chunks or []

    async def execute(
        self, plan: ExecutionPlan, *, timeout_sec: float = 60.0
    ) -> PlanExecutionResult:
        start = time.perf_counter()
        results: List[PlanStepResult] = []
        completed: Dict[str, PlanStepResult] = {}
        citations: List[str] = []
        warnings: List[str] = []
        # Topological execution: simple BFS through the plan.
        remaining = list(plan.steps)
        max_iter = len(plan.steps) * 2
        iteration = 0
        while remaining and iteration < max_iter:
            iteration += 1
            progressed = False
            for step in list(remaining):
                if all(dep in completed for dep in step.depends_on):
                    res = await self._run_step(step, completed, citations, warnings)
                    results.append(res)
                    completed[step.step_id] = res
                    remaining.remove(step)
                    progressed = True
            if not progressed:
                # Deps missing — bail out.
                for step in remaining:
                    results.append(
                        PlanStepResult(
                            step_id=step.step_id,
                            step_type=step.step_type,
                            status=PlanStepStatus.SKIPPED,
                            error="missing dependencies",
                        )
                    )
                break
        # Final status.
        if any(r.status == PlanStepStatus.FAILED for r in results):
            status = PlanStepStatus.FAILED
        elif all(r.status == PlanStepStatus.SUCCESS for r in results):
            status = PlanStepStatus.SUCCESS
        else:
            status = PlanStepStatus.SUCCESS  # partial is still useful
        # Compose final_output.
        final = self._compose_final_output(plan, results)
        total_ms = (time.perf_counter() - start) * 1000.0
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            query=plan.query,
            query_type=plan.query_type,
            strategy=plan.strategy,
            step_results=results,
            status=status,
            final_output=final,
            total_latency_ms=total_ms,
            citations=citations,
            warnings=warnings,
        )

    async def _run_step(
        self,
        step: PlanStepDefinition,
        completed: Dict[str, PlanStepResult],
        citations: List[str],
        warnings: List[str],
    ) -> PlanStepResult:
        start = time.perf_counter()
        try:
            if step.step_type == PlanStepType.RETRIEVE:
                output = await self._do_retrieve(step)
            elif step.step_type == PlanStepType.AGGREGATE:
                output = self._do_aggregate(step, completed)
            elif step.step_type == PlanStepType.ANSWER:
                output = self._do_answer(step, completed)
            else:
                output = await self._do_reason(step, completed)
            # Collect citations.
            for cid in output.get("citations", []):
                if cid not in citations:
                    citations.append(cid)
            for w in output.get("warnings", []):
                if w not in warnings:
                    warnings.append(w)
            latency = (time.perf_counter() - start) * 1000.0
            return PlanStepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status=PlanStepStatus.SUCCESS,
                output=output,
                latency_ms=latency,
            )
        except Exception as exc:  # pragma: no cover
            latency = (time.perf_counter() - start) * 1000.0
            status = (
                PlanStepStatus.FAILED if not step.optional else PlanStepStatus.SKIPPED
            )
            return PlanStepResult(
                step_id=step.step_id,
                step_type=step.step_type,
                status=status,
                error=str(exc),
                latency_ms=latency,
            )

    async def _do_retrieve(self, step: PlanStepDefinition) -> Dict[str, Any]:
        params = dict(step.parameters)
        query = params.pop("query", "")
        top_k = int(params.pop("top_k", 5))
        if self.pre_supplied_chunks:
            chunks = list(self.pre_supplied_chunks)
        else:
            chunks = await self.retriever.retrieve(query, top_k=top_k, **params)
        # Pull chunk_ids as citations.
        citations = [str(c.get("chunk_id", "")) for c in chunks if c.get("chunk_id")]
        return {"chunks": chunks, "citations": citations, "count": len(chunks)}

    def _do_aggregate(
        self, step: PlanStepDefinition, completed: Dict[str, PlanStepResult]
    ) -> Dict[str, Any]:
        inputs = [
            completed[d].output
            for d in step.depends_on
            if d in completed and completed[d].output
        ]
        merged: List[Dict[str, Any]] = []
        for inp in inputs:
            if isinstance(inp, dict) and "chunks" in inp:
                merged.extend(inp["chunks"])
        return {"aggregated": merged, "count": len(merged)}

    def _do_answer(
        self, step: PlanStepDefinition, completed: Dict[str, PlanStepResult]
    ) -> Dict[str, Any]:
        # Compose a "final" answer from all preceding outputs.
        all_chunks: List[Dict[str, Any]] = []
        all_citations: List[str] = []
        for d, r in completed.items():
            if r.output:
                if "chunks" in r.output:
                    all_chunks.extend(r.output["chunks"])
                for cid in r.output.get("citations", []):
                    if cid not in all_citations:
                        all_citations.append(cid)
        return {
            "answer": {
                "query": step.parameters.get("query", ""),
                "evidence_chunks": all_chunks[:10],
            },
            "citations": all_citations,
        }

    async def _do_reason(
        self,
        step: PlanStepDefinition,
        completed: Dict[str, PlanStepResult],
    ) -> Dict[str, Any]:
        params = dict(step.parameters)
        params["upstream"] = {
            d: completed[d].output for d in step.depends_on if d in completed
        }
        return await self.reasoner.reason(
            step.step_type, query=step.parameters.get("query", ""), **params
        )

    def _compose_final_output(
        self, plan: ExecutionPlan, results: List[PlanStepResult]
    ) -> Dict[str, Any]:
        # Prefer the output of the last ANSWER step; fall back to the
        # last successful output.
        for r in reversed(results):
            if r.step_type == PlanStepType.ANSWER and r.output:
                return r.output
        for r in reversed(results):
            if r.output:
                return r.output
        return {}


# ─── Top-level QueryPlanner ──────────────────────────────────────────────


class QueryPlanner:
    """Top-level DI-friendly service."""

    def __init__(
        self,
        *,
        generator: Optional[PlanGenerator] = None,
        validator: Optional[PlanValidator] = None,
        explainer: Optional[PlanExplainer] = None,
        executor: Optional[PlanExecutor] = None,
        retriever: Optional[RetrieverProtocol] = None,
        reasoner: Optional[ReasonerProtocol] = None,
    ) -> None:
        self.generator = generator or PlanGenerator()
        self.validator = validator or PlanValidator()
        self.explainer = explainer or PlanExplainer()
        # Default executor uses the pluggable retriever / reasoner.
        self.executor = executor or PlanExecutor(retriever=retriever, reasoner=reasoner)

    def plan(
        self, request: QueryPlanRequest
    ) -> tuple[ExecutionPlan, PlanValidationResult, PlanExplanation]:
        plan = self.generator.generate(request)
        validation = self.validator.validate(plan)
        explanation = self.explainer.explain(plan)
        return plan, validation, explanation

    async def plan_and_execute(
        self, request: QueryPlanRequest
    ) -> tuple[
        ExecutionPlan, PlanValidationResult, PlanExplanation, PlanExecutionResult
    ]:
        plan, validation, explanation = self.plan(request)
        # If pre-supplied chunks are present, share them with the executor.
        executor = self.executor
        if request.chunks:
            executor = PlanExecutor(
                retriever=executor.retriever,
                reasoner=executor.reasoner,
                pre_supplied_chunks=list(request.chunks),
            )
        execution = await executor.execute(plan, timeout_sec=request.timeout_sec)
        return plan, validation, explanation, execution


def build_default_query_planner() -> QueryPlanner:
    return QueryPlanner()


__all__ = [
    "ExecutionPlan",
    "InMemoryReasoner",
    "InMemoryRetriever",
    "IntentClassifier",
    "PlanComplexity",
    "PlanExecutionResult",
    "PlanExplanation",
    "PlanExecutor",
    "PlanExplainer",
    "PlanGenerator",
    "PlanStepDefinition",
    "PlanStepResult",
    "PlanStepStatus",
    "PlanStepType",
    "PlanStrategy",
    "PlanValidator",
    "QueryPlanner",
    "QueryType",
    "ReasonerProtocol",
    "RetrieverProtocol",
    "StrategySelector",
    "TaskDecomposer",
    "build_default_query_planner",
]
