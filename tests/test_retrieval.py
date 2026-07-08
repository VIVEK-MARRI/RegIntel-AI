import pytest
import uuid
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding.retrieval import RetrievalService
from test_embedding_pipeline import MockEmbeddingProvider


@pytest.mark.asyncio
async def test_semantic_retrieval_flow(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)

    # We will use a mock embedding provider with 3 dimensions
    # Query vector: [1.0, 0.0, 0.0]
    # We mock the provider: get_model_name, get_dimension, encode_query, encode_batch
    class CustomMockEmbeddingProvider:
        def get_model_name(self) -> str:
            return "custom-3d-model"

        def get_dimension(self) -> int:
            return 3

        def encode_query(self, query: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        def encode_batch(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0]] * len(texts)

    mock_provider = CustomMockEmbeddingProvider()
    retrieval_service = RetrievalService(db_session, mock_provider)

    # 2. Register document and chunks
    doc_rbi = Document(
        title="RBI KYC Circular",
        source=SourceEnum.RBI,
        file_name="rbi_kyc.pdf",
        file_path="RBI/rbi_kyc.pdf",
        checksum="a" * 64,
        status=StatusEnum.UPLOADED,
    )
    doc_sebi = Document(
        title="SEBI Fund Circular",
        source=SourceEnum.SEBI,
        file_name="sebi_fund.pdf",
        file_path="SEBI/sebi_fund.pdf",
        checksum="b" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc_rbi)
    db_session.add(doc_sebi)
    await db_session.commit()

    # Register chunks
    chunks_rbi = [
        {
            "content": "RBI kyc section guidelines passage",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "RBI Customer diligence passage",
            "section": "Sec 2",
            "subsection": "",
            "page_number": 2,
            "token_count": 12,
        },
    ]
    chunks_sebi = [
        {
            "content": "SEBI Mutual fund passage",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]

    registered_rbi = await chunk_service.register_chunks_bulk(doc_rbi.id, chunks_rbi)
    registered_sebi = await chunk_service.register_chunks_bulk(doc_sebi.id, chunks_sebi)

    # 3. Manually create embeddings with distinct vectors
    # We want to test different scores and rank tie-breaking
    from app.repositories.embedding import ChunkEmbeddingRepository

    repo = ChunkEmbeddingRepository(db_session)

    # Chunk RBI 1: embedding [1.0, 0.0, 0.0] (Exact match to query [1.0, 0.0, 0.0])
    # Dot product: 1.0, Cosine Similarity: 1.0, L2 distance: 0.0 (L2 sim = 1.0)
    await repo.save_embedding(
        chunk_id=registered_rbi[0].id,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="custom-3d-model",
        embedding_dimension=3,
    )

    # Chunk RBI 2: embedding [0.8, 0.6, 0.0]
    # Dot product: 0.8, Cosine Similarity: 0.8 (since both vectors normalized), L2 distance = sqrt(0.04+0.36) = sqrt(0.4) = 0.632
    # L2 sim = 1 / (1 + 0.632) = 0.612
    await repo.save_embedding(
        chunk_id=registered_rbi[1].id,
        embedding=[0.8, 0.6, 0.0],
        embedding_model="custom-3d-model",
        embedding_dimension=3,
    )

    # Chunk SEBI 1: embedding [0.8, 0.6, 0.0] (Same embedding to test tie-breaking / filtering)
    await repo.save_embedding(
        chunk_id=registered_sebi[0].id,
        embedding=[0.8, 0.6, 0.0],
        embedding_model="custom-3d-model",
        embedding_dimension=3,
    )

    await db_session.commit()

    # 4. Test Semantic Retrieval (No filters, top_k=5)
    response = await retrieval_service.retrieve(
        query="KYC circular guidelines",
        top_k=5,
        score_threshold=0.0,
        distance_metric="cosine",
    )

    assert "results" in response
    assert "trace" in response
    assert len(response["results"]) == 3

    # First match should be chunk_rbi[0] (score = 1.0)
    assert response["results"][0]["chunk_id"] == str(registered_rbi[0].id)
    assert pytest.approx(response["results"][0]["score"], abs=1e-5) == 1.0

    # Second and third matches should have score = 0.8
    assert pytest.approx(response["results"][1]["score"], abs=1e-5) == 0.8
    assert pytest.approx(response["results"][2]["score"], abs=1e-5) == 0.8

    # 5. Test Filtering by Source (RBI only)
    response_rbi = await retrieval_service.retrieve(
        query="KYC", top_k=5, source=SourceEnum.RBI
    )
    assert len(response_rbi["results"]) == 2
    for r in response_rbi["results"]:
        assert r["chunk_id"] in [str(registered_rbi[0].id), str(registered_rbi[1].id)]

    # 6. Test Filtering by Document ID (SEBI document only)
    response_sebi = await retrieval_service.retrieve(
        query="Mutual Fund", top_k=5, document_id=doc_sebi.id
    )
    assert len(response_sebi["results"]) == 1
    assert response_sebi["results"][0]["chunk_id"] == str(registered_sebi[0].id)

    # 7. Test Score Threshold Filtering
    # Only RBI 1 should pass threshold 0.9
    response_threshold = await retrieval_service.retrieve(
        query="KYC", top_k=5, score_threshold=0.9
    )
    assert len(response_threshold["results"]) == 1
    assert response_threshold["results"][0]["chunk_id"] == str(registered_rbi[0].id)

    # 8. Test Deterministic Tie-breaking
    # RBI 2 and SEBI 1 have identical score (0.8).
    # Since they have identical score, they must sort by chunk_id ascending.
    response_all = await retrieval_service.retrieve(query="KYC", top_k=5)
    chunk_id_1 = uuid.UUID(response_all["results"][1]["chunk_id"])
    chunk_id_2 = uuid.UUID(response_all["results"][2]["chunk_id"])
    assert chunk_id_1 < chunk_id_2

    # 9. Verify trace values
    trace = response_all["trace"]
    assert trace["query"] == "KYC"
    assert trace["metric"] == "cosine"
    assert trace["top_k"] == 5
    assert trace["duration_ms"] > 0
    assert trace["candidates_scanned"] == 3

    # Cleanup
    await doc_service.repository.delete(doc_rbi)
    await doc_service.repository.delete(doc_sebi)
    await db_session.commit()
