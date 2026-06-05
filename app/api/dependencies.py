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
from app.services.bm25.bm25_service import BM25Service
from app.services.query_analysis.service import QueryAnalyzer
from app.services.hybrid.service import HybridRetriever
from app.services.hybrid.pipeline import HybridRerankPipeline
from app.services.reranker.model import BGERerankerProvider
from app.services.reranker.service import RerankerService

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


# Lazy singleton BM25Service — the in-memory index lives for the process lifetime.
_bm25_service: BM25Service | None = None


def get_bm25_service() -> BM25Service:
    """Dependency injection provider for the high-level BM25Service singleton.

    The BM25 index is held in memory; recreating the service on every request
    would force a full index rebuild each time, which is unacceptable for
    production traffic.
    """
    global _bm25_service
    if _bm25_service is None:
        _bm25_service = BM25Service()
    return _bm25_service


def reset_bm25_service() -> None:
    """Reset the BM25Service singleton (used by tests)."""
    global _bm25_service
    _bm25_service = None


def get_query_analyzer() -> QueryAnalyzer:
    """Dependency injection provider for QueryAnalyzer."""
    return QueryAnalyzer()

def get_hybrid_retriever(
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    bm25_retriever: BM25Retriever = Depends(get_bm25_retriever),
    query_analyzer: QueryAnalyzer = Depends(get_query_analyzer),
) -> HybridRetriever:
    """Dependency injection provider for HybridRetriever with query analysis."""
    return HybridRetriever(
        retrieval_service,
        bm25_retriever,
        query_analyzer=query_analyzer,
    )


# Lazy singleton reranker provider — loaded on first request
_reranker_provider: BGERerankerProvider | None = None

def get_reranker_provider() -> BGERerankerProvider:
    """Dependency injection provider for BGERerankerProvider (singleton)."""
    global _reranker_provider
    if _reranker_provider is None:
        _reranker_provider = BGERerankerProvider(
            model_name=settings.RERANKER_MODEL_NAME,
            device=settings.RERANKER_DEVICE,
            max_length=settings.RERANKER_MAX_LENGTH,
            batch_size=settings.RERANKER_BATCH_SIZE,
        )
    return _reranker_provider

def get_reranker_service(
    provider: BGERerankerProvider = Depends(get_reranker_provider),
) -> RerankerService:
    """Dependency injection provider for RerankerService."""
    return RerankerService(
        provider=provider,
        default_top_k=settings.RERANKER_DEFAULT_TOP_K,
        default_score_threshold=settings.RERANKER_SCORE_THRESHOLD,
    )


async def get_hybrid_rerank_pipeline(
    hybrid_retriever: HybridRetriever = Depends(get_hybrid_retriever),
    reranker: RerankerService = Depends(get_reranker_service),
) -> HybridRerankPipeline:
    """Dependency injection provider for the full hybrid + rerank pipeline."""
    return HybridRerankPipeline(hybrid_retriever, reranker)


# ─── Module 5.1 — Answer Generation ──────────────────────────────────────────

from app.schemas.answer_generation import LLMProviderName  # noqa: E402
from app.services.answer_generation import (  # noqa: E402
    AnswerGeneratorService,
    PromptBuilder,
    get_provider,
)


def get_llm_provider_name() -> LLMProviderName:
    """Resolve the configured LLM provider name."""
    name = (settings.LLM_PROVIDER or "mock").lower()
    try:
        return LLMProviderName(name)
    except ValueError:
        return LLMProviderName.MOCK


def get_llm_provider(
    provider_name: LLMProviderName = Depends(get_llm_provider_name),
) -> "BaseLLMProvider":  # noqa: F821 – forward ref
    """Build the LLM provider for this request."""
    return get_provider(
        provider_name,
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY or None,
        api_base=settings.LLM_API_BASE or None,
        timeout=settings.LLM_TIMEOUT_SEC,
    )


def get_prompt_builder() -> PromptBuilder:
    """Build the canonical PromptBuilder."""
    return PromptBuilder(
        context_token_budget=settings.ANSWER_CONTEXT_TOKEN_BUDGET,
    )


def get_answer_generator_service(
    provider: "BaseLLMProvider" = Depends(get_llm_provider),  # noqa: F821
    builder: PromptBuilder = Depends(get_prompt_builder),
) -> AnswerGeneratorService:
    """Dependency injection provider for AnswerGeneratorService."""
    return AnswerGeneratorService(provider=provider, prompt_builder=builder)


# ─── Module 5.2 — Citation Engine ────────────────────────────────────────────

from app.services.citation import (  # noqa: E402
    CitationBuilder,
    CitationMapper,
    CitationService,
    ClaimExtractor,
    build_default_citation_service,
)


def get_citation_service() -> CitationService:
    """Dependency injection provider for CitationService."""
    return build_default_citation_service()


# ─── Module 5.3 — Confidence Scoring Engine ─────────────────────────────────

from app.services.confidence import (  # noqa: E402
    ConfidenceService,
    build_default_confidence_service,
)


def get_confidence_service() -> ConfidenceService:
    """Dependency injection provider for ConfidenceService.

    The service is a singleton so its in-process :class:`ConfidenceMetrics`
    collector accumulates across all requests.
    """
    return _confidence_service_singleton()


_confidence_service: "ConfidenceService | None" = None  # type: ignore[name-defined]


def _confidence_service_singleton() -> "ConfidenceService":  # noqa: F821
    global _confidence_service
    if _confidence_service is None:
        _confidence_service = build_default_confidence_service()
    return _confidence_service


def reset_confidence_service() -> None:
    """Reset the ConfidenceService singleton (used by tests)."""
    global _confidence_service
    _confidence_service = None


# ─── Module 5.4 — Hallucination Guard ──────────────────────────────────────

from app.services.hallucination import (  # noqa: E402
    HallucinationGuardService,
    build_default_hallucination_guard,
)


def get_hallucination_guard_service(
    provider: "BaseLLMProvider" = Depends(get_llm_provider),  # noqa: F821
) -> HallucinationGuardService:
    """Dependency injection provider for HallucinationGuardService.

    The service is a singleton so the configured LLM provider is shared
    across requests.  When ``provider`` is a :class:`MockLLMProvider` the
    service still produces deterministic offline results via the lexical
    fallback.
    """
    return _hallucination_guard_singleton(provider)


_hallucination_guard: "HallucinationGuardService | None" = None  # type: ignore[name-defined]


def _hallucination_guard_singleton(provider) -> "HallucinationGuardService":  # noqa: F821
    global _hallucination_guard
    if _hallucination_guard is None:
        _hallucination_guard = build_default_hallucination_guard(provider=provider)
    elif provider is not None:
        # Allow tests to inject a fresh provider on the singleton.
        _hallucination_guard.set_provider(provider)
    return _hallucination_guard


def reset_hallucination_guard() -> None:
    """Reset the HallucinationGuardService singleton (used by tests)."""
    global _hallucination_guard
    _hallucination_guard = None


# ─── Module 5.5 — Source Attribution Engine ────────────────────────────────

from app.services.attribution import (  # noqa: E402
    SourceAttributionService,
    build_default_attribution_service,
)


def get_attribution_service() -> SourceAttributionService:
    """Dependency injection provider for SourceAttributionService."""
    return _attribution_service_singleton()


_attribution_service: "SourceAttributionService | None" = None  # type: ignore[name-defined]


def _attribution_service_singleton() -> "SourceAttributionService":
    global _attribution_service
    if _attribution_service is None:
        _attribution_service = build_default_attribution_service()
    return _attribution_service


def reset_attribution_service() -> None:
    """Reset the SourceAttributionService singleton (used by tests)."""
    global _attribution_service
    _attribution_service = None


# ─── Module 5.6 — Response Orchestrator ────────────────────────────────────

from app.services.orchestrator import (  # noqa: E402
    PipelineCoordinator,
    ResponseOrchestrator,
    build_default_orchestrator,
)


def get_response_orchestrator() -> ResponseOrchestrator:
    """Dependency injection provider for the ResponseOrchestrator.

    The orchestrator reuses the singletons from Modules 5.1-5.5.
    """
    return _orchestrator_singleton()


_orchestrator: "ResponseOrchestrator | None" = None  # type: ignore[name-defined]


def _orchestrator_singleton() -> "ResponseOrchestrator":
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = build_default_orchestrator(
            answer_generator=get_answer_generator_service(
                provider=get_llm_provider(),
                builder=get_prompt_builder(),
            ),
            citation=get_citation_service(),
            confidence=get_confidence_service(),
            hallucination_guard=get_hallucination_guard_service(provider=get_llm_provider()),
            attribution=get_attribution_service(),
        )
    return _orchestrator


def reset_response_orchestrator() -> None:
    """Reset the ResponseOrchestrator singleton (used by tests)."""
    global _orchestrator
    _orchestrator = None


# ─── Module 5.7 — Answer Evaluation Framework ──────────────────────────────

from app.services.evaluation import (  # noqa: E402
    AnswerEvaluationService,
    build_default_evaluation_service,
)


def get_evaluation_service() -> AnswerEvaluationService:
    """Dependency injection provider for AnswerEvaluationService."""
    return _evaluation_service_singleton()


_evaluation_service: "AnswerEvaluationService | None" = None  # type: ignore[name-defined]


def _evaluation_service_singleton() -> "AnswerEvaluationService":
    global _evaluation_service
    if _evaluation_service is None:
        _evaluation_service = build_default_evaluation_service()
    return _evaluation_service


def reset_evaluation_service() -> None:
    """Reset the AnswerEvaluationService singleton (used by tests)."""
    global _evaluation_service
    _evaluation_service = None


# ─── Module 5.8 — Answer Analytics Platform ───────────────────────────────

from app.services.answer_analytics import (  # noqa: E402
    AnswerAnalyticsService,
    AnswerHealthMonitor,
    build_default_answer_analytics_service,
)


def get_answer_analytics_service() -> AnswerAnalyticsService:
    """Dependency injection provider for AnswerAnalyticsService (singleton)."""
    return _answer_analytics_singleton()


_answer_analytics: "AnswerAnalyticsService | None" = None  # type: ignore[name-defined]


def _answer_analytics_singleton() -> "AnswerAnalyticsService":
    global _answer_analytics
    if _answer_analytics is None:
        _answer_analytics = build_default_answer_analytics_service()
    return _answer_analytics


def reset_answer_analytics_service() -> None:
    """Reset the AnswerAnalyticsService singleton (used by tests)."""
    global _answer_analytics
    _answer_analytics = None


def get_answer_health_monitor() -> AnswerHealthMonitor:
    """Dependency injection provider for AnswerHealthMonitor."""
    return AnswerHealthMonitor(service=get_answer_analytics_service())
