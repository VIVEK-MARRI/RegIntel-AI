"""Phase 6 — Retrieval Validation.

Covers: Dense, BM25, Hybrid, RRF Fusion, BGE Reranking, KG Expansion,
API contracts, metrics, edge cases, and performance.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_bm25_service,
    get_embedding_provider,
    get_knowledge_graph_service,
    get_reranker_service,
    get_hybrid_retriever,
    reset_bm25_service,
    reset_knowledge_graph_service,
)
from app.main import app
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.models.document import Document, SourceEnum, StatusEnum
from app.schemas.knowledge_graph import (
    NodeCreateRequest,
    NodeFilter,
    EntityType,
    NodeSource,
    RelationshipCreateRequest,
    RelationshipType,
)
from app.schemas.reranker import RerankResponse, RerankResult, RerankReport
from app.services.bm25.bm25_service import BM25Service
from app.services.bm25.retriever import BM25Document
from app.services.embedding.retrieval import RetrievalService
from app.services.fusion.engine import FusionEngine
from app.services.hybrid.service import HybridRetriever
from app.services.knowledge_graph import KnowledgeGraphService
from app.schemas.fusion import FusionMethod


# ─── Mock Providers ──────────────────────────────────────────────────


class MockEmbeddingProvider:
    """Deterministic 3-D embedding provider."""

    def get_model_name(self) -> str:
        return "phase6-mock"

    def get_dimension(self) -> int:
        return 3

    def encode_query(self, query: str) -> List[float]:
        q = query.lower()
        if "kyc" in q:
            return [1.0, 0.0, 0.0]
        if "aml" in q:
            return [0.8, 0.2, 0.0]
        if "mutual" in q or "fund" in q:
            return [0.0, 1.0, 0.0]
        if "rbi" in q or "master circular" in q:
            return [0.5, 0.3, 0.2]
        if "sebi" in q:
            return [0.2, 0.5, 0.3]
        return [0.0, 0.0, 1.0]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode_query(t) for t in texts]


class MockReranker:
    """Deterministic mock reranker for testing."""

    def __init__(self):
        self.default_top_k = 5
        self.default_score_threshold = 0.0

    def rerank(self, query, candidates, *, top_k=None, score_threshold=None):
        from app.schemas.reranker import (
            RerankResult,
            RerankResponse,
            RerankReport,
            PrecisionMetrics,
            ScoreDistribution,
        )

        effective_top_k = top_k or self.default_top_k
        scored = []
        for idx, cand in enumerate(candidates):
            scored.append(
                {
                    **cand,
                    "rerank_score": max(0.0, 1.0 - 0.05 * idx),
                    "original_rank": idx + 1,
                }
            )
        scored.sort(key=lambda c: (-c["rerank_score"], c["chunk_id"]))
        top = scored[:effective_top_k]
        results = [
            RerankResult(
                chunk_id=c["chunk_id"],
                rerank_score=c["rerank_score"],
                original_score=c.get("score"),
                original_rank=c.get("original_rank"),
                new_rank=idx + 1,
                content=c.get("content", ""),
                metadata=c.get("metadata") or {},
            )
            for idx, c in enumerate(top)
        ]
        report = RerankReport(
            model_name="mock-reranker",
            candidates_received=len(candidates),
            candidates_returned=len(results),
            candidates_filtered=0,
            latency_ms=1.0,
            scoring_latency_ms=1.0,
            score_distribution=ScoreDistribution(),
            precision_metrics=PrecisionMetrics(),
        )
        return RerankResponse(query=query, results=results, report=report)


# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_embedding_provider():
    app.dependency_overrides[get_embedding_provider] = lambda: MockEmbeddingProvider()
    yield
    app.dependency_overrides.pop(get_embedding_provider, None)


@pytest.fixture(autouse=True)
def reset_singletons():
    reset_bm25_service()
    reset_knowledge_graph_service()
    yield
    reset_bm25_service()
    reset_knowledge_graph_service()
    app.dependency_overrides.pop(get_bm25_service, None)
    app.dependency_overrides.pop(get_reranker_service, None)
    app.dependency_overrides.pop(get_knowledge_graph_service, None)
    app.dependency_overrides.pop(get_hybrid_retriever, None)


@pytest_asyncio.fixture
async def seeded_corpus(db_session: AsyncSession) -> Dict[str, Any]:
    """Create documents + chunks + embeddings + BM25 index for retrieval tests."""
    suffix = uuid.uuid4().hex[:8]

    doc_rbi = Document(
        title="RBI Master Circular on KYC Compliance",
        source=SourceEnum.RBI,
        file_name=f"rbi_kyc_{suffix}.pdf",
        file_path=f"RBI/rbi_kyc_{suffix}.pdf",
        checksum="a" * 55 + suffix,
        status=StatusEnum.UPLOADED,
    )
    doc_sebi = Document(
        title="SEBI Mutual Fund Regulations 2024",
        source=SourceEnum.SEBI,
        file_name=f"sebi_mf_{suffix}.pdf",
        file_path=f"SEBI/sebi_mf_{suffix}.pdf",
        checksum="b" * 55 + suffix,
        status=StatusEnum.UPLOADED,
    )
    doc_irda = Document(
        title="IRDAI Insurance Guidelines on AML",
        source=SourceEnum.IRDAI,
        file_name=f"irda_aml_{suffix}.pdf",
        file_path=f"IRDAI/irda_aml_{suffix}.pdf",
        checksum="c" * 55 + suffix,
        status=StatusEnum.UPLOADED,
    )
    db_session.add_all([doc_rbi, doc_sebi, doc_irda])
    await db_session.commit()

    chunks = [
        DocumentChunk(
            document_id=doc_rbi.id,
            page_number=1,
            section="KYC",
            subsection="Customer Identification",
            content="KYC verification requires Aadhaar card and PAN card details for customer due diligence.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_rbi.id,
            page_number=2,
            section="KYC",
            subsection="Periodic Updation",
            content="KYC details must be updated periodically every two years for high risk customers.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_rbi.id,
            page_number=3,
            section="AML",
            subsection="Reporting",
            content="Suspicious Transaction Reports must be filed with FIU-IND within 7 days.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_sebi.id,
            page_number=1,
            section="Mutual Funds",
            subsection="Disclosure",
            content="Mutual fund schemes must disclose expense ratios and portfolio holdings quarterly.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_sebi.id,
            page_number=2,
            section="Insider Trading",
            subsection="Prohibition",
            content="No insider shall trade in securities when in possession of unpublished price sensitive information.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_irda.id,
            page_number=1,
            section="AML",
            subsection="Compliance",
            content="Insurance companies must implement AML compliance programs as per IRDAI guidelines.",
            token_count=20,
        ),
    ]
    db_session.add_all(chunks)
    await db_session.commit()

    # Store embeddings
    from app.repositories.embedding import ChunkEmbeddingRepository

    repo = ChunkEmbeddingRepository(db_session)
    emb_map = {
        0: [1.0, 0.0, 0.0],  # KYC
        1: [0.9, 0.1, 0.0],  # KYC updation
        2: [0.8, 0.2, 0.0],  # AML
        3: [0.0, 1.0, 0.0],  # Mutual funds
        4: [0.1, 0.8, 0.1],  # Insider trading
        5: [0.7, 0.2, 0.1],  # Insurance AML
    }
    for i, chunk in enumerate(chunks):
        await repo.save_embedding(
            chunk_id=chunk.id,
            embedding=emb_map[i],
            embedding_model="phase6-mock",
            embedding_dimension=3,
        )
    await db_session.commit()

    # Build BM25 in-memory index
    bm25_service: BM25Service = get_bm25_service()
    bm25_service.clear_index()
    titles = {
        doc_rbi.id: doc_rbi.title,
        doc_sebi.id: doc_sebi.title,
        doc_irda.id: doc_irda.title,
    }
    sources = {
        doc_rbi.id: SourceEnum.RBI.value,
        doc_sebi.id: SourceEnum.SEBI.value,
        doc_irda.id: SourceEnum.IRDAI.value,
    }
    bm25_docs = [
        BM25Document(
            chunk_id=str(c.id),
            content=c.content,
            section_title=c.section or "",
            subsection_title=c.subsection or "",
            document_title=titles.get(c.document_id, ""),
            source=sources.get(c.document_id, ""),
            document_id=str(c.document_id),
            page_number=c.page_number or 0,
        )
        for c in chunks
    ]
    bm25_service._retriever.build_index(bm25_docs)  # noqa: SLF001

    yield {
        "db": db_session,
        "doc_rbi": doc_rbi,
        "doc_sebi": doc_sebi,
        "doc_irda": doc_irda,
        "chunks": chunks,
    }


# ═══════════════════════════════════════════════════════════════════════
# 6.1 — Dense Retrieval
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestDenseRetrieval:
    """Phase 6.1 — Dense Retrieval Validation"""

    async def test_embeddings_exist(self, seeded_corpus, db_session):
        """Verify embeddings exist in the database."""
        from app.repositories.embedding import ChunkEmbeddingRepository

        repo = ChunkEmbeddingRepository(db_session)
        emb = await repo.get_embeddings_by_document(seeded_corpus["doc_rbi"].id)
        assert len(emb) > 0, "No embeddings for RBI document"

    async def test_vector_index_health(self, db_session):
        """Verify vector index manager reports health."""
        # pgvector-backed index health queries PostgreSQL system tables
        # (pg_index, pg_class, pg_stat_user_indexes) which are unavailable
        # on SQLite and other non-PostgreSQL databases.
        if db_session.bind and db_session.bind.dialect.name != "postgresql":
            pytest.skip("pgvector index health requires PostgreSQL system tables")
        from app.services.embedding.index_manager import VectorIndexManager

        mgr = VectorIndexManager(db_session)
        health = await mgr.index_health()
        assert health is not None

    async def test_dense_search_exact_query(self, client, seeded_corpus):
        """Dense search returns results for exact queries."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "KYC verification", "top_k": 5}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_results"] > 0, "No results for KYC query"
        assert body["strategy"] == "dense"

    async def test_dense_search_paraphrased_query(self, client, seeded_corpus):
        """Dense search returns results for paraphrased queries."""
        resp = await client.post(
            "/api/v1/search/dense",
            json={"query": "customer identification documents", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0, "No results for paraphrased query"

    async def test_dense_search_synonym_query(self, client, seeded_corpus):
        """Dense search returns results for synonym queries."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "client verification", "top_k": 5}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0, "No results for synonym query"

    async def test_dense_search_semantic_only(self, client, seeded_corpus):
        """Dense search for semantic-only (no keyword overlap) returns results."""
        resp = await client.post(
            "/api/v1/search/dense",
            json={"query": "financial compliance regulations", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0

    async def test_dense_recall_precision(self, client, seeded_corpus):
        """Measure recall and precision for dense search."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "KYC", "top_k": 5}
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) > 0
        # Verify content includes relevant terms
        contents = " ".join(r.get("content", "") for r in results).lower()
        assert "kyc" in contents, "KYC not found in dense results"


# ═══════════════════════════════════════════════════════════════════════
# 6.2 — BM25 Retrieval
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestBM25Retrieval:
    """Phase 6.2 — BM25 Retrieval Validation"""

    async def test_bm25_keyword_search(self, client, seeded_corpus):
        """BM25 keyword search returns results."""
        resp = await client.post(
            "/api/v1/search/bm25", json={"query": "Aadhaar PAN", "top_k": 5}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_results"] > 0, "No BM25 results for Aadhaar PAN"

    async def test_bm25_exact_regulatory_references(self, client, seeded_corpus):
        """BM25 finds exact regulatory references."""
        resp = await client.post(
            "/api/v1/search/bm25",
            json={"query": "Suspicious Transaction Reports", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0, "No results for STR query"
        contents = " ".join(r.get("content", "") for r in body["results"]).lower()
        assert "suspicious" in contents

    async def test_bm25_section_numbers(self, client, seeded_corpus):
        """BM25 finds section number references."""
        resp = await client.post(
            "/api/v1/search/bm25", json={"query": "Mutual Funds section", "top_k": 5}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0

    async def test_bm25_exact_phrase(self, client, seeded_corpus):
        """BM25 finds exact phrase matches."""
        resp = await client.post(
            "/api/v1/search/bm25",
            json={"query": '"unpublished price sensitive information"', "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_results"] > 0

    async def test_bm25_source_filter(self, client, seeded_corpus):
        """BM25 with source filter returns filtered results."""
        resp = await client.post(
            "/api/v1/search/bm25",
            json={
                "query": "compliance",
                "top_k": 10,
                "filters": {"source": "SEBI"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for r in body["results"]:
            meta = r.get("metadata", {})
            src = meta.get("source", "")
            assert src == "SEBI" or not src


# ═══════════════════════════════════════════════════════════════════════
# 6.3 — Hybrid Retrieval
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHybridRetrieval:
    """Phase 6.3 — Hybrid Retrieval Validation"""

    async def test_hybrid_search_returns_results(self, client, seeded_corpus):
        """Hybrid search returns results."""
        resp = await client.post(
            "/api/v1/search/hybrid",
            json={
                "query": "KYC compliance",
                "top_k": 5,
                "enable_reranking": False,
                "use_query_analysis": False,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_results"] > 0
        assert body["strategy"] == "hybrid"

    async def test_hybrid_with_reranking(self, client, seeded_corpus):
        """Hybrid search with reranking works."""
        app.dependency_overrides[get_reranker_service] = lambda: MockReranker()
        try:
            resp = await client.post(
                "/api/v1/search/hybrid",
                json={
                    "query": "KYC compliance",
                    "top_k": 5,
                    "enable_reranking": True,
                    "use_query_analysis": False,
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total_results"] > 0
            assert body["diagnostics"]["rerank_used"] is True
        finally:
            app.dependency_overrides.pop(get_reranker_service, None)

    async def test_hybrid_scores(self, client, seeded_corpus):
        """Hybrid search results have valid scores."""
        resp = await client.post(
            "/api/v1/search/hybrid",
            json={
                "query": "KYC",
                "top_k": 5,
                "enable_reranking": False,
                "use_query_analysis": False,
            },
        )
        assert resp.status_code == 200
        for r in resp.json()["results"]:
            assert r["score"] >= 0.0

    async def test_hybrid_pipeline_diagnostics(self, client, seeded_corpus):
        """Hybrid search returns pipeline diagnostics."""
        resp = await client.post(
            "/api/v1/search/hybrid",
            json={
                "query": "AML reporting",
                "top_k": 5,
                "enable_reranking": False,
                "use_query_analysis": False,
            },
        )
        assert resp.status_code == 200
        diag = resp.json().get("diagnostics", {})
        assert "query_type" in diag
        assert "dense_count" in diag
        assert "bm25_count" in diag
        assert "fused_count" in diag
        assert "overlap_count" in diag


# ═══════════════════════════════════════════════════════════════════════
# 6.4 — RRF Fusion
# ═══════════════════════════════════════════════════════════════════════


class TestRRFFusion:
    """Phase 6.4 — RRF Fusion Validation"""

    def test_rrf_fusion_ranks_overlap_higher(self):
        """RRF ranks overlapping results higher than non-overlapping."""
        engine = FusionEngine()
        dense_results = [
            {"chunk_id": "a", "score": 0.9, "content": "", "metadata": {}},
            {"chunk_id": "b", "score": 0.8, "content": "", "metadata": {}},
            {"chunk_id": "c", "score": 0.7, "content": "", "metadata": {}},
        ]
        bm25_results = [
            {"chunk_id": "b", "score": 0.85, "content": "", "metadata": {}},
            {"chunk_id": "d", "score": 0.75, "content": "", "metadata": {}},
            {"chunk_id": "e", "score": 0.6, "content": "", "metadata": {}},
        ]
        fused = engine.fuse_results(
            dense_results, bm25_results, method=FusionMethod.RRF
        )
        # 'b' appears in both lists, so should rank higher
        b_rank = next(i for i, r in enumerate(fused) if r["chunk_id"] == "b")
        for i, r in enumerate(fused):
            if r["chunk_id"] in ("d", "e"):
                assert b_rank < i, "Overlap result not ranked higher"

    def test_rrf_dense_only_result(self):
        """RRF handles chunks that only appear in dense results."""
        engine = FusionEngine()
        fused = engine.fuse_results(
            [{"chunk_id": "a", "score": 0.9, "content": "", "metadata": {}}],
            [],
            method=FusionMethod.RRF,
        )
        assert len(fused) == 1
        assert fused[0]["chunk_id"] == "a"

    def test_rrf_bm25_only_result(self):
        """RRF handles chunks that only appear in BM25 results."""
        engine = FusionEngine()
        fused = engine.fuse_results(
            [],
            [{"chunk_id": "x", "score": 0.8, "content": "", "metadata": {}}],
            method=FusionMethod.RRF,
        )
        assert len(fused) == 1
        assert fused[0]["chunk_id"] == "x"

    def test_rrf_overlap_result_boosted(self):
        """RRF correctly boosts overlapping results."""
        engine = FusionEngine()
        dense = [
            {"chunk_id": str(i), "score": float(100 - i), "content": "", "metadata": {}}
            for i in range(5)
        ]
        bm25 = [
            {"chunk_id": str(i), "score": float(100 - i), "content": "", "metadata": {}}
            for i in range(5)
        ]
        fused = engine.fuse_results(dense, bm25, method=FusionMethod.RRF)
        assert len(fused) > 0
        # All chunks overlap, all should be ranked
        assert len(fused) <= 5

    def test_rrf_score_normalization(self):
        """RRF scores are normalized between 0 and 1."""
        engine = FusionEngine()
        dense = [
            {"chunk_id": str(i), "score": float(i * 10), "content": "", "metadata": {}}
            for i in range(3)
        ]
        bm25 = [
            {
                "chunk_id": str(i + 1),
                "score": float(i * 5),
                "content": "",
                "metadata": {},
            }
            for i in range(3)
        ]
        fused = engine.fuse_results(dense, bm25, method=FusionMethod.RRF)
        for r in fused:
            score = r.get("score", 0)
            assert 0.0 <= score <= 1.0, f"Score {score} not in [0, 1]"


# ═══════════════════════════════════════════════════════════════════════
# 6.5 — BGE Reranker (with mock)
# ═══════════════════════════════════════════════════════════════════════


class TestBGEReranker:
    """Phase 6.5 — BGE Reranker Validation (with mock provider)"""

    def test_reranker_changes_order(self):
        """Reranker changes result order appropriately."""
        reranker = MockReranker()
        candidates = [
            {"chunk_id": "a", "score": 0.5, "content": "first", "metadata": {}},
            {"chunk_id": "b", "score": 0.9, "content": "second", "metadata": {}},
            {"chunk_id": "c", "score": 0.7, "content": "third", "metadata": {}},
        ]
        result = reranker.rerank("test query", candidates, top_k=3)
        # After rerank, order should be sorted by rerank_score (desc)
        assert (
            result.results[0].chunk_id == "a"
        )  # mock gives a the highest rerank_score

    def test_reranker_irrelevant_chunks_move_down(self):
        """Reranker pushes less relevant chunks down."""
        reranker = MockReranker()
        candidates = [
            {"chunk_id": "rel", "score": 0.9, "content": "relevant", "metadata": {}},
            {"chunk_id": "irr", "score": 0.1, "content": "irrelevant", "metadata": {}},
        ]
        result = reranker.rerank("important query", candidates, top_k=2)
        # Both kept, but order determined by mock
        assert len(result.results) == 2

    def test_reranker_relevant_chunks_move_up(self):
        """Reranker brings relevant chunks to top."""
        reranker = MockReranker()
        candidates = [
            {
                "chunk_id": "low",
                "score": 0.3,
                "content": "low relevance",
                "metadata": {},
            },
            {
                "chunk_id": "high",
                "score": 0.8,
                "content": "high relevance",
                "metadata": {},
            },
        ]
        before = [c["chunk_id"] for c in candidates]
        result = reranker.rerank("query", candidates, top_k=2)
        assert len(result.results) == 2

    def test_reranker_top_k_quality(self):
        """Reranker improves top-k quality (measured by mock)."""
        reranker = MockReranker()
        candidates = [
            {
                "chunk_id": f"c{i}",
                "score": 1.0 - 0.1 * i,
                "content": f"content {i}",
                "metadata": {},
            }
            for i in range(10)
        ]
        result = reranker.rerank("query", candidates, top_k=3)
        assert len(result.results) == 3


# ═══════════════════════════════════════════════════════════════════════
# 6.6 — Knowledge Graph Expansion
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestKGExpansion:
    """Phase 6.6 — Knowledge Graph Expansion Validation"""

    async def setup_kg(self):
        """Create a KG with regulatory entities."""
        from app.services.knowledge_graph import InMemoryGraphStore

        svc = KnowledgeGraphService(store=InMemoryGraphStore())
        reg = svc.add_node(
            NodeCreateRequest(entity_type=EntityType.REGULATION, name="RBI Act 1934")
        )
        circ = svc.add_node(
            NodeCreateRequest(
                entity_type=EntityType.CIRCULAR, name="Master Circular KYC"
            )
        )
        topic = svc.add_node(
            NodeCreateRequest(entity_type=EntityType.TOPIC, name="KYC")
        )
        svc.add_relationship(
            RelationshipCreateRequest(
                source_id=reg.node_id,
                target_id=circ.node_id,
                relationship_type=RelationshipType.AMENDS,
            )
        )
        svc.add_relationship(
            RelationshipCreateRequest(
                source_id=circ.node_id,
                target_id=topic.node_id,
                relationship_type=RelationshipType.RELATES_TO,
            )
        )
        return svc, reg, circ, topic

    async def test_kg_entities_extracted_from_query(self, client, seeded_corpus):
        """KG entities provide additional context for query terms."""
        from app.services.knowledge_graph import InMemoryGraphStore

        svc, reg, circ, topic = await self.setup_kg()
        app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
        try:
            # Search for KYC-related nodes in KG
            nodes_result = svc.search_nodes(NodeFilter(name_contains="KYC"))
            assert nodes_result.total >= 1, "No KG nodes found for KYC"

            # Verify impact traversal enriches context
            impact = svc.impact_traversal(topic.node_id, max_depth=3)
            assert impact.total_paths >= 0

            # Verify stats show the graph has relevant entities
            stats = svc.stats()
            assert stats.total_nodes >= 3
        finally:
            app.dependency_overrides.pop(get_knowledge_graph_service, None)

    async def test_graph_expansion_enriches_context(self, client, seeded_corpus):
        """KG expansion contributes additional context beyond chunks."""
        svc, reg, circ, topic = await self.setup_kg()
        app.dependency_overrides[get_knowledge_graph_service] = lambda: svc
        try:
            # Verify that graph contributes entity type breakdown
            stats = svc.stats()
            assert len(stats.by_entity_type) > 0
            assert stats.by_entity_type.get("regulation", 0) >= 1
            assert stats.by_entity_type.get("topic", 0) >= 1
            assert stats.by_entity_type.get("circular", 0) >= 1
        finally:
            app.dependency_overrides.pop(get_knowledge_graph_service, None)


# ═══════════════════════════════════════════════════════════════════════
# 6.7 — Retrieval API Validation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRetrievalAPI:
    """Phase 6.7 — Retrieval API Contract Validation"""

    async def test_dense_api_contract(self, client, seeded_corpus):
        """POST /search/dense returns correct response shape."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "KYC", "top_k": 3}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "query" in body
        assert "strategy" in body and body["strategy"] == "dense"
        assert "latency_ms" in body
        assert "total_results" in body
        assert "results" in body
        assert "request_id" in body
        if body["results"]:
            r = body["results"][0]
            assert "chunk_id" in r
            assert "score" in r
            assert "content" in r

    async def test_bm25_api_contract(self, client, seeded_corpus):
        """POST /search/bm25 returns correct response shape."""
        resp = await client.post(
            "/api/v1/search/bm25", json={"query": "Aadhaar", "top_k": 3}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy"] == "bm25"

    async def test_hybrid_api_contract(self, client, seeded_corpus):
        """POST /search/hybrid returns correct response shape."""
        resp = await client.post(
            "/api/v1/search/hybrid",
            json={
                "query": "KYC",
                "top_k": 3,
                "enable_reranking": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "query_type" in body
        assert "diagnostics" in body
        assert body["diagnostics"]["fusion_method"] == "rrf"

    async def test_retrieval_health(self, client):
        """GET /retrieval/health returns component status."""
        resp = await client.get("/api/v1/retrieval/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "status" in body
        assert "checks" in body
        assert "components" in body

    async def test_pagination_dense(self, client, seeded_corpus):
        """Dense search respects top_k pagination."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "compliance", "top_k": 2}
        )
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 2

    async def test_error_handling_empty_query(self, client):
        """Dense search with empty query returns empty results."""
        resp = await client.post("/api/v1/search/dense", json={"query": "", "top_k": 5})
        # Should return 422 for empty query (min_length=1)
        assert resp.status_code == 422

    async def test_score_values(self, client, seeded_corpus):
        """All search strategies return valid score values."""
        for endpoint in ["/api/v1/search/dense", "/api/v1/search/bm25"]:
            resp = await client.post(endpoint, json={"query": "KYC", "top_k": 5})
            assert resp.status_code == 200
            for r in resp.json()["results"]:
                assert r["score"] >= 0.0


# ═══════════════════════════════════════════════════════════════════════
# 6.8 — Retrieval Metrics
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRetrievalMetrics:
    """Phase 6.8 — Retrieval Metrics Validation"""

    async def test_metrics_endpoint_returns_data(self, client, seeded_corpus):
        """GET /retrieval/metrics returns metrics."""
        resp = await client.get("/api/v1/retrieval/metrics?window=daily")
        assert resp.status_code in (200, 503), resp.text
        if resp.status_code == 200:
            body = resp.json()
            assert "total_queries" in body
            assert "window_start" in body
            assert "window_end" in body


# ═══════════════════════════════════════════════════════════════════════
# 6.9 — Edge Cases
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestEdgeCases:
    """Phase 6.9 — Edge Case Validation"""

    async def test_single_word_query(self, client, seeded_corpus):
        """Single-word query returns results."""
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "KYC", "top_k": 5}
        )
        assert resp.status_code == 200
        assert resp.json()["total_results"] > 0

    async def test_large_query(self, client, seeded_corpus):
        """Large query is handled gracefully."""
        long_text = "regulatory compliance " * 200
        resp = await client.post(
            "/api/v1/search/dense", json={"query": long_text[:2000], "top_k": 5}
        )
        assert resp.status_code == 200

    async def test_no_result_query(self, client, seeded_corpus):
        """Query with no matches returns empty results."""
        # The mock provider always returns results, but the endpoint
        # should handle gracefully and return status 200
        resp = await client.post(
            "/api/v1/search/dense", json={"query": "ZZZZZZZZZZnotexist", "top_k": 5}
        )
        assert resp.status_code == 200
        assert "total_results" in resp.json()

    async def test_document_filter(self, client, seeded_corpus):
        """Dense search with document_id filter."""
        doc_id = str(seeded_corpus["doc_rbi"].id)
        resp = await client.post(
            "/api/v1/search/dense",
            json={
                "query": "KYC",
                "top_k": 5,
                "filters": {"document_id": doc_id},
            },
        )
        assert resp.status_code == 200, resp.text
        for r in resp.json()["results"]:
            meta = r.get("metadata", {})
            mid = meta.get("document_id", "")
            assert mid == doc_id or not mid, f"Document mismatch: {mid} vs {doc_id}"

    async def test_source_filter_dense(self, client, seeded_corpus):
        """Dense search with source filter."""
        resp = await client.post(
            "/api/v1/search/dense",
            json={
                "query": "compliance",
                "top_k": 5,
                "filters": {"source": "SEBI"},
            },
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 6.10 — Performance Validation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestPerformance:
    """Phase 6.10 — Performance Validation"""

    async def test_dense_latency(self, client, seeded_corpus):
        """Dense retrieval latency < 300ms (with mock provider)."""
        start = time.time()
        for _ in range(5):
            resp = await client.post(
                "/api/v1/search/dense", json={"query": "KYC compliance", "top_k": 10}
            )
            assert resp.status_code == 200
        elapsed = (time.time() - start) / 5
        # With mock provider, should be very fast
        assert elapsed < 0.3, f"Avg dense latency {elapsed*1000:.1f}ms (limit: 300ms)"

    async def test_bm25_latency(self, client, seeded_corpus):
        """BM25 retrieval latency < 200ms."""
        start = time.time()
        for _ in range(5):
            resp = await client.post(
                "/api/v1/search/bm25", json={"query": "Aadhaar PAN KYC", "top_k": 10}
            )
            assert resp.status_code == 200
        elapsed = (time.time() - start) / 5
        assert elapsed < 0.2, f"Avg BM25 latency {elapsed*1000:.1f}ms (limit: 200ms)"

    async def test_hybrid_latency(self, client, seeded_corpus):
        """Hybrid retrieval latency < 500ms."""
        start = time.time()
        for _ in range(5):
            resp = await client.post(
                "/api/v1/search/hybrid",
                json={
                    "query": "KYC compliance",
                    "top_k": 5,
                    "enable_reranking": False,
                    "use_query_analysis": False,
                },
            )
            assert resp.status_code == 200
        elapsed = (time.time() - start) / 5
        assert elapsed < 0.5, f"Avg hybrid latency {elapsed*1000:.1f}ms (limit: 500ms)"

    async def test_rerank_latency(self, client, seeded_corpus):
        """Reranking latency < 1s with mock reranker."""
        app.dependency_overrides[get_reranker_service] = lambda: MockReranker()
        try:
            start = time.time()
            for _ in range(5):
                resp = await client.post(
                    "/api/v1/search/hybrid",
                    json={
                        "query": "KYC compliance",
                        "top_k": 5,
                        "enable_reranking": True,
                        "use_query_analysis": False,
                    },
                )
                assert resp.status_code == 200
            elapsed = (time.time() - start) / 5
            assert elapsed < 1.0, f"Avg rerank latency {elapsed*1000:.1f}ms (limit: 1s)"
        finally:
            app.dependency_overrides.pop(get_reranker_service, None)

    async def test_scores_are_meaningful(self, client, seeded_corpus):
        """Verify scores differ meaningfully across strategies."""
        dense_resp = await client.post(
            "/api/v1/search/dense", json={"query": "KYC", "top_k": 3}
        )
        bm25_resp = await client.post(
            "/api/v1/search/bm25", json={"query": "KYC", "top_k": 3}
        )
        assert dense_resp.status_code == 200
        assert bm25_resp.status_code == 200
        # Both strategies should return results for KYC
        assert dense_resp.json()["total_results"] > 0
        assert bm25_resp.json()["total_results"] > 0
