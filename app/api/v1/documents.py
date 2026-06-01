import uuid
from typing import Optional, Sequence
from datetime import datetime, date
from fastapi import APIRouter, Depends, Query, status, UploadFile, File, Form, HTTPException
from app.api.dependencies import (
    get_document_service, 
    get_storage_service, 
    get_page_service, 
    get_structure_service,
    get_hierarchy_builder,
    get_hierarchy_validator,
    get_hierarchical_chunker_service,
    get_chunk_registry_service
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
from app.schemas.hierarchy import DocumentHierarchyResponse
from app.schemas.chunk import StoredChunkResponse, ChunkSortByEnum
from app.services.document import DocumentService
from app.services.storage_service import StorageService
from app.services.page import PageService
from app.services.structure.service import StructureService
from app.services.structure.hierarchy import HierarchyBuilder
from app.services.structure.validator import HierarchyValidator
from app.services.structure.chunker import HierarchicalChunkerService
from app.services.chunk_registry import ChunkRegistryService

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
    "/{document_id}/hierarchy",
    response_model=DocumentHierarchyResponse,
    summary="Get document hierarchy tree",
    description="Transforms parsed document structural outline into a navigable tree structure."
)
async def get_document_hierarchy(
    document_id: uuid.UUID,
    structure_service: StructureService = Depends(get_structure_service),
    document_service: DocumentService = Depends(get_document_service),
    hierarchy_builder: HierarchyBuilder = Depends(get_hierarchy_builder),
    hierarchy_validator: HierarchyValidator = Depends(get_hierarchy_validator)
) -> DocumentHierarchyResponse:
    # 1. Fetch document to get fallback title (raises DocumentNotFoundError if missing)
    doc = await document_service.get_document_by_id(document_id)
    
    # 2. Extract structure elements
    structure = await structure_service.get_document_structure(document_id)
    
    # 3. Build tree
    root_node = hierarchy_builder.build_hierarchy(document_id, doc.title, structure)
    
    # 4. Validate hierarchy tree
    import logging
    logger = logging.getLogger(__name__)
    validation_errors = hierarchy_validator.validate(root_node)
    if validation_errors:
        logger.warning(f"Hierarchy validation warnings for {document_id}: {validation_errors}")
        
    return DocumentHierarchyResponse(
        document_id=document_id,
        root=root_node
    )

@router.get(
    "/{document_id}/chunks",
    response_model=Sequence[StoredChunkResponse],
    summary="Get document stored chunks",
    description="Retrieves paginated stored chunks for a specific document, supporting filtering, sorting, and partial match search."
)
async def get_document_chunks(
    document_id: uuid.UUID,
    section: Optional[str] = Query(None, description="Search by section (partial match)"),
    subsection: Optional[str] = Query(None, description="Search by subsection (partial match)"),
    sort_by: ChunkSortByEnum = Query(ChunkSortByEnum.page_number, description="Field to sort by"),
    sort_order: SortOrderEnum = Query(SortOrderEnum.asc, description="Sort direction (asc or desc)"),
    skip: int = Query(0, ge=0, description="Number of chunks to skip"),
    limit: int = Query(100, ge=1, le=100, description="Max number of chunks to return"),
    service: ChunkRegistryService = Depends(get_chunk_registry_service)
) -> Sequence[StoredChunkResponse]:
    return await service.get_document_chunks(
        document_id=document_id,
        section=section,
        subsection=subsection,
        sort_by=sort_by.value,
        sort_order=sort_order.value,
        skip=skip,
        limit=limit
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
