from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.models.document import SourceEnum, StatusEnum


class DocumentBase(BaseModel):
    title: str = Field(..., max_length=255, description="The title of the document")
    source: SourceEnum = Field(
        ..., description="The document source (RBI, SEBI, IRDAI, USER_UPLOAD)"
    )
    file_name: str = Field(..., max_length=255, description="The name of the file")
    file_path: str = Field(
        ..., max_length=512, description="The logical or physical path to the file"
    )
    document_type: Optional[str] = Field(
        None,
        max_length=100,
        description="The category of the document (e.g. Circular, Policy, Report)",
    )
    publication_date: Optional[date] = Field(
        None, description="The date the document was published"
    )
    checksum: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 checksum of the file content for deduplication",
    )
    page_count: Optional[int] = Field(
        None, ge=0, description="Number of pages in the document"
    )


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    document_type: Optional[str] = Field(None, max_length=100)
    publication_date: Optional[date] = None
    page_count: Optional[int] = Field(None, ge=0)


class DocumentStatusUpdate(BaseModel):
    status: StatusEnum = Field(..., description="The new status of the document")


class DocumentResponse(DocumentBase):
    id: UUID
    status: StatusEnum
    uploaded_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDetailResponse(DocumentResponse):
    """Extended document detail with processing and indexing info."""

    chunk_count: int = 0
    page_count_actual: Optional[int] = 0
    embedding_count: int = 0
    indexed: bool = False
    processing_status: str = "pending"


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    status: str
    run_id: Optional[str] = None


class SortByEnum(str, Enum):
    uploaded_at = "uploaded_at"
    publication_date = "publication_date"
    title = "title"


class SortOrderEnum(str, Enum):
    asc = "asc"
    desc = "desc"


class PageResponse(BaseModel):
    id: UUID
    document_id: UUID
    page_number: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
