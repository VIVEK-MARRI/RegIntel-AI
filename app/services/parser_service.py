import uuid
import logging
from typing import Callable, Any, Dict, List

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

from pathlib import Path
from app.services.document import DocumentService
from app.services.page import PageService
from app.models.document import StatusEnum

logger = logging.getLogger(__name__)


class PDFParsingError(Exception):
    """Exception raised when PDF parsing fails."""

    pass


class ParserService:
    """PDF parsing service extracting text page-by-page using PyMuPDF and updating registry status."""

    def __init__(
        self,
        document_service: DocumentService,
        storage_root: str,
        page_service: PageService = None,
    ):
        self.document_service = document_service
        self.storage_root = Path(storage_root).resolve()
        self.page_service = page_service
        logger.info(f"Initialized ParserService with storage root: {self.storage_root}")

    async def parse_document(
        self, document_id: Any, progress_hook: Callable[[int, int], None] = None
    ) -> List[Dict[str, Any]]:
        """Parses a registered document by its ID and updates its status lifecycle.

        Transitions document status: UPLOADED -> PARSING -> PARSED (or FAILED on error).

        Args:
            document_id: UUID of the document in the registry.
            progress_hook: Optional callback invoked as progress_hook(current_page, total_pages).

        Returns:
            A list of structured page dictionaries: [{"page_number": int, "content": str}, ...]
        """
        # 1. Fetch document metadata — coerce string to UUID for SQLAlchemy
        if isinstance(document_id, str):
            document_id = uuid.UUID(document_id)
        doc = await self.document_service.get_document_by_id(document_id)

        # 2. Update status: UPLOADED -> PARSING
        logger.info(f"Transitioning document {doc.id} to PARSING status")
        await self.document_service.update_document_status(doc.id, StatusEnum.PARSING)

        file_path = (self.storage_root / doc.file_path).resolve()

        if not file_path.exists() or not file_path.is_file():
            logger.error(f"File not found for parsing: {file_path}")
            await self.document_service.update_document_status(
                doc.id, StatusEnum.FAILED
            )
            raise PDFParsingError(f"File not found on disk: {doc.file_path}")

        parsed_pages = []
        doc_fitz = None
        try:
            if fitz is None:
                raise RuntimeError(
                    "PyMuPDF (fitz) is required for PDF parsing but is not installed."
                )

            # 3. Open PDF using PyMuPDF
            logger.info(f"Opening PDF for parsing: {file_path}")
            try:
                doc_fitz = fitz.open(file_path)
            except Exception as fe:
                logger.error(f"PyMuPDF failed to open file {file_path}: {fe}")
                raise PDFParsingError(f"Corrupted or invalid PDF file: {fe}") from fe

            total_pages = doc_fitz.page_count
            if total_pages == 0:
                raise PDFParsingError("PDF file contains no pages or is corrupted.")

            # Update page_count in DB if not set
            if doc.page_count != total_pages:
                from app.schemas.document import DocumentUpdate

                await self.document_service.update_document_metadata(
                    doc.id, DocumentUpdate(page_count=total_pages)
                )

            # 4. Extract page-level text
            for i in range(total_pages):
                page = doc_fitz[i]
                text = page.get_text()

                # 1-based page index
                page_num = i + 1

                # Strip whitespaces, support empty pages (handled gracefully returning empty string)
                parsed_pages.append({"page_number": page_num, "content": text.strip()})

                # Trigger progress/monitoring hook
                if progress_hook:
                    try:
                        progress_hook(page_num, total_pages)
                    except Exception as he:
                        logger.warning(f"Monitoring progress hook failed: {he}")

                logger.debug(
                    f"Parsed page {page_num}/{total_pages} for document {doc.id}"
                )

            doc_fitz.close()
            doc_fitz = None

            # 5. Store parsed pages in database
            if self.page_service is not None:
                try:
                    await self.page_service.store_pages(doc.id, parsed_pages)
                    logger.info(
                        f"Stored {len(parsed_pages)} pages for document {doc.id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to store pages for document {doc.id}: {e}")
                    raise

            # 6. Update status: PARSING -> PARSED
            await self.document_service.update_document_status(
                doc.id, StatusEnum.PARSED
            )
            logger.info(f"Successfully parsed document {doc.id} ({total_pages} pages)")
            return parsed_pages

        except Exception as e:
            logger.error(f"Failed parsing document {doc.id}: {e}", exc_info=True)
            if doc_fitz:
                try:
                    doc_fitz.close()
                except Exception:
                    pass
            # Update status: PARSING -> FAILED
            try:
                await self.document_service.update_document_status(
                    doc.id, StatusEnum.FAILED
                )
            except Exception as se:
                logger.error(f"Failed to update document status to FAILED: {se}")

            if isinstance(e, PDFParsingError):
                raise e
            raise PDFParsingError(f"PyMuPDF failed to parse file: {e}") from e
