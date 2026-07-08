import uuid
import mimetypes
import logging
from typing import Optional, Sequence
from fastapi import (
    APIRouter,
    Depends,
    Query,
    status,
    UploadFile,
    File,
    Form,
    HTTPException,
)
from app.api.dependencies import (
    get_document_service,
    get_storage_service,
    get_page_service,
    get_structure_service,
    get_hierarchy_builder,
    get_hierarchy_validator,
    get_chunk_registry_service,
    get_ingestion_service,
)
from app.models.document import SourceEnum, StatusEnum
from app.schemas.document import (
    DocumentCreate,
    DocumentResponse,
    DocumentDetailResponse,
    DocumentStatusUpdate,
    DocumentUpdate,
    DocumentUploadResponse,
    SortByEnum,
    SortOrderEnum,
    PageResponse,
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
from app.services.chunk_registry import ChunkRegistryService
from app.services.ingestion import AutoIngestionService

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed file types for user upload
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".html", ".htm"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/html",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def _validate_upload_file(file: UploadFile) -> None:
    """Validate file extension, MIME type, and size."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    mime_type, _ = mimetypes.guess_type(file.filename)
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MIME type '{mime_type}'. Allowed: PDF, DOCX, TXT, HTML",
        )

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds the maximum limit of {MAX_FILE_SIZE // (1024*1024)} MB",
        )


def _sanitize_filename(filename: str) -> str:
    """Remove path traversal characters from filename."""
    import os

    sanitized = os.path.basename(filename)
    if not sanitized:
        sanitized = "document"
    return sanitized


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new document",
)
async def register_document(
    doc_in: DocumentCreate,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    return await service.register_document(doc_in)


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document details with processing info",
)
async def get_document(
    document_id: uuid.UUID,
    document_service: DocumentService = Depends(get_document_service),
    chunk_service: ChunkRegistryService = Depends(get_chunk_registry_service),
    ingestion_service: AutoIngestionService = Depends(get_ingestion_service),
) -> DocumentDetailResponse:
    doc = await document_service.get_document_by_id(document_id)
    chunks = await chunk_service.get_document_chunks(document_id)
    embedding_count = 0
    for c in chunks:
        emb = await chunk_service.get_chunk_embeddings(c.id)
        embedding_count += len([e for e in (emb or []) if e.status == "completed"])

    run = ingestion_service.repository.latest_run_for_document(str(document_id))
    processing_status = "pending"
    indexed = False
    if run:
        processing_status = run.status.value
        indexed = run.status.value == "completed"

    return DocumentDetailResponse(
        id=doc.id,
        title=doc.title,
        source=doc.source,
        file_name=doc.file_name,
        file_path=doc.file_path,
        document_type=doc.document_type,
        publication_date=doc.publication_date,
        checksum=doc.checksum,
        page_count=doc.page_count,
        status=doc.status,
        uploaded_at=doc.uploaded_at,
        updated_at=doc.updated_at,
        chunk_count=len(chunks),
        page_count_actual=doc.page_count,
        embedding_count=embedding_count,
        indexed=indexed,
        processing_status=processing_status,
    )


@router.get(
    "/{document_id}/pages",
    response_model=Sequence[PageResponse],
    summary="Get document pages",
)
async def get_document_pages(
    document_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    page_service: PageService = Depends(get_page_service),
) -> Sequence[PageResponse]:
    return await page_service.get_document_pages(document_id, skip=skip, limit=limit)


@router.get(
    "/{document_id}/structure",
    response_model=DocumentStructureResponse,
    summary="Get document structure",
)
async def get_document_structure(
    document_id: uuid.UUID,
    structure_service: StructureService = Depends(get_structure_service),
) -> DocumentStructureResponse:
    structure = await structure_service.get_document_structure(document_id)
    return DocumentStructureResponse(document_id=document_id, structure=structure)


@router.get(
    "/{document_id}/hierarchy",
    response_model=DocumentHierarchyResponse,
    summary="Get document hierarchy tree",
)
async def get_document_hierarchy(
    document_id: uuid.UUID,
    structure_service: StructureService = Depends(get_structure_service),
    document_service: DocumentService = Depends(get_document_service),
    hierarchy_builder: HierarchyBuilder = Depends(get_hierarchy_builder),
    hierarchy_validator: HierarchyValidator = Depends(get_hierarchy_validator),
) -> DocumentHierarchyResponse:
    doc = await document_service.get_document_by_id(document_id)
    structure = await structure_service.get_document_structure(document_id)
    root_node = hierarchy_builder.build_hierarchy(document_id, doc.title, structure)
    validation_errors = hierarchy_validator.validate(root_node)
    if validation_errors:
        logger.warning(
            "Hierarchy validation warnings for %s: %s", document_id, validation_errors
        )
    return DocumentHierarchyResponse(document_id=document_id, root=root_node)


@router.get(
    "/{document_id}/chunks",
    response_model=Sequence[StoredChunkResponse],
    summary="Get document stored chunks",
)
async def get_document_chunks(
    document_id: uuid.UUID,
    section: Optional[str] = Query(None),
    subsection: Optional[str] = Query(None),
    sort_by: ChunkSortByEnum = Query(ChunkSortByEnum.page_number),
    sort_order: SortOrderEnum = Query(SortOrderEnum.asc),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    service: ChunkRegistryService = Depends(get_chunk_registry_service),
) -> Sequence[StoredChunkResponse]:
    return await service.get_document_chunks(
        document_id=document_id,
        section=section,
        subsection=subsection,
        sort_by=sort_by.value,
        sort_order=sort_order.value,
        skip=skip,
        limit=limit,
    )


@router.get(
    "",
    response_model=Sequence[DocumentResponse],
    summary="List and filter documents",
)
async def list_documents(
    source: Optional[SourceEnum] = Query(None),
    status: Optional[StatusEnum] = Query(None),
    sort_by: SortByEnum = Query(SortByEnum.uploaded_at),
    sort_order: SortOrderEnum = Query(SortOrderEnum.desc),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    service: DocumentService = Depends(get_document_service),
) -> Sequence[DocumentResponse]:
    return await service.list_documents(
        source=source,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@router.patch(
    "/{document_id}/status",
    response_model=DocumentResponse,
    summary="Update document status",
)
async def update_document_status(
    document_id: uuid.UUID,
    status_update: DocumentStatusUpdate,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    return await service.update_document_status(document_id, status_update.status)


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Update document metadata",
)
async def update_document_metadata(
    document_id: uuid.UUID,
    metadata_update: DocumentUpdate,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    return await service.update_document_metadata(document_id, metadata_update)


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, DOCX, TXT, HTML) for ingestion",
    description="Uploads an enterprise document, validates it, saves it, registers it, and asynchronously triggers the full ingestion pipeline (parse, chunk, embed, index, KG extraction).",
)
async def upload_document(
    file: UploadFile = File(..., description="Document file (PDF, DOCX, TXT, HTML)"),
    title: Optional[str] = Form(
        None, max_length=255, description="Document title (defaults to filename)"
    ),
    document_type: Optional[str] = Form(
        None, max_length=100, description="E.g. Policy, Report, SOP"
    ),
    source: Optional[SourceEnum] = Form(
        SourceEnum.USER_UPLOAD, description="Document source"
    ),
    document_service: DocumentService = Depends(get_document_service),
    storage_service: StorageService = Depends(get_storage_service),
    ingestion_service: AutoIngestionService = Depends(get_ingestion_service),
) -> DocumentUploadResponse:
    _validate_upload_file(file)

    original_filename = _sanitize_filename(file.filename or "document")
    display_title = title or original_filename.rsplit(".", 1)[0]

    file_path, checksum = await storage_service.save_file(
        file_data=file.file,
        original_filename=original_filename,
        source=source.value,
    )

    doc_create = DocumentCreate(
        title=display_title,
        source=source,
        file_name=original_filename,
        file_path=file_path,
        document_type=document_type,
        checksum=checksum,
    )

    doc = await document_service.register_document(doc_create)

    # Asynchronously process through the ingestion pipeline
    run_id = None
    try:
        result = await ingestion_service.ingest_upload(str(doc.id))
        run_id = result.run_id
        logger.info("Upload ingestion started for document %s (run %s)", doc.id, run_id)
    except Exception as exc:
        logger.exception(
            "Failed to start ingestion for uploaded document %s: %s", doc.id, exc
        )

    return DocumentUploadResponse(
        document_id=doc.id,
        status="processing",
        run_id=run_id,
    )
