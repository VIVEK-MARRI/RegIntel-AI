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
from app.services.structure.hierarchy import HierarchyBuilder
from app.services.structure.validator import HierarchyValidator
from app.core.token_utils import SimpleTokenizer
from app.services.structure.chunker import HierarchicalChunker, HierarchicalChunkerService
from app.services.structure.enricher import MetadataEnricher, MetadataValidator
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding import EmbeddingProvider, embedding_provider
from app.services.embedding.pipeline import EmbeddingPipeline
from app.services.embedding.index_manager import VectorIndexManager
from app.services.embedding.retrieval import RetrievalService
from app.services.embedding.benchmark_suite import RetrievalBenchmarkRunner
from app.services.validation.embedding import EmbeddingQualityValidator
from app.services.bm25.base import BM25Retriever
from app.services.bm25.service import BM25RetrieverService

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

def get_hierarchy_builder() -> HierarchyBuilder:
    """Dependency injection provider for HierarchyBuilder."""
    return HierarchyBuilder()

def get_hierarchy_validator() -> HierarchyValidator:
    """Dependency injection provider for HierarchyValidator."""
    return HierarchyValidator()

def get_metadata_enricher() -> MetadataEnricher:
    """Dependency injection provider for MetadataEnricher."""
    return MetadataEnricher(MetadataValidator())

async def get_hierarchical_chunker_service(
    doc_service: DocumentService = Depends(get_document_service),
    page_service: PageService = Depends(get_page_service),
    enricher: MetadataEnricher = Depends(get_metadata_enricher)
) -> HierarchicalChunkerService:
    """Dependency injection provider for HierarchicalChunkerService."""
    tokenizer = SimpleTokenizer()
    chunker = HierarchicalChunker(tokenizer)
    return HierarchicalChunkerService(doc_service, page_service, chunker, enricher)

async def get_chunk_registry_service(
    db_session: AsyncSession = Depends(get_db_session),
    doc_service: DocumentService = Depends(get_document_service)
) -> ChunkRegistryService:
    """Dependency injection provider for ChunkRegistryService."""
    return ChunkRegistryService(db_session, doc_service)

def get_embedding_provider() -> EmbeddingProvider:
    """Dependency injection provider for EmbeddingProvider singleton."""
    return embedding_provider

async def get_embedding_pipeline(
    db_session: AsyncSession = Depends(get_db_session),
    chunk_service: ChunkRegistryService = Depends(get_chunk_registry_service),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider)
) -> EmbeddingPipeline:
    """Dependency injection provider for EmbeddingPipeline."""
    return EmbeddingPipeline(db_session, chunk_service, embedding_provider)

async def get_vector_index_manager(
    db_session: AsyncSession = Depends(get_db_session)
) -> VectorIndexManager:
    """Dependency injection provider for VectorIndexManager."""
    return VectorIndexManager(db_session)

async def get_retrieval_service(
    db_session: AsyncSession = Depends(get_db_session),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider)
) -> RetrievalService:
    """Dependency injection provider for RetrievalService."""
    return RetrievalService(db_session, embedding_provider)

async def get_embedding_quality_validator(
    db_session: AsyncSession = Depends(get_db_session)
) -> EmbeddingQualityValidator:
    """Dependency injection provider for EmbeddingQualityValidator."""
    return EmbeddingQualityValidator(db_session)

async def get_benchmark_runner(
    retrieval_service: RetrievalService = Depends(get_retrieval_service)
) -> RetrievalBenchmarkRunner:
    """Dependency injection provider for RetrievalBenchmarkRunner."""
    return RetrievalBenchmarkRunner(retrieval_service)

async def get_bm25_retriever(
    db_session: AsyncSession = Depends(get_db_session)
) -> BM25Retriever:
    """Dependency injection provider for BM25Retriever."""
    return BM25RetrieverService(db_session)
