"""Validation: Phase 1 (Upload) → Phase 2 (Parsing) → Phase 3 (Chunking) → Phase 4 (Embedding)"""

import pytest
import fitz
import uuid
import io
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, StatusEnum
from app.models.chunk import EmbeddingStatusEnum
from app.services.embedding.pipeline import EmbeddingPipeline
from app.services.embedding.index_manager import VectorIndexManager


def create_test_pdf_bytes(
    content_lines: list[str], filename: str = "test.pdf"
) -> bytes:
    """Create a valid PDF with given content lines as separate pages."""
    doc = fitz.open()
    for content in content_lines:
        page = doc.new_page()
        if content:
            page.insert_text((50, 700), content)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_phase1_upload_validation(client: AsyncClient, db_session: AsyncSession):
    """Phase 1: Upload Pipeline Validation"""

    pdf_bytes = create_test_pdf_bytes(["Page 1 content for RBI circular."])
    file_bytes = io.BytesIO(pdf_bytes)

    # 1. Successful PDF upload
    response = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "Validation Test Document"},
        files={"file": ("test_circular.pdf", file_bytes, "application/pdf")},
    )
    assert response.status_code == 201, f"Upload failed: {response.text}"
    res = response.json()
    assert "document_id" in res
    assert res["status"] == "processing"
    doc_id = res["document_id"]

    # 2. Duplicate upload rejection
    dup_bytes = io.BytesIO(pdf_bytes)
    dup_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "Duplicate"},
        files={"file": ("dup.pdf", dup_bytes, "application/pdf")},
    )
    assert dup_res.status_code == 409, f"Duplicate detection failed: {dup_res.text}"
    assert dup_res.json()["error_code"] == "DUPLICATE_DOCUMENT"

    # 3. Unsupported file type rejection
    bad_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "Bad file"},
        files={"file": ("test.exe", io.BytesIO(b"text"), "application/x-msdownload")},
    )
    assert bad_res.status_code == 400
    assert "Unsupported file type" in bad_res.json()["detail"]

    # 4. Oversized file rejection
    import unittest.mock

    with unittest.mock.patch("app.api.v1.documents.MAX_FILE_SIZE", 1 * 1024 * 1024):
        size_res = await client.post(
            "/api/v1/documents/upload",
            data={"source": "RBI", "title": "Big file"},
            files={
                "file": (
                    "big.pdf",
                    io.BytesIO(b"x" * (2 * 1024 * 1024)),
                    "application/pdf",
                )
            },
        )
        assert (
            size_res.status_code == 400
        ), f"Expected 400, got {size_res.status_code}: {size_res.text}"
        assert "1 MB" in size_res.json()["detail"]

    # 5. Document retrievable
    get_res = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Validation Test Document"
    assert get_res.json()["source"] == "RBI"
    assert get_res.json()["status"] == "PARSED"


@pytest.mark.asyncio
async def test_phase2_parsing_validation(client: AsyncClient, db_session: AsyncSession):
    """Phase 2: Parsing Validation — verify page extraction, persistence, ordering"""
    from app.repositories.page import PageRepository

    # Create a PDF with 5 pages of known content (unique checksum vs phase1)
    pages_content = [
        "RBI Master Circular on KYC Compliance",
        "Section 1. Introduction\nThis circular is issued under Section 35A of the Banking Regulation Act.",
        "Section 2. Applicability\nThese guidelines apply to all Scheduled Commercial Banks.",
        "Section 3. Customer Identification\nBanks must verify identity using Aadhaar, Passport, or Voter ID.",
        "References\nRBI Act 1934 and subsequent amendments.",
    ]
    pdf_bytes = create_test_pdf_bytes(pages_content)
    file_bytes = io.BytesIO(pdf_bytes)

    # Upload
    upload_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "KYC Norms Circular", "page_count": 5},
        files={"file": ("kyc_circular.pdf", file_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = uuid.UUID(upload_res.json()["document_id"])

    # Pipeline already parsed via upload endpoint — verify results from DB
    from app.repositories.page import PageRepository

    pages_repo = PageRepository(db_session)
    db_pages = await pages_repo.get_pages_by_document(doc_id)
    parsed = [{"page_number": p.page_number, "content": p.content} for p in db_pages]

    # Verify parsed pages count
    assert len(parsed) == 5, f"Expected 5 pages, got {len(parsed)}"

    # Verify page ordering
    for i, page in enumerate(parsed):
        assert page["page_number"] == i + 1, f"Page number mismatch at index {i}"

    # Verify content matches
    assert parsed[0]["content"] == pages_content[0].strip(), "Page 1 content mismatch"
    assert parsed[1]["content"] == pages_content[1].strip(), "Page 2 content mismatch"

    # Verify document status = PARSED
    doc = await db_session.get(Document, doc_id)
    assert doc is not None
    assert doc.status == StatusEnum.PARSED, f"Expected PARSED, got {doc.status}"
    assert doc.page_count == 5, f"Expected page_count=5, got {doc.page_count}"

    # API page endpoint
    api_pages_res = await client.get(f"/api/v1/documents/{doc_id}/pages")
    assert api_pages_res.status_code == 200
    api_pages = api_pages_res.json()
    assert len(api_pages) == 5
    assert api_pages[0]["page_number"] == 1

    # API structure endpoint
    struct_res = await client.get(f"/api/v1/documents/{doc_id}/structure")
    assert struct_res.status_code == 200


@pytest.mark.asyncio
async def test_phase3_chunking_validation(
    client: AsyncClient, db_session: AsyncSession
):
    """Phase 3: Chunking Validation — verify chunk generation, metadata, page mapping"""
    pages_content = [
        "RBI Master Circular on AML Norms",
        "Section 1. Introduction\nAnti-Money Laundering guidelines issued under PMLA 2002.",
        "Section 1.1. Applicability\nAll financial institutions must comply with KYC norms.",
        "Section 2. Reporting\nSuspicious Transaction Reports must be filed within 7 days.",
        "Section 2.1. Penalties\nNon-compliance attracts penalties under Section 13 of PMLA.",
    ]
    pdf_bytes = create_test_pdf_bytes(pages_content)
    file_bytes = io.BytesIO(pdf_bytes)

    upload_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "AML Norms Circular"},
        files={"file": ("aml.pdf", file_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = uuid.UUID(upload_res.json()["document_id"])

    # Pipeline already parsed via upload endpoint — proceed to chunking
    from app.services.structure.chunker import (
        HierarchicalChunkerService,
        HierarchicalChunker,
    )
    from app.core.token_utils import SimpleTokenizer
    from app.services.structure.enricher import MetadataEnricher, MetadataValidator
    from app.services.document import DocumentService
    from app.services.page import PageService

    doc_service = DocumentService(db_session)
    page_service = PageService(db_session, doc_service)
    chunker = HierarchicalChunker(tokenizer=SimpleTokenizer())
    enricher = MetadataEnricher(MetadataValidator())
    chunker_service = HierarchicalChunkerService(
        document_service=doc_service,
        page_service=page_service,
        chunker=chunker,
        enricher=enricher,
    )

    chunks = await chunker_service.chunk_document_by_id(doc_id)

    # Verify chunks > 0
    assert len(chunks) > 0, "Expected at least 1 chunk, got 0"

    # Verify no empty chunks
    for i, c in enumerate(chunks):
        # Enriched chunks have nested structure: {"chunk_id", "content", "metadata": {...}}
        content = c["content"]
        meta = c.get("metadata", {})
        assert len(content.strip()) > 0, f"Empty chunk at index {i}"
        # page number is in metadata.page for enriched chunks
        assert meta.get("page", 0) > 0, f"Invalid page_number in chunk {i}"

    # Pipeline already persisted chunks — verify them from DB
    from app.repositories.chunk import ChunkRepository

    chunk_repo = ChunkRepository(db_session)
    db_chunks = await chunk_repo.get_document_chunks(doc_id)
    assert len(db_chunks) == len(
        chunks
    ), f"DB chunks {len(db_chunks)} != returned {len(chunks)}"
    for dbc in db_chunks:
        assert dbc.page_number > 0
        assert dbc.document_id == doc_id

    # Verify API chunk endpoint
    api_chunks_res = await client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert api_chunks_res.status_code == 200
    api_chunks = api_chunks_res.json()
    assert len(api_chunks) > 0

    # Verify chunk IDs are stable (deterministic)
    chunk_ids = [c["chunk_id"] for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk IDs"

    # Test small/medium document sizing
    medium_content = [f"Page {i} content with Section {i} details" for i in range(20)]
    medium_pdf = create_test_pdf_bytes(medium_content)
    medium_bytes = io.BytesIO(medium_pdf)
    med_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "SEBI", "title": "Medium Document"},
        files={"file": ("medium.pdf", medium_bytes, "application/pdf")},
    )
    assert med_res.status_code == 201
    med_id = uuid.UUID(med_res.json()["document_id"])

    med_chunks = await chunker_service.chunk_document_by_id(med_id)
    assert len(med_chunks) > 0, "Medium document produced 0 chunks"

    db_med_chunks = await chunk_repo.get_document_chunks(med_id)
    assert len(db_med_chunks) == len(med_chunks)


@pytest.mark.asyncio
async def test_chunker_service_accepts_string_document_id(
    client: AsyncClient, db_session: AsyncSession
):
    pages_content = [
        "RBI Master Circular on AML Norms",
        "Section 1. Introduction\nAnti-Money Laundering guidelines issued under PMLA 2002.",
    ]
    pdf_bytes = create_test_pdf_bytes(pages_content)
    file_bytes = io.BytesIO(pdf_bytes)
    upload_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "RBI", "title": "AML Norms Circular"},
        files={"file": ("aml.pdf", file_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = uuid.UUID(upload_res.json()["document_id"])

    from app.services.structure.chunker import (
        HierarchicalChunkerService,
        HierarchicalChunker,
    )
    from app.core.token_utils import SimpleTokenizer
    from app.services.structure.enricher import MetadataEnricher, MetadataValidator
    from app.services.document import DocumentService
    from app.services.page import PageService

    doc_service = DocumentService(db_session)
    page_service = PageService(db_session, doc_service)
    chunker = HierarchicalChunker(tokenizer=SimpleTokenizer())
    enricher = MetadataEnricher(MetadataValidator())
    chunker_service = HierarchicalChunkerService(
        document_service=doc_service,
        page_service=page_service,
        chunker=chunker,
        enricher=enricher,
    )

    chunks = await chunker_service.chunk_document_by_id(str(doc_id))
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_phase4_embedding_validation(
    client: AsyncClient, db_session: AsyncSession
):
    """Phase 4: Embedding Validation — verify embeddings generated and stored"""
    from app.repositories.embedding import ChunkEmbeddingRepository

    pages_content = [
        "SEBI Master Circular on Insider Trading",
        "Section 1. Prohibition\nNo insider shall trade in securities when in possession of unpublished price sensitive information.",
        "Section 2. Disclosure\nPromoters must disclose shareholding changes within 2 days.",
    ]
    pdf_bytes = create_test_pdf_bytes(pages_content)
    file_bytes = io.BytesIO(pdf_bytes)

    upload_res = await client.post(
        "/api/v1/documents/upload",
        data={"source": "SEBI", "title": "Insider Trading Regulations"},
        files={"file": ("insider.pdf", file_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = uuid.UUID(upload_res.json()["document_id"])

    # Pipeline already parsed + chunked via upload endpoint
    # Get existing chunks from DB
    from app.repositories.chunk import ChunkRepository
    from app.services.chunk_registry import ChunkRegistryService
    from app.services.document import DocumentService

    chunk_repo = ChunkRepository(db_session)
    db_chunks = await chunk_repo.get_document_chunks(doc_id)
    assert len(db_chunks) > 0, "No chunks found in DB"
    chunk_ids_in_db = {c.id for c in db_chunks}

    doc_service = DocumentService(db_session)
    chunk_registry = ChunkRegistryService(db_session, doc_service)

    # Embed using mock provider
    from typing import List

    class MockEmbeddingProvider:
        def get_dimension(self):
            return 384

        def get_model_name(self):
            return "mock-model"

        def encode_text(self, text):
            return [0.0] * 384

        def encode_query(self, query):
            return [0.0] * 384

        def encode_batch(self, texts: List[str]):
            return [[0.0] * 384 for _ in texts]

        def health_check(self):
            return True

    pipeline = EmbeddingPipeline(
        db_session=db_session,
        chunk_service=chunk_registry,
        embedding_provider=MockEmbeddingProvider(),
    )

    result = await pipeline.process_document_embeddings(doc_id)

    assert result["total_chunks"] > 0, f"No chunks to embed: {result}"
    assert result["processed_chunks"] > 0, f"No embeddings created: {result}"
    assert result["failed_chunks"] == 0, f"Failed embeddings: {result}"

    # Verify embeddings stored in DB
    embed_repo = ChunkEmbeddingRepository(db_session)
    all_embeddings = await embed_repo.get_embeddings_by_document(doc_id)
    assert len(all_embeddings) > 0, "No embeddings found in DB"

    # Verify each embedding references a valid chunk
    for emb in all_embeddings:
        assert (
            emb.chunk_id in chunk_ids_in_db
        ), f"Orphan embedding for chunk {emb.chunk_id}"
        assert (
            emb.status == EmbeddingStatusEnum.COMPLETED
        ), f"Embedding {emb.id} status = {emb.status}"
        assert emb.embedding is not None, f"Null embedding vector for {emb.id}"
        assert len(emb.embedding) > 0, f"Empty embedding vector for {emb.id}"

    # Verify no orphan chunks (chunks without embeddings)
    from app.repositories.chunk import ChunkRepository as _ChunkRepository

    chunk_repo = _ChunkRepository(db_session)
    db_chunks = await chunk_repo.get_document_chunks(doc_id)
    embedded_chunk_ids = {e.chunk_id for e in all_embeddings}
    for c in db_chunks:
        assert c.id in embedded_chunk_ids, f"Chunk {c.id} has no embedding"

    # Index health check — SQLite doesn't have pg_index
    from sqlalchemy.exc import OperationalError

    index_mgr = VectorIndexManager(db_session)
    try:
        health = await index_mgr.index_health()
        assert health is not None
    except OperationalError as exc:
        if "no such table: pg_index" in str(exc):
            pass
        else:
            raise
