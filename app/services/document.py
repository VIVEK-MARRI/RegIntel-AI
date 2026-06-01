import uuid
import logging
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, SourceEnum, StatusEnum
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.repositories.document import DocumentRepository
from app.core.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    InvalidStateTransitionError
)

logger = logging.getLogger(__name__)

class DocumentService:
    def __init__(self, db_session: AsyncSession):
        self.repository = DocumentRepository(db_session)
        self.db_session = db_session

    async def register_document(self, doc_create: DocumentCreate) -> Document:
        """Registers a new document in the system after checking for duplicates."""
        logger.info(f"Registering document with checksum: {doc_create.checksum}")
        
        # Check for duplication
        existing = await self.repository.get_document_by_checksum(doc_create.checksum)
        if existing:
            raise DuplicateDocumentError(doc_create.checksum)

        # Create ORM instance
        doc = Document(
            title=doc_create.title,
            source=doc_create.source,
            file_name=doc_create.file_name,
            file_path=doc_create.file_path,
            document_type=doc_create.document_type,
            publication_date=doc_create.publication_date,
            status=StatusEnum.UPLOADED,
            checksum=doc_create.checksum,
            page_count=doc_create.page_count
        )

        created_doc = await self.repository.create_document(doc)
        await self.db_session.commit()
        logger.info(f"Registered new document: {created_doc.id}")
        return created_doc

    async def get_document_by_id(self, document_id: uuid.UUID) -> Document:
        """Retrieves a document by its primary key or raises DocumentNotFoundError."""
        doc = await self.repository.get_document(document_id)
        if not doc:
            raise DocumentNotFoundError(str(document_id))
        return doc

    async def list_documents(
        self,
        source: Optional[SourceEnum] = None,
        status: Optional[StatusEnum] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[Document]:
        """Lists documents using repository layer filters."""
        return await self.repository.list_documents(source, status, skip, limit)

    async def update_document_status(self, document_id: uuid.UUID, new_status: StatusEnum) -> Document:
        """Updates document status after validating state transition rules."""
        logger.info(f"Updating status for document {document_id} to {new_status}")
        
        doc = await self.get_document_by_id(document_id)
        current_status = doc.status

        # Validate transition
        if not self._is_valid_transition(current_status, new_status):
            raise InvalidStateTransitionError(current_status.value, new_status.value)

        # Execute update
        updated_doc = await self.repository.update_status(document_id, new_status)
        await self.db_session.commit()
        
        # Refresh session to get updated_at value
        await self.db_session.refresh(updated_doc)
        logger.info(f"Document {document_id} status updated successfully to {new_status}")
        return updated_doc

    async def update_document_metadata(self, document_id: uuid.UUID, doc_update: DocumentUpdate) -> Document:
        """Updates document metadata fields (title, document_type, publication_date, page_count)."""
        logger.info(f"Updating metadata for document {document_id}")
        
        doc = await self.get_document_by_id(document_id)
        
        update_data = doc_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(doc, key, value)
            
        await self.db_session.commit()
        await self.db_session.refresh(doc)
        logger.info(f"Document {document_id} metadata updated successfully.")
        return doc

    def _is_valid_transition(self, current: StatusEnum, target: StatusEnum) -> bool:
        """Enforces lifecycle transition rules.
        
        Rules:
        - UPLOADED -> PARSING, FAILED
        - PARSING -> PARSED, FAILED
        - FAILED -> PARSING (allow retrying parsing)
        """
        # Identity transition is always valid (e.g. UPLOADED to UPLOADED)
        if current == target:
            return True
            
        transitions = {
            StatusEnum.UPLOADED: {StatusEnum.PARSING, StatusEnum.FAILED},
            StatusEnum.PARSING: {StatusEnum.PARSED, StatusEnum.FAILED},
            StatusEnum.PARSED: set(),  # terminal state
            StatusEnum.FAILED: {StatusEnum.PARSING}  # retry parsing
        }
        
        allowed = transitions.get(current, set())
        return target in allowed
