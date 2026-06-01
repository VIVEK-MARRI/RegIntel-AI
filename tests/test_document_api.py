import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "project": "RegIntel AI Document Registry"}

@pytest.mark.asyncio
async def test_register_and_get_document(client: AsyncClient):
    doc_data = {
        "title": "RBI Master Circular - Credit Cards",
        "source": "RBI",
        "file_name": "rbi_credit_cards.pdf",
        "file_path": "/var/data/rbi_credit_cards.pdf",
        "document_type": "Circular",
        "publication_date": "2026-05-15",
        "checksum": "a" * 64,  # 64-char hex
        "page_count": 25
    }
    
    # 1. Create document
    response = await client.post("/api/v1/documents", json=doc_data)
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["title"] == doc_data["title"]
    assert res_data["status"] == "UPLOADED"
    assert "id" in res_data
    assert "uploaded_at" in res_data
    
    doc_id = res_data["id"]
    
    # 2. Duplicate registration (same checksum)
    duplicate_response = await client.post("/api/v1/documents", json=doc_data)
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error_code"] == "DUPLICATE_DOCUMENT"
    
    # 3. Retrieve document by ID
    get_response = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == doc_id
    
    # 4. Retrieve invalid UUID
    invalid_uuid = "00000000-0000-0000-0000-000000000000"
    get_invalid = await client.get(f"/api/v1/documents/{invalid_uuid}")
    assert get_invalid.status_code == 404
    assert get_invalid.json()["error_code"] == "DOCUMENT_NOT_FOUND"

@pytest.mark.asyncio
async def test_list_and_filter_documents(client: AsyncClient):
    docs = [
        {
            "title": "RBI Circular 1",
            "source": "RBI",
            "file_name": "rbi1.pdf",
            "file_path": "/path/rbi1.pdf",
            "checksum": "1" * 64,
            "page_count": 5
        },
        {
            "title": "SEBI Regulation 1",
            "source": "SEBI",
            "file_name": "sebi1.pdf",
            "file_path": "/path/sebi1.pdf",
            "checksum": "2" * 64,
            "page_count": 10
        },
        {
            "title": "RBI Notification 2",
            "source": "RBI",
            "file_name": "rbi2.pdf",
            "file_path": "/path/rbi2.pdf",
            "checksum": "3" * 64,
            "page_count": 15
        }
    ]
    
    # Register documents
    for doc in docs:
        res = await client.post("/api/v1/documents", json=doc)
        assert res.status_code == 201

    # List all
    list_res = await client.get("/api/v1/documents")
    assert list_res.status_code == 200
    all_docs = list_res.json()
    assert len(all_docs) >= 3
    
    # Filter by source: SEBI
    sebi_res = await client.get("/api/v1/documents?source=SEBI")
    assert sebi_res.status_code == 200
    sebi_docs = sebi_res.json()
    assert len(sebi_docs) == 1
    assert sebi_docs[0]["title"] == "SEBI Regulation 1"
    
    # Filter by source: RBI
    rbi_res = await client.get("/api/v1/documents?source=RBI")
    assert rbi_res.status_code == 200
    rbi_docs = rbi_res.json()
    assert len(rbi_docs) >= 2

@pytest.mark.asyncio
async def test_document_lifecycle_transitions(client: AsyncClient):
    doc_data = {
        "title": "Lifecycle Test Document",
        "source": "RBI",
        "file_name": "lifecycle.pdf",
        "file_path": "/path/lifecycle.pdf",
        "checksum": "b" * 64,
        "page_count": 3
    }
    
    # Register document -> starts at UPLOADED
    res = await client.post("/api/v1/documents", json=doc_data)
    assert res.status_code == 201
    doc_id = res.json()["id"]
    
    # 1. Invalid transition: UPLOADED -> PARSED (returns 400 Bad Request)
    bad_transition1 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "PARSED"})
    assert bad_transition1.status_code == 400
    assert bad_transition1.json()["error_code"] == "INVALID_STATE_TRANSITION"
    
    # 2. Valid transition: UPLOADED -> PARSING (returns 200 OK)
    ok_transition1 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "PARSING"})
    assert ok_transition1.status_code == 200
    assert ok_transition1.json()["status"] == "PARSING"
    
    # 3. Invalid transition: PARSING -> UPLOADED (returns 400 Bad Request)
    bad_transition2 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "UPLOADED"})
    assert bad_transition2.status_code == 400
    
    # 4. Valid transition: PARSING -> FAILED (returns 200 OK)
    ok_transition2 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "FAILED"})
    assert ok_transition2.status_code == 200
    assert ok_transition2.json()["status"] == "FAILED"
    
    # 5. Valid transition: FAILED -> PARSING (returns 200 OK for retry)
    ok_transition3 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "PARSING"})
    assert ok_transition3.status_code == 200
    
    # 6. Valid transition: PARSING -> PARSED (returns 200 OK)
    ok_transition4 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "PARSED"})
    assert ok_transition4.status_code == 200
    assert ok_transition4.json()["status"] == "PARSED"
    
    # 7. Invalid transition: PARSED -> PARSING (returns 400 Bad Request since PARSED is terminal)
    bad_transition3 = await client.patch(f"/api/v1/documents/{doc_id}/status", json={"status": "PARSING"})
    assert bad_transition3.status_code == 400

@pytest.mark.asyncio
async def test_update_metadata(client: AsyncClient):
    doc_data = {
        "title": "Old Title",
        "source": "RBI",
        "file_name": "meta.pdf",
        "file_path": "/path/meta.pdf",
        "checksum": "c" * 64,
        "page_count": 1
    }
    
    res = await client.post("/api/v1/documents", json=doc_data)
    doc_id = res.json()["id"]
    
    # Update title and page count
    update_data = {
        "title": "New Title",
        "page_count": 99
    }
    
    update_res = await client.patch(f"/api/v1/documents/{doc_id}", json=update_data)
    assert update_res.status_code == 200
    updated_doc = update_res.json()
    assert updated_doc["title"] == "New Title"
    assert updated_doc["page_count"] == 99
    
    # Ensure other fields did not change
    assert updated_doc["file_name"] == "meta.pdf"

@pytest.mark.asyncio
async def test_upload_document_api(client: AsyncClient):
    import io
    import hashlib
    from unittest.mock import patch, AsyncMock
    
    file_content = b"PDF API upload content SEBI regulation"
    file_bytes = io.BytesIO(file_content)
    
    # 1. Successful upload
    response = await client.post(
        "/api/v1/documents/upload",
        data={
            "source": "SEBI",
            "title": "SEBI Insider Trading Regulation",
            "document_type": "Regulation",
            "publication_date": "2026-05-20",
            "page_count": 42
        },
        files={
            "file": ("sebi_insider.pdf", file_bytes, "application/pdf")
        }
    )
    
    assert response.status_code == 201
    res_data = response.json()
    assert "document_id" in res_data
    assert res_data["status"] == "uploaded"
    
    doc_id = res_data["document_id"]
    
    # Verify we can fetch the document from DB registry
    get_res = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "SEBI Insider Trading Regulation"

    # 2. Try duplicate upload (same content)
    file_bytes_dup = io.BytesIO(file_content)
    dup_response = await client.post(
        "/api/v1/documents/upload",
        data={
            "source": "SEBI",
            "title": "Duplicate Upload",
            "document_type": "Regulation"
        },
        files={
            "file": ("sebi_insider_dup.pdf", file_bytes_dup, "application/pdf")
        }
    )
    assert dup_response.status_code == 409
    assert dup_response.json()["error_code"] == "DUPLICATE_DOCUMENT"

    # 3. Invalid file type (Only PDF allowed)
    bad_file = io.BytesIO(b"some text data")
    type_response = await client.post(
        "/api/v1/documents/upload",
        data={
            "source": "SEBI",
            "title": "Text File Upload"
        },
        files={
            "file": ("sebi_text.txt", bad_file, "text/plain")
        }
    )
    assert type_response.status_code == 400
    assert "Only PDF files are allowed" in type_response.json()["detail"]

    # 4. File size limit exceeded (> 50 MB)
    large_file = io.BytesIO(b"dummy pdf content")
    with patch("tempfile.SpooledTemporaryFile.tell", return_value=51 * 1024 * 1024):
        size_response = await client.post(
            "/api/v1/documents/upload",
            data={
                "source": "SEBI",
                "title": "Large File Upload"
            },
            files={
                "file": ("large_doc.pdf", large_file, "application/pdf")
            }
        )
    assert size_response.status_code == 400
    assert "File size exceeds the maximum limit of 50 MB" in size_response.json()["detail"]
