"""Canonical Intelligence Pipeline (Module 10).

The :class:`IntelligencePipeline` drives the full end-to-end regulatory
intelligence workflow in one call:

  Query → Hybrid Retrieval → Evidence Collection → Answer Generation →
  Citation → Confidence Scoring → Hallucination Check →
  Confidence Routing (abstain | review | return) → Audit Trail

Design decisions
----------------
* Reuses ALL existing M4-M8 services — no code duplication.
* Confidence routing is explicit and traceable (audit record captures the
  routing decision and the reason).
* Abstention is a first-class outcome: when there is insufficient evidence
  the pipeline returns a structured abstention rather than a fabricated answer.
* The pipeline is intentionally synchronous at the service layer; async I/O
  is handled by the FastAPI endpoint that wraps it.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.schemas.intelligence import (
    AnswerSection,
    CitationItem,
    ConfidenceBreakdown,
    EvidenceChunk,
    IntelligenceQueryRequest,
    IntelligenceQueryResponse,
)

logger = logging.getLogger(__name__)


# ─── Result ──────────────────────────────────────────────────────────────────


@dataclass
class PipelineContext:
    """Mutable pipeline state threaded through each stage."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    query: str = ""
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_scores: List[float] = field(default_factory=list)
    reranker_scores: Optional[List[float]] = None
    answer: Optional[Dict[str, Any]] = None
    citations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    confidence_level: str = "LOW"
    confidence_flags: List[str] = field(default_factory=list)
    confidence_breakdown: Optional[Dict[str, Any]] = None
    hallucination_detected: Optional[bool] = None
    faithfulness_score: Optional[float] = None
    abstained: bool = False
    requires_review: bool = False
    governance_task_id: Optional[str] = None
    audit_record_id: Optional[str] = None
    workflow_output: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    stage_latencies: Dict[str, float] = field(default_factory=dict)


# ─── Pipeline ─────────────────────────────────────────────────────────────────


class IntelligencePipeline:
    """End-to-end regulatory intelligence pipeline.

    Composes M4 retrieval, M5 answer generation + confidence + hallucination,
    M8.6 governance, and M8.7 audit into a single coherent workflow.

    Parameters
    ----------
    hybrid_retriever:
        M4 hybrid retrieval service (dense + BM25 + rerank).
    answer_generator:
        M5.1 answer generation service.
    citation_service:
        M5.2 citation engine.
    confidence_service:
        M5.3 confidence scoring service.
    hallucination_guard:
        M5.4 hallucination detection service.
    governance_service:
        M8.6 AI governance service (optional).
    audit_service:
        M8.7 audit service (optional).
    """

    def __init__(
        self,
        *,
        hybrid_retriever=None,
        answer_generator=None,
        citation_service=None,
        confidence_service=None,
        hallucination_guard=None,
        governance_service=None,
        audit_service=None,
        # Thresholds — can be overridden per-instance for testing
        confidence_threshold_high: float | None = None,
        confidence_threshold_low: float | None = None,
        abstention_threshold: float | None = None,
    ) -> None:
        self._hybrid_retriever = hybrid_retriever
        self._answer_generator = answer_generator
        self._citation_service = citation_service
        self._confidence_service = confidence_service
        self._hallucination_guard = hallucination_guard
        self._governance_service = governance_service
        self._audit_service = audit_service

        self._threshold_high = (
            confidence_threshold_high
            if confidence_threshold_high is not None
            else settings.CONFIDENCE_THRESHOLD_HIGH
        )
        self._threshold_low = (
            confidence_threshold_low
            if confidence_threshold_low is not None
            else settings.CONFIDENCE_THRESHOLD_LOW
        )
        self._abstention_threshold = (
            abstention_threshold
            if abstention_threshold is not None
            else settings.ABSTENTION_THRESHOLD
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(
        self,
        request: IntelligenceQueryRequest,
        *,
        db_session=None,
    ) -> IntelligenceQueryResponse:
        """Execute the full intelligence pipeline and return a structured response."""
        t0 = time.perf_counter()
        ctx = PipelineContext(query=request.query)

        try:
            # Stage 1: Retrieve evidence
            await self._stage_retrieve(ctx, request, db_session=db_session)

            # Stage 2: Generate answer (or abstain if no evidence)
            if not ctx.evidence and ctx.confidence < self._abstention_threshold:
                self._stage_abstain(ctx, reason="no_evidence")
            else:
                await self._stage_generate(ctx, request)

                # Stage 3: Citation
                self._stage_cite(ctx)

                # Stage 4: Confidence scoring
                self._stage_confidence(ctx, request)

                # Stage 5: Hallucination check
                await self._stage_hallucination(ctx)

                # Stage 6: Confidence routing
                self._stage_route(ctx)

                # Stage 6b: Optional agent workflow enrichment
                # ('research' | 'compliance' | 'risk')
                await self._stage_workflow(ctx, request)

            # Stage 7: Audit trail (always runs)
            self._stage_audit(ctx)

        except Exception as exc:
            logger.error(
                "intelligence.pipeline run_id=%s error: %s", ctx.run_id, exc, exc_info=True
            )
            ctx.errors.append(str(exc))
            # Degrade gracefully: ensure we have a usable answer
            if ctx.answer is None:
                ctx.answer = {
                    "executive_summary": (
                        "An internal error occurred while processing your query. "
                        "Please try again or contact support."
                    ),
                    "detailed_explanation": "",
                    "supporting_evidence": [],
                    "key_regulatory_references": [],
                    "compliance_implications": "",
                    "recommended_actions": "",
                    "caveats": f"Pipeline error: {type(exc).__name__}",
                }
                ctx.confidence = 0.0
                ctx.confidence_level = "LOW"
                ctx.requires_review = True

        total_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            "intelligence.pipeline run_id=%s confidence=%.3f abstained=%s "
            "requires_review=%s latency=%.1fms evidence=%d errors=%d",
            ctx.run_id,
            ctx.confidence,
            ctx.abstained,
            ctx.requires_review,
            total_ms,
            len(ctx.evidence),
            len(ctx.errors),
        )

        return self._build_response(ctx, total_ms)

    # ── Stages ────────────────────────────────────────────────────────────────

    async def _stage_retrieve(
        self,
        ctx: PipelineContext,
        request: IntelligenceQueryRequest,
        *,
        db_session=None,
    ) -> None:
        """Stage 1: Hybrid retrieval (dense + BM25 + rerank)."""
        t0 = time.perf_counter()
        try:
            top_k = request.top_k or settings.INTELLIGENCE_TOP_K
            # Coerce the user-supplied source filter to SourceEnum
            # (case-insensitive). A raw string would silently miss the
            # enum comparison downstream — fail soft to "all sources"
            # instead of returning empty evidence.
            source = None
            if request.source_filter and len(request.source_filter) == 1:
                from app.models.document import SourceEnum

                raw = str(request.source_filter[0]).strip()
                try:
                    source = SourceEnum(raw.upper())
                except ValueError:
                    ctx.errors.append(
                        f"source_filter: unknown source {raw!r}; searched all sources"
                    )
                    source = None
            if self._hybrid_retriever is not None:
                search_resp = await self._hybrid_retriever.search(
                    query=request.query,
                    top_k=top_k,
                    rerank_score_threshold=request.score_threshold,
                    source=source,
                    active_only=request.active_only,
                )
                results = search_resp.results if hasattr(search_resp, "results") else []
                ctx.evidence = []
                ctx.retrieval_scores = []
                ctx.reranker_scores = []
                for r in results:
                    chunk_id = getattr(r, "chunk_id", None) or (r.get("chunk_id") if isinstance(r, dict) else None)
                    content = getattr(r, "content", None) or (r.get("content") if isinstance(r, dict) else "")
                    
                    score = getattr(r, "rerank_score", None) or getattr(r, "score", None) or getattr(r, "original_score", 0.0)
                    if isinstance(r, dict):
                        score = r.get("rerank_score") or r.get("score") or r.get("original_score") or score
                    score = float(score or 0.0)
                    
                    meta = getattr(r, "metadata", {}) or (r.get("metadata", {}) if isinstance(r, dict) else {})
                    meta_dict = dict(meta or {})
                    
                    doc_id = getattr(r, "document_id", None) or meta_dict.get("document_id")
                    if isinstance(r, dict) and not doc_id:
                        doc_id = r.get("document_id")
                    
                    source = getattr(r, "source", None) or meta_dict.get("source")
                    if isinstance(r, dict) and not source:
                        source = r.get("source")
                        
                    section = getattr(r, "section", None) or meta_dict.get("section")
                    if isinstance(r, dict) and not section:
                        section = r.get("section")
                        
                    subsection = getattr(r, "subsection", None) or meta_dict.get("subsection")
                    if isinstance(r, dict) and not subsection:
                        subsection = r.get("subsection")
                        
                    page_num = getattr(r, "page_number", None) or meta_dict.get("page_number")
                    if isinstance(r, dict) and not page_num:
                        page_num = r.get("page_number")
                    if page_num is not None:
                        try:
                            page_num = int(page_num)
                        except ValueError:
                            page_num = None

                    ctx.evidence.append({
                        "chunk_id": str(chunk_id or ""),
                        "document_id": str(doc_id or "") or None,
                        "content": str(content or ""),
                        "score": score,
                        "source": str(source or "") or None,
                        "section": str(section or "") or None,
                        "subsection": str(subsection or "") or None,
                        "page_number": page_num,
                        "metadata": meta_dict,
                    })
                    ctx.retrieval_scores.append(score)
                    
                    r_score = getattr(r, "rerank_score", None)
                    if isinstance(r, dict) and r_score is None:
                        r_score = r.get("rerank_score")
                    if r_score is not None:
                        ctx.reranker_scores.append(float(r_score))
        except Exception as exc:
            logger.warning("intelligence.retrieve failed: %s", exc)
            ctx.errors.append(f"retrieval: {exc}")
        finally:
            ctx.stage_latencies["retrieve"] = (time.perf_counter() - t0) * 1000.0


    async def _stage_generate(
        self,
        ctx: PipelineContext,
        request: IntelligenceQueryRequest,
    ) -> None:
        """Stage 2: LLM answer generation."""
        t0 = time.perf_counter()
        try:
            if self._answer_generator is not None:
                from app.schemas.answer_generation import AnswerGenerationRequest, RetrievedChunk
                retrieved_chunks = []
                for idx, e in enumerate(ctx.evidence):
                    retrieved_chunks.append(RetrievedChunk(
                        chunk_id=str(e.get("chunk_id", "")),
                        document_id=str(e.get("document_id", "") or "00000000-0000-0000-0000-000000000000"),
                        content=str(e.get("content", "")),
                        score=float(e.get("score", 0.0)),
                        source=e.get("source"),
                        page_number=e.get("page_number"),
                        section=e.get("section"),
                        subsection=e.get("subsection"),
                        rank=idx + 1,
                    ))
                gen_req = AnswerGenerationRequest(
                    query=request.query,
                    chunks=retrieved_chunks,
                    provider=settings.LLM_PROVIDER,
                    model=settings.LLM_MODEL,
                )
                gen_response = await self._answer_generator.generate(gen_req)
                # Normalise to dict
                if hasattr(gen_response, "answer"):
                    a = gen_response.answer
                    ctx.answer = (
                        a.model_dump() if hasattr(a, "model_dump") else dict(a)
                    ) if a else {}
                elif hasattr(gen_response, "model_dump"):
                    ctx.answer = gen_response.model_dump()
                else:
                    ctx.answer = dict(gen_response) if gen_response else {}
                
                # Normalize supporting_evidence to list of chunk IDs (strings)
                if ctx.answer and "supporting_evidence" in ctx.answer:
                    se = ctx.answer["supporting_evidence"]
                    if isinstance(se, list):
                        normalized_se = []
                        for item in se:
                            if isinstance(item, dict):
                                normalized_se.append(str(item.get("chunk_id") or ""))
                            elif hasattr(item, "chunk_id"):
                                normalized_se.append(str(getattr(item, "chunk_id")))
                            else:
                                normalized_se.append(str(item))
                        ctx.answer["supporting_evidence"] = normalized_se
            else:
                # No generator available — produce a descriptive answer from evidence
                ctx.answer = self._fallback_answer(request.query, ctx.evidence)
        except Exception as exc:
            logger.warning("intelligence.generate failed: %s", exc)
            ctx.errors.append(f"generation: {exc}")
            ctx.answer = self._fallback_answer(request.query, ctx.evidence)
        finally:
            ctx.stage_latencies["generate"] = (time.perf_counter() - t0) * 1000.0

    @staticmethod
    def _build_gen_answer(answer: Dict[str, Any], retrieved_chunks: list):
        """Build a citation/hallucination-compatible AnswerSection.

        supporting_evidence must be EvidenceChunk OBJECTS (chunk_id /
        document_id / excerpt), never bare chunk-id strings — and this
        schema only accepts its 4 canonical fields (extra="forbid").
        """
        from app.schemas.answer_generation import (
            AnswerSection as GenAnswerSection,
            EvidenceChunk as GenEvidenceChunk,
        )

        by_id = {rc.chunk_id: rc for rc in retrieved_chunks}
        evidence_objs = []
        for item in answer.get("supporting_evidence", []) or []:
            cid = (
                item.get("chunk_id")
                if isinstance(item, dict)
                else getattr(item, "chunk_id", None)
            ) or str(item)
            rc = by_id.get(str(cid))
            if rc is None:
                continue
            evidence_objs.append(
                GenEvidenceChunk(
                    chunk_id=rc.chunk_id,
                    document_id=rc.document_id,
                    source=(
                        rc.source.value
                        if hasattr(rc.source, "value")
                        else rc.source
                    ),
                    page_number=rc.page_number,
                    section=rc.section,
                    excerpt=rc.content[:500],
                )
            )
        return GenAnswerSection(
            executive_summary=answer.get("executive_summary", ""),
            detailed_explanation=answer.get("detailed_explanation", ""),
            supporting_evidence=evidence_objs,
            key_regulatory_references=answer.get("key_regulatory_references", []),
        )

    def _stage_cite(self, ctx: PipelineContext) -> None:
        """Stage 3: Citation extraction."""
        t0 = time.perf_counter()
        try:
            if self._citation_service is not None and ctx.answer and ctx.evidence:
                from app.schemas.citation import CitationRequest
                from app.schemas.answer_generation import RetrievedChunk

                retrieved_chunks = []
                for idx, e in enumerate(ctx.evidence):
                    retrieved_chunks.append(RetrievedChunk(
                        chunk_id=str(e.get("chunk_id", "")),
                        document_id=str(e.get("document_id", "") or "00000000-0000-0000-0000-000000000000"),
                        content=str(e.get("content", "")),
                        score=float(e.get("score", 0.0)),
                        source=e.get("source"),
                        page_number=e.get("page_number"),
                        section=e.get("section"),
                        subsection=e.get("subsection"),
                        rank=idx + 1,
                    ))

                gen_answer = self._build_gen_answer(ctx.answer, retrieved_chunks)

                cite_req = CitationRequest(
                    query=ctx.query,
                    answer=gen_answer,
                    chunks=retrieved_chunks,
                )
                cite_resp = self._citation_service.cite(cite_req)
                # cite() returns CitationResponse(query, annotated_answer,
                # coverage, metadata) — the inline citations live inside
                # annotated_answer.{executive_summary,detailed_explanation}.
                # (Legacy branches kept for backwards compatibility.)
                inline = []
                annotated = getattr(cite_resp, "annotated_answer", None)
                if annotated is not None:
                    for section in (
                        getattr(annotated, "executive_summary", None),
                        getattr(annotated, "detailed_explanation", None),
                    ):
                        inline.extend(getattr(section, "citations", None) or [])
                if inline:
                    by_chunk = {
                        str(e.get("chunk_id", "")): e for e in ctx.evidence
                    }
                    ctx.citations = []
                    for c in inline:
                        d = (
                            c.model_dump()
                            if hasattr(c, "model_dump")
                            else dict(c)
                        )
                        ev = by_chunk.get(str(d.get("chunk_id", ""))) or {}
                        ctx.citations.append(
                            {
                                "citation_id": d.get("citation_id"),
                                "chunk_id": d.get("chunk_id"),
                                "claim_id": d.get("claim_id"),
                                "excerpt": d.get("marker"),
                                "relevance_score": d.get("similarity"),
                                "document_id": ev.get("document_id"),
                                "document_title": (
                                    ev.get("metadata", {}) or {}
                                ).get("document_title"),
                                "source": ev.get("source"),
                                "section": ev.get("section"),
                                "page_number": ev.get("page_number"),
                            }
                        )
                elif hasattr(cite_resp, "citations"):
                    ctx.citations = [
                        c.model_dump() if hasattr(c, "model_dump") else dict(c)
                        for c in cite_resp.citations
                    ]
                elif isinstance(cite_resp, list):
                    ctx.citations = [
                        c.model_dump() if hasattr(c, "model_dump") else dict(c)
                        for c in cite_resp
                    ]
        except Exception as exc:
            logger.warning("intelligence.cite failed: %s", exc)
            ctx.errors.append(f"citation: {exc}")
        finally:
            ctx.stage_latencies["cite"] = (time.perf_counter() - t0) * 1000.0

    def _stage_confidence(
        self,
        ctx: PipelineContext,
        request: IntelligenceQueryRequest,
    ) -> None:
        """Stage 4: Multi-factor confidence scoring."""
        t0 = time.perf_counter()
        try:
            if self._confidence_service is not None:
                conf_resp = self._confidence_service.score_answer(
                    query=request.query,
                    answer=ctx.answer or {},
                    chunks=ctx.evidence,
                    retrieval_scores=ctx.retrieval_scores or None,
                    reranker_scores=ctx.reranker_scores,
                )
                ctx.confidence = float(conf_resp.confidence)
                ctx.confidence_level = conf_resp.level.value if hasattr(conf_resp.level, "value") else str(conf_resp.level)
                ctx.confidence_flags = [
                    f.value if hasattr(f, "value") else str(f)
                    for f in (conf_resp.flags or [])
                ]
                if hasattr(conf_resp, "breakdown") and conf_resp.breakdown:
                    bd = conf_resp.breakdown
                    raw = (
                        bd.model_dump() if hasattr(bd, "model_dump") else dict(bd)
                    )
                    # The confidence service reports {factors: [{name, score,
                    # ...}], weights, total_weight}; the intelligence response
                    # needs the flat per-factor fields. Translate by factor
                    # name so explainability actually reaches the client.
                    translated = {}
                    for f in raw.get("factors", []) or []:
                        name = (
                            f.get("name").value
                            if hasattr(f.get("name"), "value")
                            else str(f.get("name", ""))
                        )
                        try:
                            translated[name] = float(f.get("score", 0.0))
                        except (TypeError, ValueError):
                            continue
                    if translated:
                        ctx.confidence_breakdown = translated
                    else:
                        # Already in flat form (or unknown shape) — pass through
                        # and let _build_response validate.
                        ctx.confidence_breakdown = raw
        except Exception as exc:
            logger.warning("intelligence.confidence failed: %s", exc)
            ctx.errors.append(f"confidence: {exc}")
        finally:
            ctx.stage_latencies["confidence"] = (time.perf_counter() - t0) * 1000.0

    async def _stage_hallucination(self, ctx: PipelineContext) -> None:
        """Stage 5: Hallucination / faithfulness check."""
        t0 = time.perf_counter()
        try:
            if self._hallucination_guard is not None and ctx.answer and ctx.evidence:
                from app.schemas.hallucination import FaithfulnessRequest, VerificationMethod
                from app.schemas.answer_generation import RetrievedChunk

                retrieved_chunks = []
                for idx, e in enumerate(ctx.evidence):
                    retrieved_chunks.append(RetrievedChunk(
                        chunk_id=str(e.get("chunk_id", "")),
                        document_id=str(e.get("document_id", "") or "00000000-0000-0000-0000-000000000000"),
                        content=str(e.get("content", "")),
                        score=float(e.get("score", 0.0)),
                        source=e.get("source"),
                        page_number=e.get("page_number"),
                        section=e.get("section"),
                        subsection=e.get("subsection"),
                        rank=idx + 1,
                    ))

                gen_answer = self._build_gen_answer(ctx.answer, retrieved_chunks)

                method = VerificationMethod.MOCK if settings.LLM_PROVIDER == "mock" else VerificationMethod.LLM
                
                hall_req = FaithfulnessRequest(
                    query=ctx.query,
                    answer=gen_answer,
                    chunks=retrieved_chunks,
                    method=method,
                )
                hall_resp = await self._hallucination_guard.verify(hall_req)
                if hasattr(hall_resp, "report") and hall_resp.report:
                    rpt = hall_resp.report
                    ctx.hallucination_detected = getattr(rpt, "hallucination_detected", None)
                    ctx.faithfulness_score = getattr(rpt, "faithfulness_score", None)
                elif hasattr(hall_resp, "hallucination_detected"):
                    ctx.hallucination_detected = hall_resp.hallucination_detected
                    ctx.faithfulness_score = getattr(hall_resp, "faithfulness_score", None)
        except Exception as exc:
            logger.warning("intelligence.hallucination failed: %s", exc)
            ctx.errors.append(f"hallucination: {exc}")
        finally:
            ctx.stage_latencies["hallucination"] = (time.perf_counter() - t0) * 1000.0

    def _stage_route(self, ctx: PipelineContext) -> None:
        """Stage 6: Route based on confidence thresholds.

        HIGH (>= threshold_high)   → return directly
        MEDIUM (threshold_low <= c < threshold_high) → flag requires_review
        LOW (abstention <= c < threshold_low)        → flag requires_review, create governance task
        ABSTAIN (< abstention_threshold)             → set abstained=True
        """
        t0 = time.perf_counter()
        try:
            c = ctx.confidence
            if c >= self._threshold_high:
                # High confidence — no action required
                pass
            elif c >= self._threshold_low:
                # Medium confidence — advisory flag only
                ctx.requires_review = True
                logger.info(
                    "intelligence.route run_id=%s confidence=%.3f → requires_review",
                    ctx.run_id,
                    c,
                )
            elif c >= self._abstention_threshold:
                # Low confidence — create governance review task
                ctx.requires_review = True
                ctx.governance_task_id = self._create_governance_task(ctx)
                logger.info(
                    "intelligence.route run_id=%s confidence=%.3f → governance review task=%s",
                    ctx.run_id,
                    c,
                    ctx.governance_task_id,
                )
            else:
                # Below abstention threshold
                if not ctx.evidence:
                    self._stage_abstain(ctx, reason="low_confidence_no_evidence")
                else:
                    # Has some evidence but very low confidence — still flag for review
                    ctx.requires_review = True
                    ctx.governance_task_id = self._create_governance_task(ctx)
        except Exception as exc:
            logger.warning("intelligence.route failed: %s", exc)
            ctx.errors.append(f"routing: {exc}")
        finally:
            ctx.stage_latencies["route"] = (time.perf_counter() - t0) * 1000.0

    def _create_governance_task(self, ctx: PipelineContext) -> Optional[str]:
        """Create a governance review task and return its ID."""
        try:
            if self._governance_service is None:
                return None
            from app.schemas.governance import (
                GovernanceDecision,
                GovernanceDecisionCreateRequest,
                DecisionType,
            )
            decision_req = GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                inputs={"query": ctx.query},
                outputs={"answer_summary": (ctx.answer or {}).get("executive_summary", "")[:200]},
                metadata={
                    "run_id": ctx.run_id,
                    "confidence": ctx.confidence,
                    "confidence_level": ctx.confidence_level,
                    "flags": ctx.confidence_flags,
                    "reason": "confidence_below_low_threshold",
                },
            )
            decision = self._governance_service.register_decision(decision_req)
            return str(decision.decision_id) if decision else None
        except Exception as exc:
            logger.warning("intelligence.governance_task failed: %s", exc)
            return None

    async def _stage_workflow(
        self,
        ctx: PipelineContext,
        request: IntelligenceQueryRequest,
    ) -> None:
        """Stage 6b: run the requested agent workflow (research|compliance|risk).

        Best-effort enrichment: the agent result is attached to
        ``ctx.workflow_output`` (surfaced in response metadata). Failures are
        captured in ``ctx.errors`` and never fail the query itself.
        """
        t0 = time.perf_counter()
        try:
            name = (request.workflow or "").strip().lower()
            if not name:
                return
            if name not in ("research", "compliance", "risk"):
                ctx.errors.append(
                    f"workflow: unknown workflow {request.workflow!r} "
                    "(expected 'research', 'compliance' or 'risk')"
                )
                return
            from app.services.intelligence_agents import (
                build_default_intelligence_agent_service,
            )

            svc = build_default_intelligence_agent_service()
            doc_ids = sorted(
                {e.get("document_id") for e in ctx.evidence if e.get("document_id")}
            )
            top_k = request.top_k or settings.INTELLIGENCE_TOP_K
            if name == "research":
                from app.schemas.intelligence_agents import ResearchAgentRequest

                result = await svc.run_research(
                    ResearchAgentRequest(
                        query=ctx.query, top_k=top_k, document_ids=doc_ids
                    )
                )
            elif name == "compliance":
                from app.schemas.intelligence_agents import ComplianceAgentRequest

                result = await svc.run_compliance(
                    ComplianceAgentRequest(
                        query=ctx.query,
                        document_id=doc_ids[0] if len(doc_ids) == 1 else None,
                    )
                )
            else:
                from app.schemas.intelligence_agents import RiskAgentRequest

                result = await svc.run_risk(RiskAgentRequest(query=ctx.query))
            ctx.workflow_output = {
                "workflow": name,
                "result": result.model_dump(mode="json"),
            }
        except Exception as exc:
            logger.warning("intelligence.workflow failed: %s", exc)
            ctx.errors.append(f"workflow: {exc}")
        finally:
            ctx.stage_latencies["workflow"] = (time.perf_counter() - t0) * 1000.0

    def _stage_abstain(self, ctx: PipelineContext, reason: str = "insufficient_evidence") -> None:
        """Mark the pipeline as abstained and produce a structured abstention answer."""
        ctx.abstained = True
        ctx.answer = {
            "executive_summary": (
                "I cannot provide a reliable answer to this question based on the "
                "available regulatory documents. The retrieved evidence is either "
                "insufficient or not directly relevant to the query."
            ),
            "detailed_explanation": (
                f"Abstention reason: {reason}. "
                "No answer has been generated to avoid providing misleading regulatory guidance. "
                "Please consult a qualified compliance professional or refer to the original "
                "regulatory documents directly."
            ),
            "supporting_evidence": [],
            "key_regulatory_references": [],
            "compliance_implications": "",
            "recommended_actions": "Consult the relevant regulatory authority or a qualified compliance professional.",
            "caveats": "System abstained due to insufficient evidence.",
        }
        ctx.confidence = ctx.confidence if ctx.confidence > 0 else 0.0
        logger.info(
            "intelligence.abstain run_id=%s reason=%s confidence=%.3f",
            ctx.run_id,
            reason,
            ctx.confidence,
        )

    def _stage_audit(self, ctx: PipelineContext) -> None:
        """Stage 7: Create audit trail entry."""
        t0 = time.perf_counter()
        try:
            if self._audit_service is None:
                return
            from app.schemas.audit import AuditAction, AuditRecordCreateRequest, AuditSeverity

            severity = AuditSeverity.WARNING if ctx.requires_review else AuditSeverity.INFO

            req = AuditRecordCreateRequest(
                actor="system:intelligence_pipeline",
                actor_role="pipeline",
                action=AuditAction.READ,
                subject_type="intelligence_query",
                subject_id=ctx.run_id,
                description=f"Intelligence query processed: confidence={ctx.confidence:.3f} abstained={ctx.abstained}",
                severity=severity,
                details={
                    "run_id": ctx.run_id,
                    "query_preview": ctx.query[:100],
                    "confidence": ctx.confidence,
                    "confidence_level": ctx.confidence_level,
                    "abstained": ctx.abstained,
                    "requires_review": ctx.requires_review,
                    "governance_task_id": ctx.governance_task_id,
                    "evidence_count": len(ctx.evidence),
                    "citation_count": len(ctx.citations),
                    "hallucination_detected": ctx.hallucination_detected,
                    "errors": ctx.errors,
                    "stage_latencies": ctx.stage_latencies,
                },
                source_module="intelligence.pipeline",
            )
            record = self._audit_service.create_record(req)
            ctx.audit_record_id = str(record.audit_id) if record else None
        except Exception as exc:
            logger.warning("intelligence.audit failed: %s", exc)
            ctx.errors.append(f"audit: {exc}")
        finally:
            ctx.stage_latencies["audit"] = (time.perf_counter() - t0) * 1000.0

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fallback_answer(query: str, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a basic answer from evidence when the LLM is unavailable."""
        if not evidence:
            return {
                "executive_summary": "No relevant regulatory documents were found for this query.",
                "detailed_explanation": "",
                "supporting_evidence": [],
                "key_regulatory_references": [],
                "compliance_implications": "",
                "recommended_actions": "",
                "caveats": "Answer generated from evidence without LLM synthesis.",
            }
        snippets = [e.get("content", "")[:300] for e in evidence[:3]]
        chunk_ids = [str(e.get("chunk_id", "")) for e in evidence if e.get("chunk_id")]
        return {
            "executive_summary": f"Based on retrieved regulatory documents: {snippets[0][:200]}",
            "detailed_explanation": " ".join(snippets),
            "supporting_evidence": chunk_ids,
            "key_regulatory_references": [
                e.get("source", "Unknown") for e in evidence[:3] if e.get("source")
            ],
            "compliance_implications": "",
            "recommended_actions": "",
            "caveats": "Answer synthesised directly from evidence without LLM processing.",
        }

    def _build_response(
        self, ctx: PipelineContext, total_ms: float
    ) -> IntelligenceQueryResponse:
        """Assemble the final response from the pipeline context."""
        answer_dict = ctx.answer or {}

        # Parse breakdown if available
        breakdown = None
        if ctx.confidence_breakdown:
            from app.schemas.intelligence import ConfidenceBreakdown
            try:
                breakdown = ConfidenceBreakdown(**ctx.confidence_breakdown)
            except Exception:
                pass

        # Build evidence list
        evidence = [
            EvidenceChunk(
                chunk_id=str(e.get("chunk_id", "")),
                document_id=str(e.get("document_id", "")) or None,
                content=str(e.get("content", "")),
                score=float(e.get("score", 0.0)),
                source=e.get("source"),
                section=e.get("section"),
                subsection=e.get("subsection"),
                page_number=e.get("page_number"),
                metadata=dict(e.get("metadata", {})),
            )
            for e in ctx.evidence
        ]

        # Build citation list
        citations = [
            CitationItem(
                citation_id=str(c.get("citation_id", uuid.uuid4().hex)),
                document_title=c.get("document_title"),
                document_id=str(c.get("document_id", "")) or None,
                chunk_id=str(c.get("chunk_id", "")) or None,
                source=c.get("source"),
                section=c.get("section"),
                page_number=c.get("page_number"),
                excerpt=c.get("excerpt") or c.get("text"),
                relevance_score=c.get("relevance_score") or c.get("score"),
            )
            for c in ctx.citations
        ]

        return IntelligenceQueryResponse(
            run_id=ctx.run_id,
            query=ctx.query,
            answer=AnswerSection(
                executive_summary=answer_dict.get("executive_summary", ""),
                detailed_explanation=answer_dict.get("detailed_explanation", ""),
                supporting_evidence=list(answer_dict.get("supporting_evidence", [])),
                key_regulatory_references=list(answer_dict.get("key_regulatory_references", [])),
                compliance_implications=answer_dict.get("compliance_implications", ""),
                recommended_actions=answer_dict.get("recommended_actions", ""),
                caveats=answer_dict.get("caveats", ""),
            ),
            citations=citations,
            evidence=evidence,
            confidence=ctx.confidence,
            confidence_level=ctx.confidence_level,
            confidence_breakdown=breakdown,
            confidence_flags=ctx.confidence_flags,
            abstained=ctx.abstained,
            requires_review=ctx.requires_review,
            governance_task_id=ctx.governance_task_id,
            hallucination_detected=ctx.hallucination_detected,
            faithfulness_score=ctx.faithfulness_score,
            audit_record_id=ctx.audit_record_id,
            latency_ms=total_ms,
            metadata={
                "stage_latencies": ctx.stage_latencies,
                "evidence_count": len(ctx.evidence),
                "workflow": ctx.workflow_output,
                "errors": ctx.errors,
            },
        )


# ─── Factory ─────────────────────────────────────────────────────────────────


def build_intelligence_pipeline(
    *,
    hybrid_retriever=None,
    answer_generator=None,
    citation_service=None,
    confidence_service=None,
    hallucination_guard=None,
    governance_service=None,
    audit_service=None,
) -> IntelligencePipeline:
    """Wire up the canonical IntelligencePipeline from existing service instances."""
    return IntelligencePipeline(
        hybrid_retriever=hybrid_retriever,
        answer_generator=answer_generator,
        citation_service=citation_service,
        confidence_service=confidence_service,
        hallucination_guard=hallucination_guard,
        governance_service=governance_service,
        audit_service=audit_service,
    )


__all__ = ["IntelligencePipeline", "PipelineContext", "build_intelligence_pipeline"]
