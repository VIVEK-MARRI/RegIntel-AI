"""PostgreSQL-backed knowledge-graph store.

Implements the same :class:`GraphStore` ABC as the JSONL store, but persists
``kg_nodes`` / ``kg_relationships`` rows — so the graph survives backend
restarts and redeploys. Used automatically whenever ``DATABASE_URL`` points
at PostgreSQL; SQLite/file deployments keep the JSONL store.

Sync SQLAlchemy sessions are used (one short scoped session per call) so the
existing synchronous service layer needs no changes.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.knowledge_graph import KGNode, KGRelationship
from app.schemas.knowledge_graph import (
    EntityType,
    GraphNode,
    GraphRelationship,
    NodeSource,
    RelationshipType,
)
from app.services.knowledge_graph import GraphStore

logger = logging.getLogger(__name__)


def _enum_value(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _node_to_row(n: GraphNode) -> KGNode:
    return KGNode(
        id=n.node_id,
        entity_type=_enum_value(n.entity_type),
        name=n.name,
        description=n.description or "",
        external_id=n.external_id,
        source=_enum_value(n.source),
        properties=dict(n.properties or {}),
        tags=list(n.tags or []),
        created_at=float(n.created_at or 0.0),
        updated_at=float(n.updated_at or 0.0),
    )


def _row_to_node(r: KGNode) -> Optional[GraphNode]:
    try:
        return GraphNode(
            node_id=r.id,
            entity_type=EntityType(r.entity_type),
            name=r.name,
            description=r.description or "",
            external_id=r.external_id,
            source=NodeSource(r.source),
            properties=dict(r.properties or {}),
            tags=list(r.tags or []),
            created_at=float(r.created_at or 0.0),
            updated_at=float(r.updated_at or 0.0),
        )
    except Exception:
        logger.warning("Skipping KG node with unknown enum: %s", r.id)
        return None


def _rel_to_row(r: GraphRelationship) -> KGRelationship:
    return KGRelationship(
        id=r.relationship_id,
        source_id=r.source_id,
        target_id=r.target_id,
        relationship_type=_enum_value(r.relationship_type),
        weight=float(r.weight),
        confidence=float(r.confidence),
        properties=dict(r.properties or {}),
        created_at=float(r.created_at or 0.0),
    )


def _row_to_rel(r: KGRelationship) -> Optional[GraphRelationship]:
    try:
        return GraphRelationship(
            relationship_id=r.id,
            source_id=r.source_id,
            target_id=r.target_id,
            relationship_type=RelationshipType(r.relationship_type),
            weight=float(r.weight),
            confidence=float(r.confidence),
            properties=dict(r.properties or {}),
            created_at=float(r.created_at or 0.0),
        )
    except Exception:
        logger.warning("Skipping KG relationship with unknown enum: %s", r.id)
        return None


_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_engine(
                    settings.DATABASE_URL_SYNC,
                    pool_size=3,
                    max_overflow=2,
                    pool_pre_ping=True,
                )
    return _engine


class PostgresGraphStore(GraphStore):
    """GraphStore persisted in PostgreSQL (kg_nodes / kg_relationships)."""

    def __init__(self) -> None:
        self._factory = sessionmaker(bind=_get_engine(), expire_on_commit=False)

    def _session(self) -> Session:
        return self._factory()

    def add_node(self, node: GraphNode) -> None:
        with self._session() as s:
            s.merge(_node_to_row(node))
            s.commit()

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        with self._session() as s:
            row = s.get(KGNode, node_id)
            return _row_to_node(row) if row is not None else None

    def list_nodes(self) -> List[GraphNode]:
        with self._session() as s:
            rows = s.execute(select(KGNode).order_by(KGNode.name)).scalars().all()
            out = []
            for r in rows:
                n = _row_to_node(r)
                if n is not None:
                    out.append(n)
            return out

    def add_relationship(self, rel: GraphRelationship) -> None:
        with self._session() as s:
            s.merge(_rel_to_row(rel))
            s.commit()

    def get_relationship(self, rel_id: str) -> Optional[GraphRelationship]:
        with self._session() as s:
            row = s.get(KGRelationship, rel_id)
            return _row_to_rel(row) if row is not None else None

    def list_relationships(self) -> List[GraphRelationship]:
        with self._session() as s:
            rows = s.execute(select(KGRelationship)).scalars().all()
            out = []
            for r in rows:
                rel = _row_to_rel(r)
                if rel is not None:
                    out.append(rel)
            return out

    def reset(self) -> None:
        with self._session() as s:
            s.execute(delete(KGRelationship))
            s.execute(delete(KGNode))
            s.commit()


__all__ = ["PostgresGraphStore"]
