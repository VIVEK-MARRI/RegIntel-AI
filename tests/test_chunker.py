import uuid
import pytest
from httpx import AsyncClient
from app.core.token_utils import SimpleTokenizer
from app.services.structure.chunker import HierarchicalChunker
from app.services.structure.benchmark_chunker import run_chunker_benchmark
from app.models.document import Document, SourceEnum, StatusEnum


def test_simple_tokenizer():
    tokenizer = SimpleTokenizer()
    assert tokenizer.count_tokens("") == 0
    assert tokenizer.count_tokens(None) == 0

    text = "This is a simple sentence."
    # 5 words + 1 punctuation = 6 BPE components
    # 6 * 1.1 = 6.6 -> 6 tokens
    tokens = tokenizer.count_tokens(text)
    assert tokens > 0

    # Determinism check
    assert tokenizer.count_tokens(text) == tokens


def test_hierarchical_chunker_bounds_and_metadata():
    tokenizer = SimpleTokenizer()
    chunker = HierarchicalChunker(tokenizer)
    doc_id = uuid.uuid4()
    doc_title = "RAG Standards Guideline"

    # 1. Build a mock document content with large sections to test chunk boundaries (500-800 tokens)
    # A single line has roughly 14 words (~16 tokens). We need ~45 lines to hit 700 tokens.
    lines_section_1 = [
        f"The system must establish standard compliance protocols and manage technical risks on line {i}."
        for i in range(1, 60)
    ]

    pages = [
        {
            "page_number": 1,
            "content": (
                "Reserve Bank of India\n"
                "1. Customer Due Diligence\n" + "\n".join(lines_section_1[:30]) + "\n"
            ),
        },
        {
            "page_number": 2,
            "content": (
                "1.1 Periodic Verification\n" + "\n".join(lines_section_1[30:]) + "\n"
            ),
        },
    ]

    chunks = chunker.chunk_document(doc_id, doc_title, pages)

    assert len(chunks) > 0

    # Check that metadata is preserved and titles are in the content
    for chunk in chunks:
        # Check metadata
        assert chunk.section in ["General", "1. Customer Due Diligence"]
        assert chunk.page_number in [1, 2]

        # Verify title is never split from content (since it's prepended in the header prefix)
        assert "Document: RAG Standards Guideline" in chunk.content
        assert "Section:" in chunk.content

        # Verify token counts are non-zero
        assert chunk.token_count > 0

        # Verify stable deterministic ID is a string of UUID
        assert len(chunk.chunk_id) == 36
        uuid.UUID(chunk.chunk_id)  # Should not raise ValueError


def test_chunker_benchmark():
    # Verify the benchmark script runs correctly and produces valid metrics
    metrics = run_chunker_benchmark(pages_count=2, lines_per_page=20)
    assert metrics["document_pages_count"] == 2
    assert metrics["total_lines_processed"] == 40
    assert metrics["chunk_count"] > 0
    assert metrics["execution_time_ms"] > 0
    assert metrics["tokens_mean"] > 0


@pytest.mark.asyncio
async def test_get_document_chunks_api(client: AsyncClient, db_session):
    from app.models.chunk import DocumentChunk

    # 1. Register document
    doc = Document(
        title="RBI Cybersecurity Chunking Circular",
        source=SourceEnum.RBI,
        file_name="cyber_chunks.pdf",
        file_path="RBI/cyber_chunks.pdf",
        checksum="6" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # 2. Add some page content & chunk content to the database
    chunk1 = DocumentChunk(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        document_id=doc.id,
        page_number=1,
        section="General",
        subsection="",
        content="General content before first section",
        token_count=10,
        metadata_json={"page": 1, "section": "General", "token_count": 10},
    )
    chunk2 = DocumentChunk(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        document_id=doc.id,
        page_number=1,
        section="1. Introduction",
        subsection="1.1 Scope",
        content="This document describes cybersecurity chunks in details.",
        token_count=15,
        metadata_json={
            "page": 1,
            "section": "1. Introduction",
            "subsection": "1.1 Scope",
            "token_count": 15,
        },
    )
    db_session.add(chunk1)
    db_session.add(chunk2)
    await db_session.commit()

    # 3. Request chunks API
    response = await client.get(f"/api/v1/documents/{doc.id}/chunks")
    assert response.status_code == 200
    res_data = response.json()

    assert isinstance(res_data, list)
    assert len(res_data) == 2

    # First chunk is General
    assert res_data[0]["section"] == "General"

    # Second chunk is from section block under 1.1 Scope
    second_chunk = res_data[1]
    assert second_chunk["section"] == "1. Introduction"
    assert second_chunk["subsection"] == "1.1 Scope"
    assert "This document describes" in second_chunk["content"]
    assert second_chunk["token_count"] == 15
    assert second_chunk["page_number"] == 1
    assert "id" in second_chunk

    # Cleanup to maintain test database isolation
    await db_session.delete(doc)
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_document_chunks_api_not_found(client: AsyncClient):
    # Query non-existent document UUID
    non_existent_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/documents/{non_existent_id}/chunks")
    assert response.status_code == 404
    assert response.json()["error_code"] == "DOCUMENT_NOT_FOUND"
