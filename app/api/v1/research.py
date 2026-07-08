"""Module 7.7 — Agentic Regulatory Research API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_hybrid_rerank_pipeline, get_research_service
from app.schemas.research import ResearchFilter, ResearchKind, ResearchRequest
from app.services.hybrid.pipeline import HybridRerankPipeline
from app.services.research import ResearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Research service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "research", "version": "7.7.0"}


@router.get(
    "/stats",
    summary="Aggregate research statistics",
)
async def stats(
    service: ResearchService = Depends(get_research_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


# ─── Run / Plan ──────────────────────────────────────────────────────


@router.post(
    "/run",
    summary="Run an end-to-end research task",
)
async def run(
    request: ResearchRequest,
    service: ResearchService = Depends(get_research_service),
    hybrid: HybridRerankPipeline = Depends(get_hybrid_rerank_pipeline),
) -> Dict[str, Any]:
    knowledge_items: list[Dict[str, Any]] = []
    try:
        resp = await hybrid.search(query=request.query, top_k=5)
        for r in resp.results:
            meta = r.metadata or {}
            knowledge_items.append(
                {
                    "id": r.chunk_id,
                    "title": meta.get("title", ""),
                    "content": r.content,
                    "body": r.content,
                    "score": r.rerank_score,
                    "document_id": meta.get("document_id", ""),
                    "section": meta.get("section", ""),
                    "page_number": meta.get("page_number"),
                }
            )
    except Exception as exc:
        logger.warning("Hybrid search failed for query '%s': %s", request.query, exc)
    return (await service.run(request, knowledge_items=knowledge_items)).model_dump(
        mode="json"
    )


@router.post(
    "/plan",
    summary="Generate a research plan (no execution)",
)
async def plan(
    request: ResearchRequest,
    service: ResearchService = Depends(get_research_service),
) -> Dict[str, Any]:
    p = service.plan_only(request)
    return p.model_dump(mode="json")


# ─── Search / List ──────────────────────────────────────────────────


@router.get(
    "",
    summary="List / filter research reports",
)
async def list_reports(
    kind: Optional[ResearchKind] = Query(None),
    after: Optional[float] = Query(None),
    before: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    service: ResearchService = Depends(get_research_service),
) -> Dict[str, Any]:
    flt = ResearchFilter(
        kind=kind,
        after=after,
        before=before,
        page=page,
        page_size=page_size,
    )
    return service.search(flt).model_dump(mode="json")


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/{report_id}",
    summary="Fetch a single research report",
)
async def get_report(
    report_id: str,
    service: ResearchService = Depends(get_research_service),
) -> Dict[str, Any]:
    r = service.get(report_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"report {report_id!r} not found",
        )
    return r.model_dump(mode="json")


__all__ = ["router"]
