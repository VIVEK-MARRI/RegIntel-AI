import io
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from app.services.storage_provider import LocalStorageProvider
from app.services.storage_service import StorageService
from app.core.exceptions import DuplicateDocumentError

@pytest.mark.asyncio
async def test_calculate_checksum():
    # Setup test file content
    content = b"RegIntel AI file content test"
    file_stream = io.BytesIO(content)
    
    service = StorageService(provider=AsyncMock(), db_session=AsyncMock())
    checksum = await service.calculate_checksum(file_stream)
    
    # Calculated hash
    import hashlib
    expected = hashlib.sha256(content).hexdigest()
    assert checksum == expected

@pytest.mark.asyncio
async def test_local_storage_provider_lifecycle():
    with tempfile.TemporaryDirectory() as temp_dir:
        provider = LocalStorageProvider(temp_dir)
        
        # 1. Save file
        content = b"Hello Local Storage"
        file_stream = io.BytesIO(content)
        dest = "RBI/circular_1.pdf"
        
        await provider.save_file(file_stream, dest)
        
        # 2. Check exists
        assert await provider.file_exists(dest) is True
        
        # Verify written file contents
        full_path = Path(temp_dir) / dest
        assert full_path.exists()
        assert full_path.read_bytes() == content
        
        # 3. Delete file
        await provider.delete_file(dest)
        assert await provider.file_exists(dest) is False
        assert not full_path.exists()

@pytest.mark.asyncio
async def test_local_storage_provider_path_traversal_protection():
    with tempfile.TemporaryDirectory() as temp_dir:
        provider = LocalStorageProvider(temp_dir)
        
        bad_dest = "../traversal.txt"
        file_stream = io.BytesIO(b"data")
        
        with pytest.raises(ValueError, match="Path traversal attempt detected"):
            await provider.save_file(file_stream, bad_dest)
            
        with pytest.raises(ValueError, match="Path traversal attempt detected"):
            await provider.delete_file(bad_dest)
            
        with pytest.raises(ValueError, match="Path traversal attempt detected"):
            await provider.file_exists(bad_dest)

@pytest.mark.asyncio
async def test_storage_service_save_and_duplicate_prevention(db_session):
    with tempfile.TemporaryDirectory() as temp_dir:
        provider = LocalStorageProvider(temp_dir)
        storage_service = StorageService(provider, db_session)
        
        # Upload a mock file
        content = b"PDF regulatory intelligence RBI doc 1"
        file_stream = io.BytesIO(content)
        filename = "rbi_doc.pdf"
        
        # 1. Successful save
        path, checksum = await storage_service.save_file(file_stream, filename, "RBI")
        assert path.startswith("RBI/")
        assert path.endswith(".pdf")
        assert len(checksum) == 64
        
        # Verify file exists on disk
        assert await storage_service.file_exists(path) is True
        
        # 2. Add document manually to db_session to trigger checksum duplication
        from app.models.document import Document, SourceEnum, StatusEnum
        doc = Document(
            title="Registered Doc",
            source=SourceEnum.RBI,
            file_name="rbi_doc.pdf",
            file_path=path,
            checksum=checksum,
            status=StatusEnum.UPLOADED
        )
        db_session.add(doc)
        await db_session.commit()
        
        # 3. Try to save duplicate file (same content/checksum)
        duplicate_stream = io.BytesIO(content)
        with pytest.raises(DuplicateDocumentError):
            await storage_service.save_file(duplicate_stream, "another_name.pdf", "RBI")
            
        # 4. Try invalid source
        with pytest.raises(ValueError, match="Invalid source regulatory body"):
            await storage_service.save_file(io.BytesIO(b"other"), "doc.pdf", "INVALID")
