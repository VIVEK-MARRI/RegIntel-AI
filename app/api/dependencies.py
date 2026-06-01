from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db_session
from app.services.document import DocumentService
from app.services.storage_provider import StorageProvider, LocalStorageProvider
from app.services.storage_service import StorageService
from app.services.parser_service import ParserService
from app.services.page import PageService
from app.services.metadata.service import MetadataService
from app.services.metadata.extractor import (
    FileMetadataExtractor,
    PDFStructureExtractor,
    RegulatorMetadataExtractor
)
from app.services.structure.service import StructureService
from app.services.structure.rule_based import RuleBasedStructureExtractor

# Global local storage provider instance
_storage_provider = LocalStorageProvider(settings.STORAGE_ROOT)

async def get_document_service(
    db_session: AsyncSession = Depends(get_db_session)
) -> DocumentService:
    """Dependency injection provider for DocumentService."""
    return DocumentService(db_session)

def get_storage_provider() -> StorageProvider:
    """Dependency injection provider for StorageProvider (defaults to local storage)."""
    return _storage_provider

async def get_storage_service(
    provider: StorageProvider = Depends(get_storage_provider),
    db_session: AsyncSession = Depends(get_db_session)
) -> StorageService:
    """Dependency injection provider for StorageService."""
    return StorageService(provider, db_session)

async def get_parser_service(
    doc_service: DocumentService = Depends(get_document_service)
) -> ParserService:
    """Dependency injection provider for ParserService."""
    return ParserService(doc_service, settings.STORAGE_ROOT)

async def get_page_service(
    db_session: AsyncSession = Depends(get_db_session),
    doc_service: DocumentService = Depends(get_document_service)
) -> PageService:
    """Dependency injection provider for PageService."""
    return PageService(db_session, doc_service)

# Global MetadataService instance configured with standard extractors
_metadata_service = MetadataService([
    FileMetadataExtractor(),
    PDFStructureExtractor(),
    RegulatorMetadataExtractor()
])

def get_metadata_service() -> MetadataService:
    """Dependency injection provider for MetadataService."""
    return _metadata_service

async def get_structure_service(
    page_service: PageService = Depends(get_page_service)
) -> StructureService:
    """Dependency injection provider for StructureService."""
    return StructureService(page_service, RuleBasedStructureExtractor())
