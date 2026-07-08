import pytest
import os
import uuid
import pickle
from httpx import AsyncClient

from app.main import app
from app.api.dependencies import get_embedding_provider
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.repositories.embedding import ChunkEmbeddingRepository
from app.services.bm25.service import BM25IndexManager, BM25RetrieverService
from app.services.embedding.retrieval import RetrievalService
from app.services.hybrid.service import HybridRetriever
from app.services.hybrid.strategy import min_max_normalize, RetrievalStrategyManager
from app.schemas.hybrid import RetrievalStrategy, FusionMethod


# Custom mock embedding provider for tests
class CustomMockEmbeddingProvider:
    def get_model_name(self) -> str:
        return "hybrid-mock-model"
    def get_dimension(self) -> int:
        return 3
    def encode_query(self, query: str) -> list[float]:
        if "KYC" in query:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]
    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0]] * len(texts)


@pytest.fixture(autouse=True)
def override_provider():
    app.dependency_overrides[get_embedding_provider] = lambda: CustomMockEmbeddingProvider()
    yield
    app.dependency_overrides.pop(get_embedding_provider, None)


def test_strategy_logic():
    # Min-max normalization tests
    assert min_max_normalize([]) == []
    assert min_max_normalize([5.0]) == [1.0]
    assert min_max_normalize([5.0, 5.0]) == [1.0, 1.0]
    
    normalized = min_max_normalize([1.0, 2.0, 3.0])
    assert pytest.approx(normalized[0]) == 0.0
    assert pytest.approx(normalized[1]) == 0.5
    assert pytest.approx(normalized[2]) == 1.0

    # Weight balancing tests
    assert RetrievalStrategyManager.balance_weights(0.0, 0.0) == (0.5, 0.5)
    assert RetrievalStrategyManager.balance_weights(-1.0, 2.0) == (0.0, 1.0)
    assert RetrievalStrategyManager.balance_weights(0.7, 0.3) == (0.7, 0.3)
    
    d, b = RetrievalStrategyManager.balance_weights(1.0, 1.0)
    assert pytest.approx(d) == 0.5
    assert pytest.approx(b) == 0.5


@pytest.mark.asyncio
async def test_hybrid_retriever_db(db_session, tmp_path):
    # Clean up any leftover data from prior tests that pollute BM25 / dense retrieval
    from sqlalchemy import delete as sa_delete
    await db_session.execute(sa_delete(ChunkEmbedding).where(ChunkEmbedding.embedding_model == "hybrid-mock-model"))
    await db_session.execute(sa_delete(DocumentChunk))
    await db_session.commit()

    # Setup test document and chunks (3 chunks total to avoid 0.0 IDF scores)
    doc = Document(
        title="RBI KYC Circular",
        source=SourceEnum.RBI,
        file_name="rbi_kyc.pdf",
        file_path="rbi_kyc.pdf",
        checksum="z" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    try:
        chunk_kyc = DocumentChunk(
            document_id=doc.id,
            page_number=1,
            section="Sec 1",
            subsection="KYC Details",
            content="KYC guidelines detail customer due diligence.",
            token_count=10
        )
        chunk_other = DocumentChunk(
            document_id=doc.id,
            page_number=2,
            section="Sec 2",
            subsection="General Details",
            content="This is general information about compliance.",
            token_count=10
        )
        chunk_dummy = DocumentChunk(
            document_id=doc.id,
            page_number=3,
            section="Sec 3",
            subsection="Dummy Details",
            content="Nothing here.",
            token_count=10
        )
        db_session.add_all([chunk_kyc, chunk_other, chunk_dummy])
        await db_session.commit()

        # Add mock embeddings for dense search
        repo = ChunkEmbeddingRepository(db_session)
        await repo.save_embedding(
            chunk_id=chunk_kyc.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await repo.save_embedding(
            chunk_id=chunk_other.id,
            embedding=[0.0, 1.0, 0.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await repo.save_embedding(
            chunk_id=chunk_dummy.id,
            embedding=[0.0, 0.0, 1.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await db_session.commit()

        # Build BM25 index
        index_manager = BM25IndexManager(db_session, storage_dir=str(tmp_path))
        await index_manager.build_index("hybrid_bm25_idx")

        # Initialize Retrievers
        bm25_retriever = BM25RetrieverService(db_session)
        dense_retriever = RetrievalService(db_session, CustomMockEmbeddingProvider())
        
        orchestrator = HybridRetriever(dense_retriever, bm25_retriever)

        # 1. Test retrieve_dense
        dense_results = await orchestrator.retrieve_dense(query="KYC", top_k=2)
        assert len(dense_results) == 2
        assert dense_results[0]["chunk_id"] == str(chunk_kyc.id)

        # 2. Test retrieve_bm25
        bm25_results = await orchestrator.retrieve_bm25(query="diligence", top_k=2)
        assert len(bm25_results) >= 1
        assert bm25_results[0]["chunk_id"] == str(chunk_kyc.id)

        # 3. Test retrieve_hybrid with Strategy: DENSE
        resp_dense_only = await orchestrator.retrieve_hybrid(
            query="KYC",
            top_n=2,
            strategy=RetrievalStrategy.DENSE
        )
        assert len(resp_dense_only.results) == 2
        assert resp_dense_only.results[0].chunk_id == str(chunk_kyc.id)
        assert resp_dense_only.metrics["dense_count"] == 3
        assert resp_dense_only.metrics["bm25_count"] == 0

        # 4. Test retrieve_hybrid with Strategy: KEYWORD (BM25)
        resp_keyword_only = await orchestrator.retrieve_hybrid(
            query="compliance",
            top_n=2,
            strategy=RetrievalStrategy.KEYWORD
        )
        assert len(resp_keyword_only.results) >= 1
        assert resp_keyword_only.results[0].chunk_id == str(chunk_other.id)
        assert resp_keyword_only.metrics["dense_count"] == 0
        assert resp_keyword_only.metrics["bm25_count"] >= 1

        # 5. Test retrieve_hybrid with Strategy: HYBRID and Fusion Method: RRF
        resp_rrf = await orchestrator.retrieve_hybrid(
            query="KYC diligence compliance",
            top_n=2,
            strategy=RetrievalStrategy.HYBRID,
            fusion_method=FusionMethod.RRF
        )
        assert len(resp_rrf.results) == 2
        assert "overall_latency_ms" in resp_rrf.metrics
        assert "overlap_percentage" in resp_rrf.metrics

        # 6. Test retrieve_hybrid with Strategy: HYBRID and Fusion Method: WEIGHTED_SUM
        resp_wsum = await orchestrator.retrieve_hybrid(
            query="KYC diligence compliance",
            top_n=2,
            strategy=RetrievalStrategy.HYBRID,
            fusion_method=FusionMethod.WEIGHTED_SUM
        )
        assert len(resp_wsum.results) == 2

    finally:
        # Clean up active BM25 files and records to prevent leakage
        await db_session.delete(doc)
        await db_session.commit()


@pytest.mark.asyncio
async def test_hybrid_search_api_flow(client: AsyncClient, db_session, tmp_path):
    # Setup test records
    doc = Document(
        title="SEBI Circular",
        source=SourceEnum.SEBI,
        file_name="sebi.pdf",
        file_path="sebi.pdf",
        checksum="w" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    try:
        chunk = DocumentChunk(
            document_id=doc.id,
            page_number=1,
            section="Sec A",
            subsection="Sub A",
            content="Guidelines for mutual fund schemes equity allocation details.",
            token_count=10
        )
        chunk_dummy1 = DocumentChunk(
            document_id=doc.id,
            page_number=2,
            section="Sec B",
            subsection="Sub B",
            content="Standard text.",
            token_count=10
        )
        chunk_dummy2 = DocumentChunk(
            document_id=doc.id,
            page_number=3,
            section="Sec C",
            subsection="Sub C",
            content="Empty details.",
            token_count=10
        )
        db_session.add_all([chunk, chunk_dummy1, chunk_dummy2])
        await db_session.commit()

        # Add mock embedding
        repo = ChunkEmbeddingRepository(db_session)
        await repo.save_embedding(
            chunk_id=chunk.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await repo.save_embedding(
            chunk_id=chunk_dummy1.id,
            embedding=[0.0, 1.0, 0.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await repo.save_embedding(
            chunk_id=chunk_dummy2.id,
            embedding=[0.0, 0.0, 1.0],
            embedding_model="hybrid-mock-model",
            embedding_dimension=3
        )
        await db_session.commit()

        # Build BM25 index
        index_manager = BM25IndexManager(db_session, storage_dir=str(tmp_path))
        await index_manager.build_index("hybrid_api_bm25_idx")

        # Test POST /api/v1/search/hybrid (Module 4.8 endpoint)
        payload = {
            "query": "KYC mutual fund guidelines",
            "top_k": 5,
            "dense_top_k": 5,
            "bm25_top_k": 5,
            "dense_weight": 0.6,
            "bm25_weight": 0.4,
            "fusion_method": "rrf",
            "rrf_k": 60,
            "use_query_analysis": False,
        }

        response = await client.post("/api/v1/search/hybrid", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "KYC mutual fund guidelines"
        assert len(data["results"]) >= 1
        assert data["results"][0]["chunk_id"] == str(chunk.id)
        assert "diagnostics" in data

    finally:
        await db_session.delete(doc)
        await db_session.commit()
