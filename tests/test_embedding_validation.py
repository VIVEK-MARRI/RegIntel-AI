import pytest
import uuid
from app.models.document import Document, SourceEnum, StatusEnum
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.validation.embedding import EmbeddingQualityValidator
from app.repositories.embedding import ChunkEmbeddingRepository


@pytest.mark.asyncio
async def test_embedding_validation_rules(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    repo = ChunkEmbeddingRepository(db_session)
    validator = EmbeddingQualityValidator(db_session)

    # 2. Register mock document & chunks
    checksum_unique = uuid.uuid4().hex + uuid.uuid4().hex
    doc = Document(
        title="Validation Test Doc",
        source=SourceEnum.RBI,
        file_name="validation_test.pdf",
        file_path="RBI/validation_test.pdf",
        checksum=checksum_unique,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 2",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 3",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 4",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 5",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    chunk_ids = [c.id for c in registered_chunks]

    # 3. Create normal embeddings for Chunk 0 and Chunk 1 (dimension = 3)
    # Norm of [1.0, 0.0, 0.0] is 1.0. Norm of [0.6, 0.8, 0.0] is 1.0.
    # Average norm should be 1.0.
    await repo.save_embedding(
        chunk_id=chunk_ids[0],
        embedding=[1.0, 0.0, 0.0],
        embedding_model="test-model",
        embedding_dimension=3,
    )
    await repo.save_embedding(
        chunk_id=chunk_ids[1],
        embedding=[0.6, 0.8, 0.0],
        embedding_model="test-model",
        embedding_dimension=3,
    )

    # 4. Create an embedding with Dimension Mismatch for Chunk 2 (len = 4 instead of 3)
    await repo.save_embedding(
        chunk_id=chunk_ids[2],
        embedding=[1.0, 0.0, 0.0, 0.0],
        embedding_model="test-model",
        embedding_dimension=3,  # Mismatch: actual len is 4
    )

    # 5. Create a Zero Vector embedding for Chunk 3
    await repo.save_embedding(
        chunk_id=chunk_ids[3],
        embedding=[0.0, 0.0, 0.0],
        embedding_model="test-model",
        embedding_dimension=3,
    )

    # 6. Create a Corrupted Vector (NaN) embedding for Chunk 4
    await repo.save_embedding(
        chunk_id=chunk_ids[4],
        embedding=[1.0, float("nan"), 0.0],
        embedding_model="test-model",
        embedding_dimension=3,
    )

    await db_session.commit()

    # 7. Mock db_session.execute to simulate an orphan embedding record
    from unittest.mock import MagicMock, patch

    original_execute = db_session.execute
    mock_orphan_id = uuid.uuid4()
    mock_chunk_id = uuid.uuid4()

    async def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        # Detect orphan outer join check query by scanning table names and IS NULL check
        if (
            "document_chunks" in stmt_str
            and "chunk_embeddings" in stmt_str
            and "null" in stmt_str
        ):
            mock_res = MagicMock()
            mock_res.all.return_value = [(mock_orphan_id, mock_chunk_id)]
            return mock_res
        return await original_execute(stmt, *args, **kwargs)

    with patch.object(db_session, "execute", side_effect=mock_execute):
        # Run validation
        report = await validator.validate_embeddings(
            expected_dim=3, embedding_model="test-model", document_id=doc.id
        )

    # Assertions
    assert report.valid is False
    assert report.metrics.total_chunks == 5
    assert report.metrics.total_embeddings == 5

    # Get issues
    issues_by_rule = {}
    for issue in report.issues:
        issues_by_rule[issue.rule_name] = issue

    assert "dimension_mismatch" in issues_by_rule
    assert "zero_vector" in issues_by_rule
    assert "corrupted_vector" in issues_by_rule
    assert "orphan_embedding" in issues_by_rule

    # Check dimensions mismatch message
    assert "Vector dimension mismatch" in issues_by_rule["dimension_mismatch"].message
    assert issues_by_rule["orphan_embedding"].embedding_id == str(mock_orphan_id)

    # Clean up DB for test isolation
    await doc_service.repository.delete(doc)
    await db_session.commit()


@pytest.mark.asyncio
async def test_embedding_validation_missing_and_duplicates(db_session):
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    repo = ChunkEmbeddingRepository(db_session)
    validator = EmbeddingQualityValidator(db_session)

    checksum_unique = uuid.uuid4().hex + uuid.uuid4().hex
    doc = Document(
        title="Validation Missing/Duplicates Doc",
        source=SourceEnum.RBI,
        file_name="validation_miss_dup.pdf",
        file_path="RBI/validation_miss_dup.pdf",
        checksum=checksum_unique,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    chunks_data = [
        {
            "content": "Passage 1",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 2",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "Passage 3",
            "section": "Sec 1",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    chunk_ids = [c.id for c in registered_chunks]

    # Save identical vectors for Chunk 0 and Chunk 1 to test duplicate check
    await repo.save_embedding(
        chunk_id=chunk_ids[0],
        embedding=[0.8, 0.6, 0.0],
        embedding_model="test-miss-dup-model",
        embedding_dimension=3,
    )
    await repo.save_embedding(
        chunk_id=chunk_ids[1],
        embedding=[0.8, 0.6, 0.0],
        embedding_model="test-miss-dup-model",
        embedding_dimension=3,
    )

    # We do NOT save an embedding for Chunk 2 to test missing check
    await db_session.commit()

    # Run validation
    report = await validator.validate_embeddings(
        expected_dim=3, embedding_model="test-miss-dup-model", document_id=doc.id
    )

    # Assertions
    assert report.valid is False  # due to missing embedding (severity ERROR)
    assert report.metrics.total_chunks == 3
    assert report.metrics.total_embeddings == 2

    # Coverage should be 2/3 * 100 = 66.66%
    assert pytest.approx(report.metrics.embedding_coverage, abs=1e-2) == 66.67

    # Duplicate embedding count should be 1 (we have 2 records sharing 1 vector, so 1 extra duplicate)
    assert report.metrics.duplicate_embedding_count == 1

    issues_by_rule = {}
    for issue in report.issues:
        issues_by_rule[issue.rule_name] = issue

    assert "missing_embedding" in issues_by_rule
    assert "duplicate_embedding" in issues_by_rule

    assert issues_by_rule["missing_embedding"].severity == "ERROR"
    assert issues_by_rule["duplicate_embedding"].severity == "WARNING"

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
