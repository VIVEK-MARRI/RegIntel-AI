import pytest
import uuid
from httpx import AsyncClient
from app.main import app
from app.api.dependencies import get_embedding_provider
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.repositories.embedding import ChunkEmbeddingRepository

# 1. Custom mock embedding provider for tests
class CustomMockEmbeddingProvider:
    def get_model_name(self) -> str:
        return "custom-3d-model"
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


@pytest.mark.asyncio
async def test_semantic_search_api_flow(client: AsyncClient, db_session):
    # Setup standard document and chunk entries
    doc_rbi = Document(
        title="RBI Circular for KYC",
        source=SourceEnum.RBI,
        file_name="rbi_kyc.pdf",
        file_path="RBI/rbi_kyc.pdf",
        checksum="x" * 64,
        status=StatusEnum.UPLOADED
    )
    doc_sebi = Document(
        title="SEBI Circular for Mutual Funds",
        source=SourceEnum.SEBI,
        file_name="sebi_mutual_funds.pdf",
        file_path="SEBI/sebi_mutual_funds.pdf",
        checksum="y" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add_all([doc_rbi, doc_sebi])
    await db_session.commit()

    chunk_kyc = DocumentChunk(
        document_id=doc_rbi.id,
        page_number=1,
        section="Section 1",
        subsection="KYC Process",
        content="KYC guidelines detail customer diligence procedures.",
        token_count=15
    )
    chunk_gen = DocumentChunk(
        document_id=doc_sebi.id,
        page_number=2,
        section="Section 2",
        subsection="Mutual Funds",
        content="Mutual funds must detail equity allocation guidelines.",
        token_count=20
    )
    db_session.add_all([chunk_kyc, chunk_gen])
    await db_session.commit()

    # Create matching embeddings in DB
    repo = ChunkEmbeddingRepository(db_session)
    await repo.save_embedding(
        chunk_id=chunk_kyc.id,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="custom-3d-model",
        embedding_dimension=3
    )
    await repo.save_embedding(
        chunk_id=chunk_gen.id,
        embedding=[0.0, 1.0, 0.0],
        embedding_model="custom-3d-model",
        embedding_dimension=3
    )
    await db_session.commit()

    # ----------------------------------------------------
    # Test 1: POST /api/v1/search (Valid request)
    # ----------------------------------------------------
    payload = {
        "query": "KYC guidelines",
        "top_k": 5,
        "score_threshold": 0.0,
        "distance_metric": "cosine"
    }
    response = await client.post("/api/v1/search", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query"] == "KYC guidelines"
    assert len(res_data["results"]) == 2
    
    # KYC chunk is the exact match (score = 1.0)
    assert res_data["results"][0]["chunk_id"] == str(chunk_kyc.id)
    assert pytest.approx(res_data["results"][0]["score"], abs=1e-5) == 1.0

    # ----------------------------------------------------
    # Test 2: POST /api/v1/search (Filtering by Source)
    # ----------------------------------------------------
    payload_filter = {
        "query": "KYC guidelines",
        "top_k": 5,
        "source": "RBI"
    }
    response = await client.post("/api/v1/search", json=payload_filter)
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data["results"]) == 1
    assert res_data["results"][0]["chunk_id"] == str(chunk_kyc.id)

    # ----------------------------------------------------
    # Test 3: POST /api/v1/search (Pagination: skip & limit)
    # ----------------------------------------------------
    payload_page = {
        "query": "KYC guidelines",
        "skip": 1,
        "limit": 1
    }
    response = await client.post("/api/v1/search", json=payload_page)
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data["results"]) == 1
    # First match (KYC) skipped, returns second match (Gen)
    assert res_data["results"][0]["chunk_id"] == str(chunk_gen.id)

    # ----------------------------------------------------
    # Test 4: POST /api/v1/search (Validation: invalid metric name)
    # ----------------------------------------------------
    payload_invalid = {
        "query": "KYC guidelines",
        "distance_metric": "invalid_metric"
    }
    response = await client.post("/api/v1/search", json=payload_invalid)
    assert response.status_code == 400
    assert "Unsupported distance metric" in response.json()["detail"]

    # ----------------------------------------------------
    # Test 5: POST /api/v1/search (Validation: field bounds error)
    # ----------------------------------------------------
    payload_bounds = {
        "query": "KYC guidelines",
        "score_threshold": 1.5  # Greater than ge=0.0, le=1.0 limit
    }
    response = await client.post("/api/v1/search", json=payload_bounds)
    assert response.status_code == 422

    # ----------------------------------------------------
    # Test 6: GET /api/v1/embeddings/stats
    # ----------------------------------------------------
    response = await client.get("/api/v1/embeddings/stats")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["model_name"] == "custom-3d-model"
    assert res_data["dimension"] == 3
    assert res_data["total_chunks"] == 2
    assert res_data["total_embeddings"] == 2
    assert pytest.approx(res_data["coverage"], abs=1e-5) == 100.0
    assert res_data["status_counts"]["COMPLETED"] == 2

    # ----------------------------------------------------
    # Test 7: POST /api/v1/index/rebuild
    # ----------------------------------------------------
    response = await client.post("/api/v1/index/rebuild", json={})
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert len(res_data["rebuilt_indexes"]) > 0

    # ----------------------------------------------------
    # Test 8: GET /api/v1/search/health
    # ----------------------------------------------------
    response = await client.get("/api/v1/search/health")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "healthy"
    assert res_data["is_consistent"] is True
    assert "index_health" in res_data
    assert "consistency_details" in res_data

    # Cleanup database
    await db_session.delete(doc_rbi)
    await db_session.delete(doc_sebi)
    await db_session.commit()
