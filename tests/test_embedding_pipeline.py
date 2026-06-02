import pytest
import uuid
from sqlalchemy import select
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding.pipeline import EmbeddingPipeline

class MockEmbeddingProvider:
    def __init__(self, dimension=384, fail_until=0):
        self.dimension = dimension
        self.fail_until = fail_until
        self.calls = 0

    def encode_batch(self, texts):
        self.calls += 1
        if self.calls <= self.fail_until:
            raise RuntimeError(f"Mock transient error (call {self.calls})")
        return [[0.5] * self.dimension for _ in texts]

    def get_dimension(self) -> int:
        return self.dimension

    def get_model_name(self) -> str:
        return "mock-model"

    def health_check(self) -> bool:
        return True

@pytest.mark.asyncio
async def test_embedding_pipeline_success(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    
    # Use mock provider that succeeds on the first call
    mock_provider = MockEmbeddingProvider(dimension=384, fail_until=0)
    pipeline = EmbeddingPipeline(db_session, chunk_service, mock_provider)

    # 2. Register document and chunks
    doc = Document(
        title="RBI Risk Framework",
        source=SourceEnum.RBI,
        file_name="rbi_risk.pdf",
        file_path="RBI/rbi_risk.pdf",
        checksum="p" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {"content": "Content passage 1", "section": "Sec 1", "subsection": "", "page_number": 1, "token_count": 10},
        {"content": "Content passage 2", "section": "Sec 2", "subsection": "", "page_number": 1, "token_count": 12},
        {"content": "Content passage 3", "section": "Sec 3", "subsection": "", "page_number": 2, "token_count": 15}
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # 3. Run Pipeline (using small batch_size to test multiple batches)
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id,
        batch_size=2,
        max_retries=2
    )

    # 4. Assert Metrics
    assert metrics["total_chunks"] == 3
    assert metrics["processed_chunks"] == 3
    assert metrics["failed_chunks"] == 0
    assert metrics["duration_ms"] > 0
    assert mock_provider.calls == 2  # 2 batches: batch 1 (size 2), batch 2 (size 1)

    # 5. Verify database records are COMPLETED and contain embeddings
    stmt = select(ChunkEmbedding).join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id).where(DocumentChunk.document_id == doc.id)
    res = await db_session.execute(stmt)
    embeddings = res.scalars().all()
    assert len(embeddings) == 3
    
    for emb in embeddings:
        assert emb.status == EmbeddingStatusEnum.COMPLETED
        assert len(emb.embedding) == 384
        assert emb.embedding[0] == 0.5
        assert emb.error_message is None

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()

@pytest.mark.asyncio
async def test_embedding_pipeline_transient_retry(db_session):
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    
    # Mock provider that fails on the first call, but succeeds on retry
    mock_provider = MockEmbeddingProvider(dimension=384, fail_until=1)
    pipeline = EmbeddingPipeline(db_session, chunk_service, mock_provider)

    doc = Document(
        title="SEBI Transient Test",
        source=SourceEnum.SEBI,
        file_name="sebi_transient.pdf",
        file_path="SEBI/sebi_transient.pdf",
        checksum="q" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {"content": "Content passage 1", "section": "Sec 1", "subsection": "", "page_number": 1, "token_count": 10}
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # Run pipeline with backoff_factor=0.01 to keep tests fast
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id,
        batch_size=1,
        max_retries=3,
        backoff_factor=0.01
    )

    # Verify recovery
    assert metrics["total_chunks"] == 1
    assert metrics["processed_chunks"] == 1
    assert metrics["failed_chunks"] == 0
    assert mock_provider.calls == 2  # first call failed, second (retry) succeeded

    stmt = select(ChunkEmbedding).join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id).where(DocumentChunk.document_id == doc.id)
    res = await db_session.execute(stmt)
    embeddings = res.scalars().all()
    assert len(embeddings) == 1
    assert embeddings[0].status == EmbeddingStatusEnum.COMPLETED

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()

@pytest.mark.asyncio
async def test_embedding_pipeline_permanent_failure(db_session):
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    
    # Mock provider that always fails
    mock_provider = MockEmbeddingProvider(dimension=384, fail_until=10)
    pipeline = EmbeddingPipeline(db_session, chunk_service, mock_provider)

    doc = Document(
        title="SEBI Failure Test",
        source=SourceEnum.SEBI,
        file_name="sebi_failure.pdf",
        file_path="SEBI/sebi_failure.pdf",
        checksum="r" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {"content": "Content passage 1", "section": "Sec 1", "subsection": "", "page_number": 1, "token_count": 10}
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # Run pipeline with max_retries=2
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id,
        batch_size=1,
        max_retries=2,
        backoff_factor=0.01
    )

    assert metrics["total_chunks"] == 1
    assert metrics["processed_chunks"] == 0
    assert metrics["failed_chunks"] == 1
    assert mock_provider.calls == 2  # first call failed, second (retry) failed, then fails permanently

    # Verify status is FAILED and error message is saved
    stmt = select(ChunkEmbedding).join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id).where(DocumentChunk.document_id == doc.id)
    res = await db_session.execute(stmt)
    embeddings = res.scalars().all()
    assert len(embeddings) == 1
    assert embeddings[0].status == EmbeddingStatusEnum.FAILED
    assert "Mock transient error" in embeddings[0].error_message

    # Test status checking repo method
    status_counts = await pipeline.embedding_repo.get_document_embeddings_status(doc.id)
    assert status_counts[EmbeddingStatusEnum.FAILED.value] == 1
    assert status_counts[EmbeddingStatusEnum.COMPLETED.value] == 0

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
