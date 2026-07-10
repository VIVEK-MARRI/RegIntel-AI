import pytest
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
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Content passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Content passage 2",
            "section": "Sec 2",
            "subsection": "",
            "page_number": 1,
            "token_count": 12,
        },
        {
            "content": "Content passage 3",
            "section": "Sec 3",
            "subsection": "",
            "page_number": 2,
            "token_count": 15,
        },
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # 3. Run Pipeline (using small batch_size to test multiple batches)
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id, batch_size=2, max_retries=2
    )

    # 4. Assert Metrics
    assert metrics["total_chunks"] == 3
    assert metrics["processed_chunks"] == 3
    assert metrics["failed_chunks"] == 0
    assert metrics["duration_ms"] > 0
    assert mock_provider.calls == 2  # 2 batches: batch 1 (size 2), batch 2 (size 1)

    # 5. Verify database records are COMPLETED and contain embeddings
    stmt = (
        select(ChunkEmbedding)
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(DocumentChunk.document_id == doc.id)
    )
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
async def test_embedding_pipeline_accepts_string_document_id(db_session):
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    mock_provider = MockEmbeddingProvider(dimension=384, fail_until=0)
    pipeline = EmbeddingPipeline(db_session, chunk_service, mock_provider)
    doc = Document(
        title="String ID Test",
        source=SourceEnum.RBI,
        file_name="test.pdf",
        file_path="RBI/test.pdf",
        checksum="q" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()
    chunks_data = [
        {
            "content": "Test content",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    metrics = await pipeline.process_document_embeddings(
        document_id=str(doc.id), batch_size=2, max_retries=2
    )
    assert metrics["total_chunks"] == 1
    assert metrics["processed_chunks"] == 1
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
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Content passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # Run pipeline with backoff_factor=0.01 to keep tests fast
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id, batch_size=1, max_retries=3, backoff_factor=0.01
    )

    # Verify recovery
    assert metrics["total_chunks"] == 1
    assert metrics["processed_chunks"] == 1
    assert metrics["failed_chunks"] == 0
    assert mock_provider.calls == 2  # first call failed, second (retry) succeeded

    stmt = (
        select(ChunkEmbedding)
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(DocumentChunk.document_id == doc.id)
    )
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
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Content passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # Run pipeline with max_retries=2
    metrics = await pipeline.process_document_embeddings(
        document_id=doc.id, batch_size=1, max_retries=2, backoff_factor=0.01
    )

    assert metrics["total_chunks"] == 1
    assert metrics["processed_chunks"] == 0
    assert metrics["failed_chunks"] == 1
    assert (
        mock_provider.calls == 2
    )  # first call failed, second (retry) failed, then fails permanently

    # Verify status is FAILED and error message is saved
    stmt = (
        select(ChunkEmbedding)
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(DocumentChunk.document_id == doc.id)
    )
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


@pytest.mark.asyncio
async def test_repository_save_and_retrieve_embedding(db_session):
    from app.repositories.embedding import ChunkEmbeddingRepository
    from app.services.document import DocumentService
    from app.services.chunk_registry import ChunkRegistryService
    from app.models.document import Document, SourceEnum, StatusEnum

    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    repo = ChunkEmbeddingRepository(db_session)

    doc = Document(
        title="Repo Test Doc",
        source=SourceEnum.RBI,
        file_name="repo_test.pdf",
        file_path="RBI/repo_test.pdf",
        checksum="x" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Content passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        }
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    chunk_id = registered_chunks[0].id

    # 1. Test save_embedding (single upsert)
    emb_record = await repo.save_embedding(
        chunk_id=chunk_id,
        embedding=[0.1, 0.2, 0.3],
        embedding_model="mock-model",
        embedding_dimension=3,
    )
    assert emb_record.status == EmbeddingStatusEnum.COMPLETED
    assert emb_record.embedding_model == "mock-model"
    assert emb_record.embedding_dimension == 3
    assert emb_record.embedding == [0.1, 0.2, 0.3]

    # 2. Test get_embedding
    retrieved = await repo.get_embedding(chunk_id, "mock-model")
    assert retrieved is not None
    assert retrieved.id == emb_record.id
    assert retrieved.embedding == [0.1, 0.2, 0.3]

    # 3. Test saving a different model's embedding for the same chunk (coexistence!)
    emb_record_2 = await repo.save_embedding(
        chunk_id=chunk_id,
        embedding=[0.9, 0.8, 0.7, 0.6],
        embedding_model="mock-model-large",
        embedding_dimension=4,
    )
    assert emb_record_2.id != emb_record.id
    assert emb_record_2.embedding_model == "mock-model-large"
    assert emb_record_2.embedding == [0.9, 0.8, 0.7, 0.6]

    # Verify both exist
    retrieved_1 = await repo.get_embedding(chunk_id, "mock-model")
    retrieved_2 = await repo.get_embedding(chunk_id, "mock-model-large")
    assert retrieved_1 is not None
    assert retrieved_2 is not None
    assert len(retrieved_1.embedding) == 3
    assert len(retrieved_2.embedding) == 4

    # 4. Test delete_embeddings for a specific model
    await repo.delete_embeddings(chunk_id, "mock-model")
    assert await repo.get_embedding(chunk_id, "mock-model") is None
    assert await repo.get_embedding(chunk_id, "mock-model-large") is not None

    # 5. Test delete_embeddings for all models
    await repo.delete_embeddings(chunk_id)
    assert await repo.get_embedding(chunk_id, "mock-model-large") is None

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()


@pytest.mark.asyncio
async def test_repository_save_embeddings_bulk(db_session):
    from app.repositories.embedding import ChunkEmbeddingRepository
    from app.services.document import DocumentService
    from app.services.chunk_registry import ChunkRegistryService
    from app.models.document import Document, SourceEnum, StatusEnum

    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    repo = ChunkEmbeddingRepository(db_session)

    doc = Document(
        title="Bulk Repo Test Doc",
        source=SourceEnum.RBI,
        file_name="bulk_repo_test.pdf",
        file_path="RBI/bulk_repo_test.pdf",
        checksum="y" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Content passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Content passage 2",
            "section": "Sec 2",
            "subsection": "",
            "page_number": 1,
            "token_count": 12,
        },
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    chunk_ids = [c.id for c in registered_chunks]

    # 1. Test save_embeddings_bulk
    bulk_data = [
        {
            "chunk_id": chunk_ids[0],
            "embedding": [0.1, 0.2],
            "embedding_model": "mock-model",
            "embedding_dimension": 2,
            "status": EmbeddingStatusEnum.COMPLETED,
        },
        {
            "chunk_id": chunk_ids[1],
            "embedding": [0.3, 0.4],
            "embedding_model": "mock-model",
            "embedding_dimension": 2,
            "status": EmbeddingStatusEnum.COMPLETED,
        },
    ]
    await repo.save_embeddings_bulk(bulk_data)
    db_session.expire_all()

    # Verify both are created
    emb_1 = await repo.get_embedding(chunk_ids[0], "mock-model")
    emb_2 = await repo.get_embedding(chunk_ids[1], "mock-model")
    assert emb_1 is not None
    assert emb_2 is not None
    assert emb_1.embedding == [0.1, 0.2]
    assert emb_2.embedding == [0.3, 0.4]

    # 2. Test bulk upsert/update (change embeddings)
    bulk_data_update = [
        {
            "chunk_id": chunk_ids[0],
            "embedding": [0.5, 0.6],
            "embedding_model": "mock-model",
            "embedding_dimension": 2,
            "status": EmbeddingStatusEnum.COMPLETED,
        }
    ]
    await repo.save_embeddings_bulk(bulk_data_update)
    db_session.expire_all()

    emb_1_updated = await repo.get_embedding(chunk_ids[0], "mock-model")
    assert emb_1_updated.embedding == [0.5, 0.6]

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
