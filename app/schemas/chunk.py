from typing import List
from uuid import UUID
from pydantic import BaseModel, ConfigDict

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
