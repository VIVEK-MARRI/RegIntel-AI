"""Module 7.6 — Regulatory Knowledge Graph Layer.

Public surface
--------------
* ``EntityExtractor``           — text → entities (rule-based)
* ``RelationshipMapper``        — derive relationships from text/co-occurrence
* ``GraphBuilder``              — assemble graphs from inputs
* ``GraphRepository``           — search / queries
* ``GraphStore`` (ABC) + ``InMemoryGraphStore`` (JSONL)
* ``KnowledgeGraphService``     — DI facade
* ``build_default_knowledge_graph_service``
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.core.config import settings
from app.schemas.knowledge_graph import (
    DependencyAnalysisResult,
    EntityType,
    GraphNode,
    GraphRelationship,
    GraphSnapshot,
    GraphStats,
    ImpactTraversalResult,
    NodeCreateRequest,
    NodeFilter,
    NodeSource,
    PaginatedNodes,
    PaginatedRelationships,
    RelationshipCreateRequest,
    RelationshipType,
    TraversalStep,
)
from app.services.observability import (
    get_knowledge_graph_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Entity extractor (rule-based) ───────────────────────────────────


_ENTITY_PATTERNS: Dict[EntityType, List[str]] = {
    EntityType.REGULATION: [
        r"\bRBI Act\b",
        r"\bSEBI Act\b",
        r"\bIRDA Act\b",
        r"\bPFRDA Act\b",
        r"\bRegulations?,?\s+\d{4}\b",
        r"\bMaster Circular\b",
        r"\bMaster Direction\b",
    ],
    EntityType.CIRCULAR: [
        r"\bCircular\s+(?:No\.?\s*)?[A-Z0-9\-/]+\b",
        r"\bNotification\s+(?:No\.?\s*)?[A-Z0-9\-/]+\b",
    ],
    EntityType.AMENDMENT: [
        r"\bAmendment\b",
        r"\bAmendments?\s+to\s+the\s+[A-Z][\w\s]+(?:Regulations?|Act|Directions?)\b",
    ],
    EntityType.INSTITUTION: [
        r"\bReserve Bank of India\b",
        r"\bRBI\b",
        r"\bSEBI\b",
        r"\bIRDAI\b",
        r"\bPFRDA\b",
        r"\bScheduled Banks?\b",
        r"\bNon[- ]Banking Financial Compan(?:y|ies)\b",
        r"\bNBFC(?:s)?\b",
        r"\bInsurers?\b",
        r"\bPension Funds?\b",
        r"\bAsset Management Compan(?:y|ies)\b",
        r"\bAMC(?:s)?\b",
        r"\bBroker(?:s)?\b",
        r"\bFintechs?\b",
    ],
    EntityType.TOPIC: [
        r"\bKYC\b",
        r"\bAML\b",
        r"\bCapital Adequacy\b",
        r"\bRisk Management\b",
        r"\bOutsourcing\b",
        r"\bCyber Security\b",
        r"\bFraud\b",
        r"\bPMLA\b",
        r"\bReporting Requirements?\b",
        r"\bCustomer Grievance(?:s)?\b",
    ],
    EntityType.REQUIREMENT: [
        r"\bmust\b",
        r"\bshall\b",
        r"\brequired to\b",
        r"\bmandatory\b",
        r"\bobligat(?:ed|ion|ions)\b",
    ],
}


class EntityExtractor:
    """Rule-based named-entity extractor over regulatory text."""

    def extract(self, text: str) -> List[GraphNode]:
        nodes: List[GraphNode] = []
        seen: Set[str] = set()
        if not text:
            return nodes
        for ent_type, patterns in _ENTITY_PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, text, flags=re.IGNORECASE):
                    name = m.group(0).strip()
                    key = f"{ent_type.value}::{name.lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    nodes.append(
                        GraphNode(
                            entity_type=ent_type,
                            name=name,
                            description=f"Extracted from text (offset={m.start()})",
                            source=NodeSource.CHANGE_DETECTION,
                            created_at=time.time(),
                            updated_at=time.time(),
                        )
                    )
        return nodes


# ─── Relationship mapper ─────────────────────────────────────────────


_RELATION_KEYWORDS: Dict[RelationshipType, List[str]] = {
    RelationshipType.AMENDS: ["amend", "amends", "amended", "amendment"],
    RelationshipType.SUPERSEDES: [
        "supersede",
        "supersedes",
        "superseded",
        "replaces",
        "replaced by",
        "substituted by",
    ],
    RelationshipType.REFERENCES: ["reference", "references", "as per", "per"],
    RelationshipType.AFFECTS: ["affects", "applies to", "binding on"],
    RelationshipType.RELATES_TO: ["relates to", "regarding", "in respect of"],
}


class RelationshipMapper:
    """Map relationships between entities within or across texts."""

    def map_from_text(
        self,
        nodes: List[GraphNode],
        text: str,
    ) -> List[GraphRelationship]:
        rels: List[GraphRelationship] = []
        if not text or len(nodes) < 2:
            return rels
        text_lower = text.lower()
        # Find any relationship keywords in the text
        rel_hits: List[Tuple[RelationshipType, int]] = []
        for rtype, keywords in _RELATION_KEYWORDS.items():
            for kw in keywords:
                for m in re.finditer(r"\b" + re.escape(kw) + r"\b", text_lower):
                    rel_hits.append((rtype, m.start()))
        rel_hits.sort(key=lambda x: x[1])
        if not rel_hits:
            # Default: connect any two nodes co-occurring
            for i in range(len(nodes) - 1):
                rels.append(
                    GraphRelationship(
                        source_id=nodes[i].node_id,
                        target_id=nodes[i + 1].node_id,
                        relationship_type=RelationshipType.RELATES_TO,
                        weight=0.5,
                        confidence=0.5,
                        created_at=time.time(),
                    )
                )
            return rels
        # Connect nearest two nodes around each keyword
        for rtype, pos in rel_hits:
            nearest = sorted(
                nodes,
                key=lambda n: abs(
                    self._first_occurrence(text, n.name) - pos
                ),
            )[:2]
            if len(nearest) == 2 and nearest[0].node_id != nearest[1].node_id:
                rels.append(
                    GraphRelationship(
                        source_id=nearest[0].node_id,
                        target_id=nearest[1].node_id,
                        relationship_type=rtype,
                        weight=1.0,
                        confidence=0.7,
                        created_at=time.time(),
                    )
                )
        return rels

    @staticmethod
    def _first_occurrence(text: str, name: str) -> int:
        return text.lower().find(name.lower())


# ─── Graph builder ───────────────────────────────────────────────────


class GraphBuilder:
    """High-level builder: turn a text + metadata into nodes + relationships."""

    def __init__(
        self,
        extractor: Optional[EntityExtractor] = None,
        mapper: Optional[RelationshipMapper] = None,
    ) -> None:
        self.extractor = extractor or EntityExtractor()
        self.mapper = mapper or RelationshipMapper()

    def build(
        self,
        text: str,
        *,
        source: NodeSource = NodeSource.CHANGE_DETECTION,
        pre_nodes: Optional[List[GraphNode]] = None,
    ) -> Tuple[List[GraphNode], List[GraphRelationship]]:
        nodes = pre_nodes or self.extractor.extract(text)
        # Apply source override
        for n in nodes:
            n.source = source
        rels = self.mapper.map_from_text(nodes, text)
        return nodes, rels


# ─── Store ───────────────────────────────────────────────────────────


class GraphStore(ABC):
    @abstractmethod
    def add_node(self, node: GraphNode) -> None: ...

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[GraphNode]: ...

    @abstractmethod
    def list_nodes(self) -> List[GraphNode]: ...

    @abstractmethod
    def add_relationship(self, rel: GraphRelationship) -> None: ...

    @abstractmethod
    def get_relationship(self, rel_id: str) -> Optional[GraphRelationship]: ...

    @abstractmethod
    def list_relationships(self) -> List[GraphRelationship]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryGraphStore(GraphStore):
    """Thread-safe in-memory graph store with optional JSONL persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._nodes: Dict[str, GraphNode] = {}
        self._rels: Dict[str, GraphRelationship] = {}
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
                        kind = data.get("kind")
                        if kind == "node":
                            n = GraphNode(**data["payload"])
                            self._nodes[n.node_id] = n
                        elif kind == "rel":
                            r = GraphRelationship(**data["payload"])
                            self._rels[r.relationship_id] = r
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, kind: str, payload: Dict[str, Any]) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": kind, "payload": payload}) + "\n")
        except Exception:  # pragma: no cover
            pass

    def add_node(self, node: GraphNode) -> None:
        with self._lock:
            self._nodes[node.node_id] = node
        self._persist("node", node.model_dump(mode="json"))

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        with self._lock:
            return self._nodes.get(node_id)

    def list_nodes(self) -> List[GraphNode]:
        with self._lock:
            return list(self._nodes.values())

    def add_relationship(self, rel: GraphRelationship) -> None:
        with self._lock:
            self._rels[rel.relationship_id] = rel
        self._persist("rel", rel.model_dump(mode="json"))

    def get_relationship(self, rel_id: str) -> Optional[GraphRelationship]:
        with self._lock:
            return self._rels.get(rel_id)

    def list_relationships(self) -> List[GraphRelationship]:
        with self._lock:
            return list(self._rels.values())

    def reset(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._rels.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Repository ──────────────────────────────────────────────────────


class GraphRepository:
    def __init__(self, store: GraphStore) -> None:
        self._store = store

    # ── nodes ────────────────────────────────────────────────────

    def add_node(self, node: GraphNode) -> None:
        self._store.add_node(node)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._store.get_node(node_id)

    def search_nodes(self, flt: NodeFilter) -> PaginatedNodes:
        items = self._store.list_nodes()
        if flt.entity_type:
            items = [n for n in items if n.entity_type == flt.entity_type]
        if flt.source:
            items = [n for n in items if n.source == flt.source]
        if flt.name_contains:
            lc = flt.name_contains.lower()
            items = [n for n in items if lc in n.name.lower()]
        if flt.tag:
            items = [n for n in items if flt.tag in n.tags]
        items.sort(key=lambda n: n.created_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedNodes(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    # ── relationships ───────────────────────────────────────────

    def add_relationship(self, rel: GraphRelationship) -> None:
        self._store.add_relationship(rel)

    def get_relationship(self, rel_id: str) -> Optional[GraphRelationship]:
        return self._store.get_relationship(rel_id)

    def search_relationships(
        self,
        *,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        rel_type: Optional[RelationshipType] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedRelationships:
        items = self._store.list_relationships()
        if source_id:
            items = [r for r in items if r.source_id == source_id]
        if target_id:
            items = [r for r in items if r.target_id == target_id]
        if rel_type:
            items = [r for r in items if r.relationship_type == rel_type]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return PaginatedRelationships(
            items=items[start:end],
            total=total,
            page=page,
            page_size=page_size,
            has_more=end < total,
        )

    # ── analysis ────────────────────────────────────────────────

    def stats(self) -> GraphStats:
        nodes = self._store.list_nodes()
        rels = self._store.list_relationships()
        s = GraphStats(
            total_nodes=len(nodes),
            total_relationships=len(rels),
        )
        if not nodes:
            s.generated_at = time.time()
            return s
        for n in nodes:
            et = n.entity_type.value
            s.by_entity_type[et] = s.by_entity_type.get(et, 0) + 1
            s.by_source[n.source.value] = s.by_source.get(n.source.value, 0) + 1
        for r in rels:
            rt = r.relationship_type.value
            s.by_relationship_type[rt] = s.by_relationship_type.get(rt, 0) + 1
        # average degree
        deg: Dict[str, int] = defaultdict(int)
        for r in rels:
            deg[r.source_id] += 1
            deg[r.target_id] += 1
        if deg:
            s.average_degree = sum(deg.values()) / len(deg)
        s.max_depth = self._max_depth(rels)
        s.connected_components = self._components(nodes, rels)
        s.generated_at = time.time()
        return s

    def _max_depth(self, rels: List[GraphRelationship]) -> int:
        if not rels:
            return 0
        adj: Dict[str, List[str]] = defaultdict(list)
        nodes: Set[str] = set()
        for r in rels:
            adj[r.source_id].append(r.target_id)
            nodes.add(r.source_id)
            nodes.add(r.target_id)
        # BFS from any node, track longest distance
        max_d = 0
        for src in list(adj.keys())[:10]:  # bounded for speed
            q: deque[Tuple[str, int]] = deque([(src, 0)])
            visited = {src}
            while q:
                cur, d = q.popleft()
                max_d = max(max_d, d)
                for nxt in adj[cur]:
                    if nxt not in visited:
                        visited.add(nxt)
                        q.append((nxt, d + 1))
        return max_d

    def _components(
        self, nodes: List[GraphNode], rels: List[GraphRelationship]
    ) -> int:
        if not nodes:
            return 0
        adj: Dict[str, Set[str]] = defaultdict(set)
        node_ids = {n.node_id for n in nodes}
        for r in rels:
            if r.source_id in node_ids and r.target_id in node_ids:
                adj[r.source_id].add(r.target_id)
                adj[r.target_id].add(r.source_id)
        visited: Set[str] = set()
        comps = 0
        for nid in node_ids:
            if nid in visited:
                continue
            comps += 1
            q: deque[str] = deque([nid])
            while q:
                cur = q.popleft()
                for nxt in adj[cur]:
                    if nxt not in visited:
                        visited.add(nxt)
                        q.append(nxt)
            visited.add(nid)
        return comps

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot(
            nodes=self._store.list_nodes(),
            relationships=self._store.list_relationships(),
            stats=self.stats(),
            generated_at=time.time(),
        )


# ─── Service (DI facade) ────────────────────────────────────────────


class KnowledgeGraphService:
    """High-level DI facade for the knowledge graph layer."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.repository = GraphRepository(store)
        self.builder = GraphBuilder()
        self.extractor = self.builder.extractor
        self.mapper = self.builder.mapper

    # ── construction ─────────────────────────────────────────────

    def add_node(self, req: NodeCreateRequest) -> GraphNode:
        with track_request(endpoint="/api/v1/knowledge-graph/nodes", strategy="kg_add"):
            n = GraphNode(
                entity_type=req.entity_type,
                name=req.name,
                description=req.description,
                external_id=req.external_id,
                source=req.source,
                properties=req.properties,
                tags=req.tags,
                created_at=time.time(),
                updated_at=time.time(),
            )
            self.store.add_node(n)
            get_knowledge_graph_metrics().record_node(n)
            return n

    def add_relationship(self, req: RelationshipCreateRequest) -> GraphRelationship:
        with track_request(
            endpoint="/api/v1/knowledge-graph/relationships",
            strategy="kg_add_rel",
        ):
            if not self.store.get_node(req.source_id):
                raise ValueError(f"source node {req.source_id!r} not found")
            if not self.store.get_node(req.target_id):
                raise ValueError(f"target node {req.target_id!r} not found")
            r = GraphRelationship(
                source_id=req.source_id,
                target_id=req.target_id,
                relationship_type=req.relationship_type,
                weight=req.weight,
                confidence=req.confidence,
                properties=req.properties,
                created_at=time.time(),
            )
            self.store.add_relationship(r)
            get_knowledge_graph_metrics().record_relationship(r)
            return r

    def build_from_text(
        self,
        text: str,
        *,
        source: NodeSource = NodeSource.CHANGE_DETECTION,
    ) -> Tuple[List[GraphNode], List[GraphRelationship]]:
        with track_request(
            endpoint="/api/v1/knowledge-graph/build", strategy="kg_build"
        ):
            nodes, rels = self.builder.build(text, source=source)
            for n in nodes:
                self.store.add_node(n)
                get_knowledge_graph_metrics().record_node(n)
            for r in rels:
                if self.store.get_node(r.source_id) and self.store.get_node(
                    r.target_id
                ):
                    self.store.add_relationship(r)
                    get_knowledge_graph_metrics().record_relationship(r)
            get_knowledge_graph_metrics().record_build()
            return nodes, rels

    # ── queries ─────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self.store.get_node(node_id)

    def get_relationship(
        self, rel_id: str
    ) -> Optional[GraphRelationship]:
        return self.store.get_relationship(rel_id)

    def search_nodes(self, flt: NodeFilter) -> PaginatedNodes:
        return self.repository.search_nodes(flt)

    def search_relationships(
        self,
        *,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        rel_type: Optional[RelationshipType] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedRelationships:
        return self.repository.search_relationships(
            source_id=source_id,
            target_id=target_id,
            rel_type=rel_type,
            page=page,
            page_size=page_size,
        )

    def list_all(self) -> Tuple[List[GraphNode], List[GraphRelationship]]:
        return self.store.list_nodes(), self.store.list_relationships()

    # ── analysis ────────────────────────────────────────────────

    def impact_traversal(
        self,
        start_node_id: str,
        *,
        max_depth: int = 3,
        rel_types: Optional[List[RelationshipType]] = None,
    ) -> ImpactTraversalResult:
        start = time.time()
        with track_request(
            endpoint="/api/v1/knowledge-graph/impact-traversal",
            strategy="kg_traversal",
        ):
            start_node = self.store.get_node(start_node_id)
            if start_node is None:
                raise ValueError(f"start node {start_node_id!r} not found")
            allowed = set(rel_types) if rel_types else None
            adj: Dict[str, List[Tuple[str, RelationshipType, float]]] = defaultdict(
                list
            )
            for r in self.store.list_relationships():
                if allowed and r.relationship_type not in allowed:
                    continue
                adj[r.source_id].append(
                    (r.target_id, r.relationship_type, r.weight)
                )
                adj[r.target_id].append(
                    (r.source_id, r.relationship_type, r.weight)
                )
            steps: List[TraversalStep] = []
            affected: List[str] = []
            seen = {start_node_id}
            q: deque[Tuple[str, int, List[str]]] = deque(
                [(start_node_id, 0, [start_node_id])]
            )
            max_d = 0
            while q:
                cur, depth, path = q.popleft()
                if depth >= max_depth:
                    continue
                for nxt, rtype, w in adj[cur]:
                    new_path = path + [nxt]
                    step = TraversalStep(
                        from_node_id=cur,
                        to_node_id=nxt,
                        relationship_type=rtype,
                        depth=depth + 1,
                        weight=w,
                        path=new_path,
                    )
                    steps.append(step)
                    if nxt not in seen:
                        seen.add(nxt)
                        affected.append(nxt)
                        q.append((nxt, depth + 1, new_path))
                max_d = max(max_d, depth)
            get_knowledge_graph_metrics().record_traversal()
            return ImpactTraversalResult(
                start_node_id=start_node_id,
                steps=steps,
                affected_node_ids=affected,
                total_paths=len(steps),
                max_depth_reached=max_d,
                duration_ms=round((time.time() - start) * 1000.0, 3),
            )

    def dependency_analysis(
        self, root_node_id: str, *, max_depth: int = 5
    ) -> DependencyAnalysisResult:
        start = time.time()
        with track_request(
            endpoint="/api/v1/knowledge-graph/dependency-analysis",
            strategy="kg_dependency",
        ):
            root = self.store.get_node(root_node_id)
            if root is None:
                raise ValueError(f"root node {root_node_id!r} not found")
            # Upstream = nodes that point to root; downstream = nodes root points to
            rels = self.store.list_relationships()
            fwd: Dict[str, List[str]] = defaultdict(list)
            bwd: Dict[str, List[str]] = defaultdict(list)
            for r in rels:
                fwd[r.source_id].append(r.target_id)
                bwd[r.target_id].append(r.source_id)

            def _chain(
                start_id: str, adj: Dict[str, List[str]]
            ) -> List[GraphNode]:
                seen = {start_id}
                q: deque[str] = deque([start_id])
                collected: List[GraphNode] = []
                depth = 0
                while q and depth < max_depth:
                    nxt_q: deque[str] = deque()
                    while q:
                        cur = q.popleft()
                        for nb in adj[cur]:
                            if nb in seen:
                                continue
                            seen.add(nb)
                            n = self.store.get_node(nb)
                            if n is not None:
                                collected.append(n)
                                nxt_q.append(nb)
                    q = nxt_q
                    depth += 1
                return collected

            upstream = _chain(root_node_id, bwd)
            downstream = _chain(root_node_id, fwd)
            cycles = self._count_cycles(rels)
            get_knowledge_graph_metrics().record_dependency()
            return DependencyAnalysisResult(
                root_node_id=root_node_id,
                upstream=upstream,
                downstream=downstream,
                cycles_detected=cycles,
                max_chain_length=max(
                    len(upstream), len(downstream)
                ),
                duration_ms=round((time.time() - start) * 1000.0, 3),
            )

    @staticmethod
    def _count_cycles(rels: List[GraphRelationship]) -> int:
        adj: Dict[str, List[str]] = defaultdict(list)
        for r in rels:
            adj[r.source_id].append(r.target_id)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {}
        cycles = 0
        for src in list(adj.keys()):
            if color.get(src, WHITE) != WHITE:
                continue
            stack: List[Tuple[str, int]] = [(src, 0)]
            while stack:
                node, i = stack[-1]
                if color.get(node, WHITE) == WHITE:
                    color[node] = GRAY
                if i < len(adj[node]):
                    stack[-1] = (node, i + 1)
                    nxt = adj[node][i]
                    if color.get(nxt, WHITE) == GRAY:
                        cycles += 1
                    elif color.get(nxt, WHITE) == WHITE:
                        stack.append((nxt, 0))
                else:
                    color[node] = BLACK
                    stack.pop()
        return cycles

    # ── exports ─────────────────────────────────────────────────

    def stats(self) -> GraphStats:
        return self.repository.stats()

    def snapshot(self) -> GraphSnapshot:
        return self.repository.snapshot()

    def reset(self) -> None:
        self.store.reset()


# ─── Factory ────────────────────────────────────────────────────────


def build_default_knowledge_graph_service() -> KnowledgeGraphService:
    persist = os.path.join(settings.STORAGE_ROOT, "knowledge_graph", "graph.jsonl")
    store = InMemoryGraphStore(persist_path=persist)
    return KnowledgeGraphService(store=store)


__all__ = [
    "EntityExtractor",
    "RelationshipMapper",
    "GraphBuilder",
    "GraphStore",
    "InMemoryGraphStore",
    "GraphRepository",
    "KnowledgeGraphService",
    "build_default_knowledge_graph_service",
]
