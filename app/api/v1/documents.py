import uuid
from typing import Optional, Sequence
from datetime import datetime, date
from fastapi import APIRouter, Depends, Query, status, UploadFile, File, Form, HTTPException
from app.api.dependencies import (
    get_document_service, 
    get_storage_service, 
    get_page_service, 
    get_structure_service
)
from app.models.document import SourceEnum, StatusEnum
from app.schemas.document import (
    DocumentCreate, 
    DocumentResponse, 
    DocumentStatusUpdate, 
    DocumentUpdate,
    DocumentUploadResponse,
    SortByEnum,
    SortOrderEnum,
    PageResponse
)
from app.schemas.structure import DocumentStructureResponse
from app.services.document import DocumentService
from app.services.storage_service import StorageService
from app.services.page import PageService
from app.services.structure.service import StructureService

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
    "/{document_id}/pages",
    response_model=Sequence[PageResponse],
    summary="Get document pages",
    description="Retrieves paginated text content pages for a specific document, sorted by page number ascending."
)
async def get_document_pages(
    document_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="Number of pages to skip"),
    limit: int = Query(100, ge=1, le=100, description="Max number of pages to return"),
    page_service: PageService = Depends(get_page_service)
) -> Sequence[PageResponse]:
    return await page_service.get_document_pages(document_id, skip=skip, limit=limit)

@router.get(
    "/{document_id}/structure",
    response_model=DocumentStructureResponse,
    summary="Get document structure",
    description="Analyzes document pages and extracts its hierarchical structural outline."
)
async def get_document_structure(
    document_id: uuid.UUID,
    structure_service: StructureService = Depends(get_structure_service)
) -> DocumentStructureResponse:
    structure = await structure_service.get_document_structure(document_id)
    return DocumentStructureResponse(
        document_id=document_id,
        structure=structure
    )

@router.get(
    "", 
    response_model=Sequence[DocumentResponse],
    summary="List and filter documents",
    description="Lists documents from the registry, filtered by document source regulator or status."
)
async def list_documents(
    source: Optional[SourceEnum] = Query(None, description="Filter by document source (RBI/SEBI)"),
    status: Optional[StatusEnum] = Query(None, description="Filter by lifecycle status"),
    sort_by: SortByEnum = Query(SortByEnum.uploaded_at, description="Field to sort by"),
    sort_order: SortOrderEnum = Query(SortOrderEnum.desc, description="Order of sorting (asc or desc)"),
    skip: int = Query(0, ge=0, description="Number of documents to skip"),
    limit: int = Query(100, ge=1, le=100, description="Max number of documents to return"),
    service: DocumentService = Depends(get_document_service)
) -> Sequence[DocumentResponse]:
    return await service.list_documents(
        source=source,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit
    )

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

@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and register a document",
    description="Uploads a regulatory PDF file, stores it locally under source subdirectories, and registers metadata in the database."
)
async def upload_document(
    source: SourceEnum = Form(..., description="The regulatory agency (RBI or SEBI)"),
    title: str = Form(..., max_length=255, description="Document title"),
    document_type: Optional[str] = Form(None, max_length=100, description="E.g. Circular, Regulation"),
    publication_date: Optional[str] = Form(None, description="Date formatted as YYYY-MM-DD"),
    page_count: Optional[int] = Form(None, ge=0),
    file: UploadFile = File(..., description="The PDF document file to store"),
    document_service: DocumentService = Depends(get_document_service),
    storage_service: StorageService = Depends(get_storage_service)
) -> DocumentUploadResponse:
    # 1. Validate file extension (Only PDF allowed)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )
        
    # 2. Validate file size (Max 50 MB)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds the maximum limit of 50 MB"
        )

    pub_date: Optional[date] = None
    if publication_date:
        try:
            pub_date = datetime.strptime(publication_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="publication_date must be in YYYY-MM-DD format"
            ) from e

    # Save file via StorageService (handles checksum & deduplication check)
    file_path, checksum = await storage_service.save_file(
        file_data=file.file,
        original_filename=file.filename,
        source=source.value
    )

    doc_create = DocumentCreate(
        title=title,
        source=source,
        file_name=file.filename,
        file_path=file_path,
        document_type=document_type,
        publication_date=pub_date,
        checksum=checksum,
        page_count=page_count
    )

    doc = await document_service.register_document(doc_create)
    return DocumentUploadResponse(
        document_id=doc.id,
        status="uploaded"
    )
