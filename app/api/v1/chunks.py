import uuid
from typing import Optional, Sequence
from fastapi import APIRouter, Depends, Query
from app.api.dependencies import get_chunk_registry_service
from app.schemas.chunk import StoredChunkResponse, ChunkSortByEnum
from app.schemas.document import SortOrderEnum
from app.services.chunk_registry import ChunkRegistryService

router = APIRouter()

@router.get(
    "",
    response_model=Sequence[StoredChunkResponse],
    summary="List and filter chunks",
    description="Lists chunks across all documents, supporting filtering, sorting, partial matching search, and pagination."
)
async def list_chunks(
    document_id: Optional[uuid.UUID] = Query(None, description="Filter chunks by document ID"),
    section: Optional[str] = Query(None, description="Search by section (partial match)"),
    subsection: Optional[str] = Query(None, description="Search by subsection (partial match)"),
    sort_by: ChunkSortByEnum = Query(ChunkSortByEnum.page_number, description="Field to sort by"),
    sort_order: SortOrderEnum = Query(SortOrderEnum.asc, description="Sort direction (asc or desc)"),
    skip: int = Query(0, ge=0, description="Number of chunks to skip"),
    limit: int = Query(100, ge=1, le=100, description="Max number of chunks to return"),
    service: ChunkRegistryService = Depends(get_chunk_registry_service)
) -> Sequence[StoredChunkResponse]:
    return await service.list_chunks(
        document_id=document_id,
        section=section,
        subsection=subsection,
        sort_by=sort_by.value,
        sort_order=sort_order.value,
        skip=skip,
        limit=limit
    )

@router.get(
    "/{chunk_id}",
    response_model=StoredChunkResponse,
    summary="Get chunk details",
    description="Retrieves details for a stored chunk by its UUID."
)
async def get_chunk(
    chunk_id: uuid.UUID,
    service: ChunkRegistryService = Depends(get_chunk_registry_service)
) -> StoredChunkResponse:
    return await service.get_chunk_by_id(chunk_id)
