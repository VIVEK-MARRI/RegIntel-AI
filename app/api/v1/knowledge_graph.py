"""Module 7.6 — Knowledge Graph API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_knowledge_graph_service
from app.schemas.knowledge_graph import (
    EntityType,
    NodeCreateRequest,
    NodeFilter,
    NodeSource,
    RelationshipCreateRequest,
    RelationshipType,
)
from app.services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Knowledge graph service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "knowledge_graph", "version": "7.6.0"}


@router.get(
    "/stats",
    summary="Aggregate knowledge graph statistics",
)
async def stats(
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


# ─── Build ───────────────────────────────────────────────────────────


@router.post(
    "/build",
    summary="Extract entities + relationships from text",
)
async def build(
    payload: Dict[str, Any],
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    text = payload.get("text", "")
    if not isinstance(text, str) or not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text is required",
        )
    source = NodeSource(payload.get("source", NodeSource.CHANGE_DETECTION.value))
    nodes, rels = service.build_from_text(text, source=source)
    return {
        "nodes": [n.model_dump(mode="json") for n in nodes],
        "relationships": [r.model_dump(mode="json") for r in rels],
        "node_count": len(nodes),
        "relationship_count": len(rels),
    }


# ─── Nodes ───────────────────────────────────────────────────────────


@router.post(
    "/nodes",
    summary="Create a new node",
)
async def create_node(
    request: NodeCreateRequest,
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    return service.add_node(request).model_dump(mode="json")


@router.get(
    "/nodes",
    summary="List / filter nodes",
)
async def list_nodes(
    entity_type: Optional[EntityType] = Query(None),
    source: Optional[NodeSource] = Query(None),
    name_contains: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    flt = NodeFilter(
        entity_type=entity_type,
        source=source,
        name_contains=name_contains,
        tag=tag,
        page=page,
        page_size=page_size,
    )
    return service.search_nodes(flt).model_dump(mode="json")


# ─── Relationships ──────────────────────────────────────────────────


@router.post(
    "/relationships",
    summary="Create a new relationship between two nodes",
)
async def create_relationship(
    request: RelationshipCreateRequest,
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    try:
        return service.add_relationship(request).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/relationships",
    summary="List / filter relationships",
)
async def list_relationships(
    source_id: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    rel_type: Optional[RelationshipType] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    res = service.search_relationships(
        source_id=source_id,
        target_id=target_id,
        rel_type=rel_type,
        page=page,
        page_size=page_size,
    )
    return res.model_dump(mode="json")


# ─── Analysis ────────────────────────────────────────────────────────


@router.post(
    "/impact-traversal/{start_node_id}",
    summary="BFS impact traversal from a starting node",
)
async def impact_traversal(
    start_node_id: str,
    max_depth: int = Query(3, ge=1, le=10),
    rel_type: Optional[RelationshipType] = Query(None),
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    rel_types = [rel_type] if rel_type else None
    try:
        res = service.impact_traversal(
            start_node_id, max_depth=max_depth, rel_types=rel_types
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return res.model_dump(mode="json")


@router.post(
    "/dependency-analysis/{root_node_id}",
    summary="Upstream / downstream dependency analysis",
)
async def dependency_analysis(
    root_node_id: str,
    max_depth: int = Query(5, ge=1, le=10),
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    try:
        res = service.dependency_analysis(root_node_id, max_depth=max_depth)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return res.model_dump(mode="json")


@router.get(
    "/snapshot",
    summary="Full graph export",
)
async def snapshot(
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    return service.snapshot().model_dump(mode="json")


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/nodes/{node_id}",
    summary="Fetch a single node",
)
async def get_node(
    node_id: str,
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    n = service.get_node(node_id)
    if n is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"node {node_id!r} not found",
        )
    return n.model_dump(mode="json")


@router.get(
    "/relationships/{rel_id}",
    summary="Fetch a single relationship",
)
async def get_relationship(
    rel_id: str,
    service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
) -> Dict[str, Any]:
    r = service.get_relationship(rel_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"relationship {rel_id!r} not found",
        )
    return r.model_dump(mode="json")


__all__ = ["router"]
