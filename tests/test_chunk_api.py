import pytest
import uuid
from httpx import AsyncClient
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk


@pytest.mark.asyncio
async def test_chunk_management_apis(client: AsyncClient, db_session):
    # 1. Setup mock data
    # Register documents
    doc1 = Document(
        title="RBI Circular on Credit Risk",
        source=SourceEnum.RBI,
        file_name="rbi_credit.pdf",
        file_path="RBI/rbi_credit.pdf",
        checksum="x" * 64,
        status=StatusEnum.UPLOADED,
    )
    doc2 = Document(
        title="SEBI Disclosure Rules",
        source=SourceEnum.SEBI,
        file_name="sebi_disclosure.pdf",
        file_path="SEBI/sebi_disclosure.pdf",
        checksum="y" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add_all([doc1, doc2])
    await db_session.commit()

    # Create chunks for Doc 1
    c1_id = uuid.uuid4()
    c1 = DocumentChunk(
        id=c1_id,
        document_id=doc1.id,
        page_number=2,
        section="Chapter I - Governance",
        subsection="Role of Board",
        content="Board of directors is responsible for overseeing risk management frameworks.",
        token_count=520,
        metadata_json={"page": 2, "section": "Chapter I - Governance"},
    )
    c2_id = uuid.uuid4()
    c2 = DocumentChunk(
        id=c2_id,
        document_id=doc1.id,
        page_number=4,
        section="Chapter II - Core Controls",
        subsection="Verification Controls",
        content="Verification controls must be established to monitor transactions.",
        token_count=600,
        metadata_json={"page": 4, "section": "Chapter II - Core Controls"},
    )

    # Create chunk for Doc 2
    c3_id = uuid.uuid4()
    c3 = DocumentChunk(
        id=c3_id,
        document_id=doc2.id,
        page_number=1,
        section="Section 3 - Disclosure Guidelines",
        subsection="Annual Reports",
        content="Annual reports must outline security disclosures.",
        token_count=480,
        metadata_json={"page": 1, "section": "Section 3 - Disclosure Guidelines"},
    )

    db_session.add_all([c1, c2, c3])
    await db_session.commit()

    # ----------------------------------------------------
    # TEST 1: GET /api/v1/chunks (List across all docs)
    # ----------------------------------------------------
    response = await client.get("/api/v1/chunks")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 3

    # Sorting default: page_number asc (c3 (1) -> c1 (2) -> c2 (4))
    assert res_data[0]["id"] == str(c3_id)
    assert res_data[1]["id"] == str(c1_id)
    assert res_data[2]["id"] == str(c2_id)

    # ----------------------------------------------------
    # TEST 2: GET /api/v1/chunks (Pagination skip/limit)
    # ----------------------------------------------------
    response = await client.get("/api/v1/chunks?skip=1&limit=1")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == str(c1_id)

    # ----------------------------------------------------
    # TEST 3: GET /api/v1/chunks (Filter by document_id)
    # ----------------------------------------------------
    response = await client.get(f"/api/v1/chunks?document_id={doc2.id}")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == str(c3_id)

    # ----------------------------------------------------
    # TEST 4: GET /api/v1/chunks (Sorting token_count desc)
    # ----------------------------------------------------
    # c2 (600) -> c1 (520) -> c3 (480)
    response = await client.get("/api/v1/chunks?sort_by=token_count&sort_order=desc")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 3
    assert res_data[0]["id"] == str(c2_id)
    assert res_data[1]["id"] == str(c1_id)
    assert res_data[2]["id"] == str(c3_id)

    # ----------------------------------------------------
    # TEST 5: GET /api/v1/chunks (Search by section & subsection partial match)
    # ----------------------------------------------------
    # Search section: "core"
    response = await client.get("/api/v1/chunks?section=core")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == str(c2_id)

    # Search subsection: "board"
    response = await client.get("/api/v1/chunks?subsection=board")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == str(c1_id)

    # ----------------------------------------------------
    # TEST 6: GET /api/v1/chunks/{id} (Get single chunk)
    # ----------------------------------------------------
    response = await client.get(f"/api/v1/chunks/{c1_id}")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["id"] == str(c1_id)
    assert res_data["document_id"] == str(doc1.id)
    assert res_data["content"] == c1.content
    assert res_data["token_count"] == 520

    # Non-existent ID -> 404 CHUNK_NOT_FOUND
    fake_id = uuid.uuid4()
    response = await client.get(f"/api/v1/chunks/{fake_id}")
    assert response.status_code == 404
    assert response.json()["error_code"] == "CHUNK_NOT_FOUND"

    # ----------------------------------------------------
    # TEST 7: GET /api/v1/documents/{id}/chunks (Get doc chunks)
    # ----------------------------------------------------
    response = await client.get(f"/api/v1/documents/{doc1.id}/chunks")
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 2

    # Page sorting check
    assert res_data[0]["id"] == str(c1_id)
    assert res_data[1]["id"] == str(c2_id)

    # Filtering/Searching on document chunks endpoint
    response = await client.get(
        f"/api/v1/documents/{doc1.id}/chunks?section=governance"
    )
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["id"] == str(c1_id)

    # Non-existent doc ID -> 404 DOCUMENT_NOT_FOUND
    fake_doc_id = uuid.uuid4()
    response = await client.get(f"/api/v1/documents/{fake_doc_id}/chunks")
    assert response.status_code == 404
    assert response.json()["error_code"] == "DOCUMENT_NOT_FOUND"

    # Cleanup to maintain test database isolation
    await db_session.delete(doc1)
    await db_session.delete(doc2)
    await db_session.commit()
