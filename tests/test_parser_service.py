import tempfile
import pytest
from pathlib import Path
import fitz
from app.services.parser_service import ParserService, PDFParsingError
from app.services.document import DocumentService
from app.models.document import Document, SourceEnum, StatusEnum

@pytest.fixture
def create_test_pdf():
    def _create(dest_path: Path, pages_content: list[str]):
        with fitz.open() as doc:
            for content in pages_content:
                page = doc.new_page()
                if content:
                    page.insert_text((50, 50), content)
            doc.save(str(dest_path))
    return _create

@pytest.mark.asyncio
async def test_parser_service_success(db_session, create_test_pdf):
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1. Setup DocumentService and ParserService
        doc_service = DocumentService(db_session)
        parser_service = ParserService(doc_service, temp_dir)
        
        # 2. Create actual PDF document on disk
        relative_path = "RBI/rbi_circular.pdf"
        full_path = Path(temp_dir) / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        create_test_pdf(full_path, ["First Page Content", "Second Page Content", ""])
        
        # 3. Create document in Database
        doc = Document(
            title="RBI Circular for Parsing",
            source=SourceEnum.RBI,
            file_name="rbi_circular.pdf",
            file_path=relative_path,
            checksum="d" * 64,
            status=StatusEnum.UPLOADED
        )
        db_session.add(doc)
        await db_session.commit()
        
        # 4. Progress hook setup
        progress_calls = []
        def progress_hook(curr, total):
            progress_calls.append((curr, total))
            
        # 5. Parse
        parsed_pages = await parser_service.parse_document(doc.id, progress_hook=progress_hook)
        
        # 6. Verify parsed outputs
        assert len(parsed_pages) == 3
        assert parsed_pages[0] == {"page_number": 1, "content": "First Page Content"}
        assert parsed_pages[1] == {"page_number": 2, "content": "Second Page Content"}
        assert parsed_pages[2] == {"page_number": 3, "content": ""}
        
        # Verify progress hooks
        assert progress_calls == [(1, 3), (2, 3), (3, 3)]
        
        # 7. Check database status and page count updates
        await db_session.refresh(doc)
        assert doc.status == StatusEnum.PARSED
        assert doc.page_count == 3

@pytest.mark.asyncio
async def test_parser_service_file_not_found(db_session):
    with tempfile.TemporaryDirectory() as temp_dir:
        doc_service = DocumentService(db_session)
        parser_service = ParserService(doc_service, temp_dir)
        
        # Create database document entry but do not write file to disk
        doc = Document(
            title="Missing File Doc",
            source=SourceEnum.RBI,
            file_name="missing.pdf",
            file_path="RBI/missing.pdf",
            checksum="e" * 64,
            status=StatusEnum.UPLOADED
        )
        db_session.add(doc)
        await db_session.commit()
        
        with pytest.raises(PDFParsingError, match="File not found on disk"):
            await parser_service.parse_document(doc.id)
            
        await db_session.refresh(doc)
        assert doc.status == StatusEnum.FAILED

@pytest.mark.asyncio
async def test_parser_service_corrupted_pdf(db_session):
    with tempfile.TemporaryDirectory() as temp_dir:
        doc_service = DocumentService(db_session)
        parser_service = ParserService(doc_service, temp_dir)
        
        relative_path = "SEBI/corrupted.pdf"
        full_path = Path(temp_dir) / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write corrupted garbage bytes to file
        full_path.write_bytes(b"INVALID_PDF_GARBAGE_DATA")
        
        doc = Document(
            title="Corrupted Doc",
            source=SourceEnum.SEBI,
            file_name="corrupted.pdf",
            file_path=relative_path,
            checksum="f" * 64,
            status=StatusEnum.UPLOADED
        )
        db_session.add(doc)
        await db_session.commit()
        
        with pytest.raises(PDFParsingError, match="Corrupted or invalid PDF file"):
            await parser_service.parse_document(doc.id)
            
        await db_session.refresh(doc)
        assert doc.status == StatusEnum.FAILED
