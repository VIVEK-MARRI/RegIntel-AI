import uuid
from typing import Optional, Sequence
from fastapi import APIRouter, Depends, Query, status
from app.api.dependencies import get_document_service
from app.models.document import SourceEnum, StatusEnum
from app.schemas.document import (
    DocumentCreate, 
    DocumentResponse, 
    DocumentStatusUpdate, 
    DocumentUpdate
)
from app.services.document import DocumentService

router = APIRouter()

@router.post(
    "", 
    response_model=DocumentResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Register a new document",
    description="Registers a new document in the registry, ensuring duplicate check using SHA-256 checksum."
)
async def register_document(
    doc_in: DocumentCreate,
    service: DocumentService = Depends(get_document_service)
) -> DocumentResponse:
    return await service.register_document(doc_in)

@router.get(
    "/{document_id}", 
    response_model=DocumentResponse,
    summary="Get document details",
    description="Fetches metadata details for a registered document by its UUID."
)
async def get_document(
    document_id: uuid.UUID,
    service: DocumentService = Depends(get_document_service)
) -> DocumentResponse:
    return await service.get_document_by_id(document_id)

@router.get(
    "", 
    response_model=Sequence[DocumentResponse],
    summary="List and filter documents",
    description="Lists documents from the registry, filtered by document source regulator or status."
)
async def list_documents(
    source: Optional[SourceEnum] = Query(None, description="Filter by document source (RBI/SEBI)"),
    status: Optional[StatusEnum] = Query(None, description="Filter by lifecycle status"),
    skip: int = Query(0, ge=0, description="Number of documents to skip"),
    limit: int = Query(100, ge=1, le=100, description="Max number of documents to return"),
    service: DocumentService = Depends(get_document_service)
) -> Sequence[DocumentResponse]:
    return await service.list_documents(source=source, status=status, skip=skip, limit=limit)

@router.patch(
    "/{document_id}/status", 
    response_model=DocumentResponse,
    summary="Update document status",
    description="Updates the parsing lifecycle status of a document, enforcing permitted state transitions."
)
async def update_document_status(
    document_id: uuid.UUID,
    status_update: DocumentStatusUpdate,
    service: DocumentService = Depends(get_document_service)
) -> DocumentResponse:
    return await service.update_document_status(document_id, status_update.status)

@router.patch(
    "/{document_id}", 
    response_model=DocumentResponse,
    summary="Update document metadata",
    description="Updates general metadata details of a document like title, document_type, page_count."
)
async def update_document_metadata(
    document_id: uuid.UUID,
    metadata_update: DocumentUpdate,
    service: DocumentService = Depends(get_document_service)
) -> DocumentResponse:
    return await service.update_document_metadata(document_id, metadata_update)
