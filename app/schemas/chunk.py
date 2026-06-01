from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class ChunkResponse(BaseModel):
    chunk_id: str
    section: str
    subsection: str
    content: str
    token_count: int
    page_number: int

    model_config = ConfigDict(from_attributes=True)

class DocumentChunkingResponse(BaseModel):
    document_id: UUID
    chunks: List[ChunkResponse]

    model_config = ConfigDict(from_attributes=True)

class ChunkMetadata(BaseModel):
    document_id: UUID
    title: str
    source: str
    page: int
    section: str
    subsection: str
    publication_date: Optional[date] = None
    chunk_size: int
    token_count: int
    
    # Allow extra fields for dynamic metadata extensions
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
        from_attributes=True
    )

class EnrichedChunkResponse(BaseModel):
    chunk_id: str
    content: str
    metadata: ChunkMetadata

    model_config = ConfigDict(from_attributes=True)

class DocumentEnrichedChunkingResponse(BaseModel):
    document_id: UUID
    chunks: List[EnrichedChunkResponse]

    model_config = ConfigDict(from_attributes=True)

class ChunkSortByEnum(str, Enum):
    page_number = "page_number"
    token_count = "token_count"
    created_at = "created_at"

class StoredChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    page_number: int
    section: str
    subsection: str
    content: str
    token_count: int
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
