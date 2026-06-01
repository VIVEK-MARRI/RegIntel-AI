import uuid
import logging
from typing import List, Dict, Any, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.page import DocumentPage
from app.repositories.page import PageRepository
from app.services.document import DocumentService

logger = logging.getLogger(__name__)

class PageService:
    """Service class managing business workflows for document pages."""
    
    def __init__(self, db_session: AsyncSession, document_service: DocumentService):
        self.repository = PageRepository(db_session)
        self.document_service = document_service
        self.db_session = db_session

    async def store_pages(self, document_id: uuid.UUID, pages_data: List[Dict[str, Any]]) -> List[DocumentPage]:
        """Bulk inserts page-level content for a document, after verifying document exists."""
        logger.info(f"Storing {len(pages_data)} pages for document: {document_id}")
        
        # Verify document exists (raises DocumentNotFoundError if missing)
        doc = await self.document_service.get_document_by_id(document_id)
        
        page_objs = []
        for p in pages_data:
            page_objs.append(
                DocumentPage(
                    document_id=doc.id,
                    page_number=p["page_number"],
                    content=p["content"]
                )
            )
            
        await self.repository.bulk_insert_pages(page_objs)
        await self.db_session.commit()
        logger.info(f"Successfully stored {len(pages_data)} pages for document: {document_id}")
        return page_objs

    async def get_document_pages(
        self, 
        document_id: uuid.UUID, 
        skip: int = 0, 
        limit: int = 100
    ) -> Sequence[DocumentPage]:
        """Retrieves paginated list of pages for a document, after verifying document exists."""
        # Verify document exists (raises DocumentNotFoundError if missing)
        await self.document_service.get_document_by_id(document_id)
        return await self.repository.get_pages_by_document(document_id, skip, limit)
