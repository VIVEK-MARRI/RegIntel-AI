import pytest
import uuid
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding.retrieval import RetrievalService
from app.services.bm25.service import BM25IndexManager, BM25RetrieverService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_supersession_retrieval_flow(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)

    # We use a mock embedding provider
    class CustomMockEmbeddingProvider:
        def get_model_name(self) -> str:
            return "supersession-3d-model"

        def get_dimension(self) -> int:
            return 3

        def encode_query(self, query: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        def encode_batch(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0]] * len(texts)

    mock_provider = CustomMockEmbeddingProvider()
    retrieval_service = RetrievalService(db_session, mock_provider)

    # 2. Register active and superseded documents
    # Let's first register the active document
    doc_active = Document(
        title="RBI KYC Active Circular",
        source=SourceEnum.RBI,
        file_name="rbi_kyc_v2.pdf",
        file_path="RBI/rbi_kyc_v2.pdf",
        checksum="active-checksum" + "a" * 49,
        status=StatusEnum.UPLOADED,
        version="v2",
        is_superseded=False,
    )
    db_session.add(doc_active)
    await db_session.commit()

    # Now register the superseded document referencing the active one
    doc_superseded = Document(
        title="RBI KYC Superseded Circular",
        source=SourceEnum.RBI,
        file_name="rbi_kyc_v1.pdf",
        file_path="RBI/rbi_kyc_v1.pdf",
        checksum="superseded-checksum" + "b" * 45,
        status=StatusEnum.UPLOADED,
        version="v1",
        is_superseded=True,
        superseded_by_id=doc_active.id,
    )
    db_session.add(doc_superseded)
    await db_session.commit()

    # Register 3 dummy documents to increase corpus size (N) for BM25 IDF positivity
    for i in range(3):
        dummy_doc = Document(
            title=f"Dummy Doc {i}",
            source=SourceEnum.SEBI,
            file_name=f"dummy_{i}.pdf",
            file_path=f"SEBI/dummy_{i}.pdf",
            checksum=f"dummy-checksum-{i}" + "c" * 45,
            status=StatusEnum.UPLOADED,
            version="v1",
            is_superseded=False,
        )
        db_session.add(dummy_doc)
        await db_session.commit()

        dummy_chunks = [
            {
                "content": "completely unrelated random text content for dummy indexing",
                "section": "Sec 1",
                "subsection": "",
                "page_number": 1,
                "token_count": 10,
            }
        ]
        await chunk_service.register_chunks_bulk(dummy_doc.id, dummy_chunks)

    # Register chunks for both documents
    chunks_active = [
        {
            "content": "This is active passage regulatory guidelines",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]
    chunks_superseded = [
        {
            "content": "This is superseded passage regulatory guidelines",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]

    registered_active = await chunk_service.register_chunks_bulk(doc_active.id, chunks_active)
    registered_superseded = await chunk_service.register_chunks_bulk(doc_superseded.id, chunks_superseded)

    # 3. Create embeddings
    from app.repositories.embedding import ChunkEmbeddingRepository
    repo = ChunkEmbeddingRepository(db_session)

    await repo.save_embedding(
        chunk_id=registered_active[0].id,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="supersession-3d-model",
        embedding_dimension=3,
    )
    await repo.save_embedding(
        chunk_id=registered_superseded[0].id,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="supersession-3d-model",
        embedding_dimension=3,
    )
    await db_session.commit()

    # 4. Test dense retrieval with active_only=True
    dense_resp = await retrieval_service.retrieve(
        query="regulatory guidelines",
        top_k=5,
        active_only=True,
    )
    dense_results = dense_resp.get("results", [])
    assert len(dense_results) == 1
    assert dense_results[0]["chunk_id"] == str(registered_active[0].id)

    # Test dense retrieval with active_only=False
    dense_resp_all = await retrieval_service.retrieve(
        query="regulatory guidelines",
        top_k=5,
        active_only=False,
    )
    dense_results_all = dense_resp_all.get("results", [])

    # 5. Build BM25 index and test BM25 retrieval
    bm25_manager = BM25IndexManager(db_session)
    await bm25_manager.build_index("test_supersession_bm25")

    bm25_service = BM25RetrieverService(db_session)

    # Test BM25 retrieval with active_only=True
    bm25_results = await bm25_service.retrieve(
        query="regulatory guidelines",
        top_k=5,
        score_threshold=0.1,
        active_only=True,
    )
    assert len(bm25_results) == 1
    assert bm25_results[0]["chunk_id"] == str(registered_active[0].id)

    # Test BM25 retrieval with active_only=False
    bm25_results_all = await bm25_service.retrieve(
        query="regulatory guidelines",
        top_k=5,
        score_threshold=0.1,
        active_only=False,
    )
    assert len(bm25_results_all) == 2
