import uuid
import logging
from typing import List
from app.schemas.structure import StructureElement
from app.services.structure.base import BaseStructureExtractor
from app.services.page import PageService

logger = logging.getLogger(__name__)

class StructureService:
    """Service orchestrating document structure extraction workflows."""

    def __init__(self, page_service: PageService, extractor: BaseStructureExtractor):
        self.page_service = page_service
        self.extractor = extractor

    async def get_document_structure(self, document_id: uuid.UUID) -> List[StructureElement]:
        """Fetches page contents for a document and parses its hierarchical outline structure."""
        logger.info(f"Extracting document structure for: {document_id}")
        
        # 1. Fetch pages of the document (raises DocumentNotFoundError if document is missing)
        pages = await self.page_service.get_document_pages(document_id, limit=2000)
        
        # 2. Format inputs for extractor
        pages_data = [
            {
                "page_number": p.page_number,
                "content": p.content
            }
            for p in pages
        ]
        
        # 3. Extract structure
        return self.extractor.extract_structure(pages_data)
