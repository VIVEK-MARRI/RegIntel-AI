from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

class DocumentRegistryError(Exception):
    """Base exception for Document Registry module."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

class DocumentNotFoundError(DocumentRegistryError):
    """Exception raised when a document is not found."""
    def __init__(self, document_id: str):
        super().__init__(f"Document with ID '{document_id}' was not found.")
        self.document_id = document_id

class DuplicateDocumentError(DocumentRegistryError):
    """Exception raised when a duplicate document (same checksum) is registered."""
    def __init__(self, checksum: str):
        super().__init__(f"Document with checksum '{checksum}' already exists.")
        self.checksum = checksum

class InvalidStateTransitionError(DocumentRegistryError):
    """Exception raised when an invalid lifecycle state transition is attempted."""
    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"Invalid state transition from '{from_state}' to '{to_state}'.")
        self.from_state = from_state
        self.to_state = to_state

class ChunkNotFoundError(DocumentRegistryError):
    """Exception raised when a chunk is not found."""
    def __init__(self, chunk_id: str):
        super().__init__(f"Chunk with ID '{chunk_id}' was not found.")
        self.chunk_id = chunk_id

def register_exception_handlers(app: FastAPI) -> None:
    """Registers exception handlers for custom domain exceptions."""
    @app.exception_handler(DocumentNotFoundError)
    async def document_not_found_handler(request: Request, exc: DocumentNotFoundError):
        logger.warning(f"DocumentNotFoundError: {exc.message}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message, "error_code": "DOCUMENT_NOT_FOUND"}
        )

    @app.exception_handler(DuplicateDocumentError)
    async def duplicate_document_handler(request: Request, exc: DuplicateDocumentError):
        logger.warning(f"DuplicateDocumentError: {exc.message}")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": exc.message, "error_code": "DUPLICATE_DOCUMENT"}
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_state_transition_handler(request: Request, exc: InvalidStateTransitionError):
        logger.warning(f"InvalidStateTransitionError: {exc.message}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message, "error_code": "INVALID_STATE_TRANSITION"}
        )

    @app.exception_handler(ChunkNotFoundError)
    async def chunk_not_found_handler(request: Request, exc: ChunkNotFoundError):
        logger.warning(f"ChunkNotFoundError: {exc.message}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message, "error_code": "CHUNK_NOT_FOUND"}
        )

    @app.exception_handler(DocumentRegistryError)
    async def general_registry_error_handler(request: Request, exc: DocumentRegistryError):
        logger.error(f"DocumentRegistryError: {exc.message}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected error occurred in the document registry.", "error_code": "REGISTRY_ERROR"}
        )
