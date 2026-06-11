import uuid
import logging
from typing import List, Sequence, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import DocumentChunk
from app.repositories.chunk import ChunkRepository
from app.services.document import DocumentService
from app.core.exceptions import ChunkNotFoundError

logger = logging.getLogger(__name__)

class ChunkRegistryService:
    """Service class managing business workflows for DocumentChunks."""

    def __init__(self, db_session: AsyncSession, document_service: DocumentService):
        self.repository = ChunkRepository(db_session)
        self.document_service = document_service
        self.db_session = db_session

    async def register_chunk(self, chunk_data: Dict[str, Any]) -> DocumentChunk:
        """Registers a single document chunk."""
        # Verify parent document exists
        doc_id = uuid.UUID(str(chunk_data["document_id"]))
        await self.document_service.get_document_by_id(doc_id)

        chunk = DocumentChunk(
            id=uuid.UUID(str(chunk_data["chunk_id"])) if "chunk_id" in chunk_data else uuid.uuid4(),
            document_id=doc_id,
            page_number=chunk_data["page"] if "page" in chunk_data else chunk_data.get("page_number", 1),
            section=chunk_data["section"],
            subsection=chunk_data.get("subsection", ""),
            content=chunk_data["content"],
            token_count=chunk_data["token_count"],
            metadata_json=chunk_data.get("metadata", {})
        )

        created = await self.repository.create_chunk(chunk)
        await self.db_session.commit()
        logger.info(f"Registered single chunk {created.id} for document {doc_id}")
        return created

    @staticmethod
    def _serialize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
        """Convert non-JSON-serializable types to strings for JSONB storage."""
        serialized = {}
        for k, v in meta.items():
            if isinstance(v, uuid.UUID):
                serialized[k] = str(v)
            elif isinstance(v, dict):
                serialized[k] = ChunkRegistryService._serialize_metadata(v)
            elif isinstance(v, list):
                serialized[k] = [
                    ChunkRegistryService._serialize_metadata(item) if isinstance(item, dict) else str(item) if isinstance(item, uuid.UUID) else item
                    for item in v
                ]
            else:
                serialized[k] = v
        return serialized

    async def register_chunks_bulk(
        self, 
        document_id: uuid.UUID, 
        chunks_data: List[Dict[str, Any]]
    ) -> List[DocumentChunk]:
        """Registers multiple document chunks in bulk within a single transaction block."""
        # Verify parent document exists
        doc = await self.document_service.get_document_by_id(document_id)
        logger.info(f"Bulk registering {len(chunks_data)} chunks for document {doc.id}")

        chunk_objs = []
        for c in chunks_data:
            # Handle both raw chunks and enriched chunks layout
            is_enriched = "metadata" in c and isinstance(c["metadata"], dict)
            meta = c["metadata"] if is_enriched else {}
            
            page_num = meta.get("page", c.get("page_number", 1))
            sec = meta.get("section", c.get("section", ""))
            subsec = meta.get("subsection", c.get("subsection", ""))
            toks = meta.get("token_count", c.get("token_count", 0))

            chunk_objs.append(
                DocumentChunk(
                    id=uuid.UUID(str(c["chunk_id"])) if "chunk_id" in c else uuid.uuid4(),
                    document_id=doc.id,
                    page_number=page_num,
                    section=sec,
                    subsection=subsec,
                    content=c["content"],
                    token_count=toks,
                    metadata_json=ChunkRegistryService._serialize_metadata(meta)
                )
            )

        await self.repository.create_chunks_bulk(chunk_objs)
        await self.db_session.commit()
        logger.info(f"Successfully bulk registered {len(chunks_data)} chunks for document {doc.id}")
        return chunk_objs

    async def get_chunk_by_id(self, chunk_id: uuid.UUID) -> DocumentChunk:
        """Retrieves a chunk by its ID or raises ChunkNotFoundError."""
        chunk = await self.repository.get_chunk(chunk_id)
        if not chunk:
            raise ChunkNotFoundError(str(chunk_id))
        return chunk

    async def list_chunks(
        self,
        document_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        subsection: Optional[str] = None,
        sort_by: str = "page_number",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[DocumentChunk]:
        """Retrieves a list of chunks across documents with optional filtering/searching/sorting."""
        # If document_id is provided, verify it exists (raising DocumentNotFoundError if missing)
        if document_id:
            await self.document_service.get_document_by_id(document_id)
        return await self.repository.list_chunks(
            document_id=document_id,
            section=section,
            subsection=subsection,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit
        )

    async def get_document_chunks(
        self, 
        document_id: uuid.UUID, 
        section: Optional[str] = None,
        subsection: Optional[str] = None,
        sort_by: str = "page_number",
        sort_order: str = "asc",
        skip: int = 0, 
        limit: int = 100
    ) -> Sequence[DocumentChunk]:
        """Retrieves a paginated list of chunks for a document, after verifying document exists."""
        # Verify document exists (raises DocumentNotFoundError if missing)
        await self.document_service.get_document_by_id(document_id)
        return await self.repository.get_document_chunks(
            document_id=document_id,
            section=section,
            subsection=subsection,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit
        )
