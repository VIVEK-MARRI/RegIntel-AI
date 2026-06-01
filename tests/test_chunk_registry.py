import pytest
import uuid
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.core.exceptions import ChunkNotFoundError, register_exception_handlers

@pytest.mark.asyncio
async def test_chunk_registry_lifecycle(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)

    # 2. Register document
    doc = Document(
        title="SEBI Issue of Capital and Disclosure Requirements",
        source=SourceEnum.SEBI,
        file_name="sebi_icdr.pdf",
        file_path="SEBI/sebi_icdr.pdf",
        checksum="h" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()

    # 3. Store a single document chunk
    chunk_id = uuid.uuid4()
    chunk_data = {
        "chunk_id": str(chunk_id),
        "document_id": str(doc.id),
        "page_number": 4,
        "section": "Chapter II - Rights Issue",
        "subsection": "Pricing",
        "content": "The pricing of rights issue shall be decided by the issuer.",
        "token_count": 120,
        "metadata": {"custom_tag": "test"}
    }

    chunk = await chunk_service.register_chunk(chunk_data)
    assert chunk.id == chunk_id
    assert chunk.document_id == doc.id
    assert chunk.page_number == 4
    assert chunk.section == "Chapter II - Rights Issue"
    assert chunk.subsection == "Pricing"
    assert chunk.content == "The pricing of rights issue shall be decided by the issuer."
    assert chunk.token_count == 120
    assert chunk.metadata_json == {"custom_tag": "test"}

    # 4. Retrieve chunk by ID
    retrieved_chunk = await chunk_service.get_chunk_by_id(chunk_id)
    assert retrieved_chunk.id == chunk_id
    assert retrieved_chunk.content == chunk.content

    # 5. Retrieve chunk by non-existent ID
    non_existent_id = uuid.uuid4()
    with pytest.raises(ChunkNotFoundError) as exc_info:
        await chunk_service.get_chunk_by_id(non_existent_id)
    assert str(non_existent_id) in str(exc_info.value)

    # 6. Bulk register chunks
    bulk_data = [
        # Enriched style (Milestone 9)
        {
            "chunk_id": str(uuid.uuid4()),
            "content": "Bulk chunk 1 content.",
            "metadata": {
                "page": 2,
                "section": "Sec A",
                "subsection": "Sub A1",
                "token_count": 50,
                "tag": "first"
            }
        },
        # Flat style (Milestone 8)
        {
            "chunk_id": str(uuid.uuid4()),
            "page_number": 3,
            "section": "Sec B",
            "subsection": "Sub B1",
            "content": "Bulk chunk 2 content.",
            "token_count": 80
        },
        # Extra chunk on page 2 to test sort order within the same page (by ID/secondary sort)
        {
            "chunk_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "content": "Bulk chunk 3 content.",
            "metadata": {
                "page": 2,
                "section": "Sec A",
                "subsection": "Sub A2",
                "token_count": 60
            }
        }
    ]

    bulk_chunks = await chunk_service.register_chunks_bulk(doc.id, bulk_data)
    assert len(bulk_chunks) == 3

    # 7. Get document chunks with pagination and page-based sorting
    # We registered 1 chunk on page 4 (from single register) and 3 chunks from bulk (page 2, page 3, page 2).
    # Expected ordering: Page 2 chunks first, then Page 3, then Page 4.
    all_chunks = await chunk_service.get_document_chunks(doc.id, skip=0, limit=10)
    assert len(all_chunks) == 4
    
    # Verify sorting order: page 2, page 2, page 3, page 4
    assert all_chunks[0].page_number == 2
    assert all_chunks[1].page_number == 2
    assert all_chunks[2].page_number == 3
    assert all_chunks[3].page_number == 4

    # Pagination test
    paginated_chunks = await chunk_service.get_document_chunks(doc.id, skip=1, limit=2)
    assert len(paginated_chunks) == 2
    assert paginated_chunks[0].id == all_chunks[1].id
    assert paginated_chunks[1].id == all_chunks[2].id

    # 8. Cascade delete test
    await doc_service.repository.delete(doc)
    await db_session.commit()

    # Verify all chunks are deleted
    stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    res = await db_session.execute(stmt)
    remaining_chunks = res.scalars().all()
    assert len(remaining_chunks) == 0


@pytest.mark.asyncio
async def test_chunk_not_found_exception_handler():
    # Test that ChunkNotFoundError results in a 404 response with error_code
    app_test = FastAPI()
    register_exception_handlers(app_test)

    @app_test.get("/test-chunk-not-found/{chunk_id}")
    async def trigger_not_found(chunk_id: str):
        raise ChunkNotFoundError(chunk_id)

    client = TestClient(app_test)
    response = client.get("/test-chunk-not-found/abc-123")
    assert response.status_code == 404
    json_data = response.json()
    assert json_data["error_code"] == "CHUNK_NOT_FOUND"
    assert "abc-123" in json_data["detail"]
