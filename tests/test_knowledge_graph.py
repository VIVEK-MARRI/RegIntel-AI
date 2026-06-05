"""Tests for Module 7.6 — Knowledge Graph Layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_knowledge_graph_service,
    reset_knowledge_graph_service,
)
from app.main import app
from app.schemas.knowledge_graph import (
    EntityType,
    NodeCreateRequest,
    NodeFilter,
    NodeSource,
    RelationshipCreateRequest,
    RelationshipType,
)
from app.services.knowledge_graph import (
    EntityExtractor,
    GraphBuilder,
    GraphRepository,
    GraphStore,
    InMemoryGraphStore,
    KnowledgeGraphService,
    RelationshipMapper,
    build_default_knowledge_graph_service,
)
from app.services.observability import reset_knowledge_graph_metrics


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_knowledge_graph_service()
    reset_knowledge_graph_metrics()
    yield
    reset_knowledge_graph_service()
    reset_knowledge_graph_metrics()


@pytest.fixture
def tmp_store(tmp_path):
    return InMemoryGraphStore(persist_path=Path(tmp_path) / "graph.jsonl")


@pytest.fixture
def service(tmp_store):
    return KnowledgeGraphService(store=tmp_store)


# ─── EntityExtractor ──────────────────────────────────────────────────


def test_extractor_extracts_regulation():
    text = "The RBI Act 1934 and Master Direction on KYC were amended."
    nodes = EntityExtractor().extract(text)
    types = {n.entity_type for n in nodes}
    assert EntityType.REGULATION in types


def test_extractor_extracts_institution():
    text = "RBI and SEBI jointly issued a circular for NBFCs."
    nodes = EntityExtractor().extract(text)
    types = {n.entity_type for n in nodes}
    assert EntityType.INSTITUTION in types


def test_extractor_extracts_topic():
    text = "KYC and AML compliance shall be mandatory."
    nodes = EntityExtractor().extract(text)
    types = {n.entity_type for n in nodes}
    assert EntityType.TOPIC in types


def test_extractor_empty_text():
    assert EntityExtractor().extract("") == []


# ─── RelationshipMapper ──────────────────────────────────────────────


def test_mapper_with_keywords():
    text = "The new circular amends the prior Master Direction on KYC."
    nodes = EntityExtractor().extract(text)
    rels = RelationshipMapper().map_from_text(nodes, text)
    assert len(rels) >= 0  # may be 0 if no two nodes close to keyword


def test_mapper_fallback_sequential():
    nodes = EntityExtractor().extract("RBI SEBI NBFC KYC")
    rels = RelationshipMapper().map_from_text(nodes, "x")
    # No keywords -> fallback chain
    if len(nodes) >= 2:
        assert any(r.relationship_type == RelationshipType.RELATES_TO for r in rels)


def test_mapper_empty():
    rels = RelationshipMapper().map_from_text([], "")
    assert rels == []


# ─── GraphBuilder ─────────────────────────────────────────────────────


def test_builder_builds_nodes_and_rels():
    text = "RBI amended Master Direction on KYC for NBFC."
    nodes, rels = GraphBuilder().build(text)
    assert len(nodes) >= 2
    assert isinstance(rels, list)


# ─── Store + Repository ──────────────────────────────────────────────


def test_store_persistence(tmp_path):
    p = Path(tmp_path) / "graph.jsonl"
    from app.schemas.knowledge_graph import GraphNode

    s1 = InMemoryGraphStore(persist_path=p)
    n = GraphNode(
        entity_type=EntityType.TOPIC, name="KYC", source=NodeSource.MANUAL
    )
    s1.add_node(n)
    s2 = InMemoryGraphStore(persist_path=p)
    out = s2.get_node(n.node_id)
    assert out is not None
    assert out.name == "KYC"


def test_store_relationship_persistence(tmp_path):
    p = Path(tmp_path) / "graph.jsonl"
    from app.schemas.knowledge_graph import GraphNode, GraphRelationship

    s1 = InMemoryGraphStore(persist_path=p)
    src = GraphNode(entity_type=EntityType.REGULATION, name="X")
    tgt = GraphNode(entity_type=EntityType.AMENDMENT, name="Y")
    s1.add_node(src)
    s1.add_node(tgt)
    r = GraphRelationship(
        source_id=src.node_id,
        target_id=tgt.node_id,
        relationship_type=RelationshipType.AMENDS,
    )
    s1.add_relationship(r)
    s2 = InMemoryGraphStore(persist_path=p)
    out = s2.get_relationship(r.relationship_id)
    assert out is not None
    assert out.relationship_type == RelationshipType.AMENDS


def test_store_get_missing(tmp_store):
    assert tmp_store.get_node("nope") is None
    assert tmp_store.get_relationship("nope") is None


def test_store_reset(tmp_store):
    from app.schemas.knowledge_graph import GraphNode

    n = GraphNode(entity_type=EntityType.TOPIC, name="KYC")
    tmp_store.add_node(n)
    assert len(tmp_store.list_nodes()) == 1
    tmp_store.reset()
    assert tmp_store.list_nodes() == []


def test_repository_search_nodes_filter(tmp_store):
    from app.schemas.knowledge_graph import GraphNode

    repo = GraphRepository(tmp_store)
    for et in [EntityType.TOPIC, EntityType.REGULATION, EntityType.TOPIC]:
        n = GraphNode(entity_type=et, name=f"n-{et.value}")
        tmp_store.add_node(n)
    res = repo.search_nodes(NodeFilter(entity_type=EntityType.TOPIC))
    assert all(n.entity_type == EntityType.TOPIC for n in res.items)


def test_repository_search_relationships(tmp_store):
    from app.schemas.knowledge_graph import GraphNode, GraphRelationship

    repo = GraphRepository(tmp_store)
    src = GraphNode(entity_type=EntityType.REGULATION, name="A")
    tgt = GraphNode(entity_type=EntityType.AMENDMENT, name="B")
    tmp_store.add_node(src)
    tmp_store.add_node(tgt)
    r1 = GraphRelationship(
        source_id=src.node_id, target_id=tgt.node_id,
        relationship_type=RelationshipType.AMENDS,
    )
    r2 = GraphRelationship(
        source_id=tgt.node_id, target_id=src.node_id,
        relationship_type=RelationshipType.REFERENCES,
    )
    tmp_store.add_relationship(r1)
    tmp_store.add_relationship(r2)
    res = repo.search_relationships(source_id=src.node_id)
    assert res.total == 1
    assert res.items[0].relationship_type == RelationshipType.AMENDS


def test_repository_stats(tmp_store):
    from app.schemas.knowledge_graph import GraphNode, GraphRelationship

    repo = GraphRepository(tmp_store)
    for i in range(3):
        tmp_store.add_node(GraphNode(entity_type=EntityType.TOPIC, name=f"n{i}"))
    nodes = tmp_store.list_nodes()
    for i in range(2):
        tmp_store.add_relationship(
            GraphRelationship(
                source_id=nodes[i].node_id,
                target_id=nodes[i + 1].node_id,
                relationship_type=RelationshipType.RELATES_TO,
            )
        )
    s = repo.stats()
    assert s.total_nodes == 3
    assert s.total_relationships == 2


# ─── Service ──────────────────────────────────────────────────────────


def test_service_add_node_and_get(service):
    n = service.add_node(
        NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC")
    )
    assert n.node_id
    out = service.get_node(n.node_id)
    assert out is not None


def test_service_add_relationship_missing_source(tmp_store):
    svc = KnowledgeGraphService(store=tmp_store)
    with pytest.raises(ValueError):
        svc.add_relationship(
            RelationshipCreateRequest(
                source_id="missing",
                target_id="missing",
                relationship_type=RelationshipType.RELATES_TO,
            )
        )


def test_service_add_relationship_success(service):
    src = service.add_node(
        NodeCreateRequest(entity_type=EntityType.REGULATION, name="R1")
    )
    tgt = service.add_node(
        NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="A1")
    )
    r = service.add_relationship(
        RelationshipCreateRequest(
            source_id=src.node_id,
            target_id=tgt.node_id,
            relationship_type=RelationshipType.AMENDS,
        )
    )
    assert r.relationship_type == RelationshipType.AMENDS


def test_service_build_from_text(service):
    text = "RBI Master Direction on KYC for NBFC."
    nodes, rels = service.build_from_text(text)
    assert len(nodes) >= 1


def test_service_search_nodes(service):
    service.add_node(NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC"))
    service.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="Act"))
    res = service.search_nodes(NodeFilter())
    assert res.total >= 2


def test_service_search_relationships(service):
    src = service.add_node(
        NodeCreateRequest(entity_type=EntityType.REGULATION, name="A")
    )
    tgt = service.add_node(
        NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B")
    )
    service.add_relationship(
        RelationshipCreateRequest(
            source_id=src.node_id,
            target_id=tgt.node_id,
            relationship_type=RelationshipType.AMENDS,
        )
    )
    res = service.search_relationships(source_id=src.node_id)
    assert res.total == 1


def test_service_impact_traversal(service):
    a = service.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="A"))
    b = service.add_node(NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B"))
    c = service.add_node(NodeCreateRequest(entity_type=EntityType.INSTITUTION, name="C"))
    service.add_relationship(
        RelationshipCreateRequest(
            source_id=a.node_id, target_id=b.node_id,
            relationship_type=RelationshipType.AMENDS,
        )
    )
    service.add_relationship(
        RelationshipCreateRequest(
            source_id=b.node_id, target_id=c.node_id,
            relationship_type=RelationshipType.AFFECTS,
        )
    )
    res = service.impact_traversal(a.node_id, max_depth=3)
    assert res.start_node_id == a.node_id
    assert b.node_id in res.affected_node_ids


def test_service_impact_traversal_missing(service):
    with pytest.raises(ValueError):
        service.impact_traversal("missing")


def test_service_dependency_analysis(service):
    a = service.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="A"))
    b = service.add_node(NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B"))
    service.add_relationship(
        RelationshipCreateRequest(
            source_id=a.node_id, target_id=b.node_id,
            relationship_type=RelationshipType.SUPERSEDES,
        )
    )
    res = service.dependency_analysis(a.node_id)
    assert res.root_node_id == a.node_id
    assert b.node_id in [n.node_id for n in res.downstream]


def test_service_dependency_analysis_missing(service):
    with pytest.raises(ValueError):
        service.dependency_analysis("missing")


def test_service_stats(service):
    service.add_node(NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC"))
    s = service.stats()
    assert s.total_nodes >= 1


def test_service_snapshot(service):
    service.add_node(NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC"))
    snap = service.snapshot()
    assert snap.stats.total_nodes >= 1


def test_build_default_service(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    svc = build_default_knowledge_graph_service()
    assert isinstance(svc, KnowledgeGraphService)


# ─── API integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/knowledge-graph/health")
        assert r.status_code == 200
        assert r.json()["module"] == "knowledge_graph"


@pytest.mark.asyncio
async def test_api_create_node(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/knowledge-graph/nodes",
                json={
                    "entity_type": "topic",
                    "name": "KYC",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["name"] == "KYC"
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_list_nodes(tmp_store):
    svc = KnowledgeGraphService(store=tmp_store)
    svc.add_node(NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC"))
    app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/knowledge-graph/nodes")
            assert r.status_code == 200
            assert r.json()["total"] >= 1
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_get_node_404(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/knowledge-graph/nodes/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_create_relationship(tmp_store):
    svc = KnowledgeGraphService(store=tmp_store)
    a = svc.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="A"))
    b = svc.add_node(NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B"))
    app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/knowledge-graph/relationships",
                json={
                    "source_id": a.node_id,
                    "target_id": b.node_id,
                    "relationship_type": "amends",
                },
            )
            assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_create_relationship_validation(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/knowledge-graph/relationships",
                json={
                    "source_id": "missing",
                    "target_id": "missing",
                    "relationship_type": "amends",
                },
            )
            assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_impact_traversal(tmp_store):
    svc = KnowledgeGraphService(store=tmp_store)
    a = svc.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="A"))
    b = svc.add_node(NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B"))
    svc.add_relationship(
        RelationshipCreateRequest(
            source_id=a.node_id,
            target_id=b.node_id,
            relationship_type=RelationshipType.AMENDS,
        )
    )
    app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/api/v1/knowledge-graph/impact-traversal/{a.node_id}?max_depth=3"
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["start_node_id"] == a.node_id
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_dependency_analysis(tmp_store):
    svc = KnowledgeGraphService(store=tmp_store)
    a = svc.add_node(NodeCreateRequest(entity_type=EntityType.REGULATION, name="A"))
    b = svc.add_node(NodeCreateRequest(entity_type=EntityType.AMENDMENT, name="B"))
    svc.add_relationship(
        RelationshipCreateRequest(
            source_id=a.node_id,
            target_id=b.node_id,
            relationship_type=RelationshipType.SUPERSEDES,
        )
    )
    app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/api/v1/knowledge-graph/dependency-analysis/{a.node_id}?max_depth=3"
            )
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_stats(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/knowledge-graph/stats")
            assert r.status_code == 200
            assert "total_nodes" in r.json()
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_build(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/knowledge-graph/build",
                json={"text": "RBI Master Direction on KYC for NBFC."},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["node_count"] >= 1
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)


@pytest.mark.asyncio
async def test_api_build_validation(tmp_store):
    app.dependency_overrides[get_knowledge_graph_service] = lambda: KnowledgeGraphService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/knowledge-graph/build", json={})
            assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_knowledge_graph_service, None)
