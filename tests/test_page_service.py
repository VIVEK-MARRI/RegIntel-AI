import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.page import DocumentPage
from app.services.document import DocumentService
from app.services.page import PageService


@pytest.mark.asyncio
async def test_page_service_lifecycle(db_session):
    # 1. Setup services
    doc_service = DocumentService(db_session)
    page_service = PageService(db_session, doc_service)

    # 2. Register document
    doc = Document(
        title="RBI Guidelines on Cybersecurity",
        source=SourceEnum.RBI,
        file_name="rbi_cyber.pdf",
        file_path="RBI/rbi_cyber.pdf",
        checksum="g" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # 3. Store document pages bulk
    pages_data = [
        {"page_number": 1, "content": "Introduction to cybersecurity guidelines."},
        {"page_number": 2, "content": "Core controls and governance structures."},
        {"page_number": 3, "content": "Incident reporting mechanisms."},
    ]

    stored = await page_service.store_pages(doc.id, pages_data)
    assert len(stored) == 3
    assert stored[0].page_number == 1
    assert stored[0].content == "Introduction to cybersecurity guidelines."

    # 4. Retrieve pages paginated
    # List all
    all_pages = await page_service.get_document_pages(doc.id)
    assert len(all_pages) == 3
    # Check sorting
    assert all_pages[0].page_number == 1
    assert all_pages[1].page_number == 2
    assert all_pages[2].page_number == 3

    # Pagination skip/limit
    paginated = await page_service.get_document_pages(doc.id, skip=1, limit=1)
    assert len(paginated) == 1
    assert paginated[0].page_number == 2
    assert paginated[0].content == "Core controls and governance structures."

    # 5. Composite unique constraint test (duplicate page_number)
    duplicate_pages = [
        {"page_number": 1, "content": "This is a duplicate page 1 content."}
    ]
    with pytest.raises(IntegrityError):
        # This should fail due to unique constraint uq_document_id_page_number
        await page_service.store_pages(doc.id, duplicate_pages)

    await db_session.rollback()  # Rollback transaction block after exception

    # 6. Cascading delete test
    # Delete parent document
    await doc_service.repository.delete(doc)
    await db_session.commit()

    # Assert pages are deleted automatically
    stmt = select(DocumentPage).where(DocumentPage.document_id == doc.id)
    res = await db_session.execute(stmt)
    pages = res.scalars().all()
    assert len(pages) == 0
