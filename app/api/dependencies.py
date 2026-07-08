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

async def get_page_service(
    db_session: AsyncSession = Depends(get_db_session),
    doc_service: DocumentService = Depends(get_document_service)
) -> PageService:
    """Dependency injection provider for PageService."""
    return PageService(db_session, doc_service)

async def get_parser_service(
    doc_service: DocumentService = Depends(get_document_service),
    page_service: PageService = Depends(get_page_service)
) -> ParserService:
    """Dependency injection provider for ParserService."""
    return ParserService(doc_service, settings.STORAGE_ROOT, page_service=page_service)

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
    CitationService,
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
        provider_name = get_llm_provider_name()
        llm_provider = get_llm_provider(provider_name=provider_name)
        _orchestrator = build_default_orchestrator(
            answer_generator=get_answer_generator_service(
                provider=llm_provider,
                builder=get_prompt_builder(),
            ),
            citation=get_citation_service(),
            confidence=get_confidence_service(),
            hallucination_guard=get_hallucination_guard_service(provider=llm_provider),
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


# ─── Module 6.2 — Conversation Management ────────────────────────────────

from app.services.conversation import (  # noqa: E402
    ConversationService,
    build_default_conversation_service,
)


_conversation_service: "ConversationService | None" = None  # type: ignore[name-defined]


def _conversation_service_singleton() -> "ConversationService":
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = build_default_conversation_service()
    return _conversation_service


def get_conversation_service() -> ConversationService:
    """Dependency injection provider for ConversationService (singleton)."""
    return _conversation_service_singleton()


def reset_conversation_service() -> None:
    """Reset the ConversationService singleton (used by tests)."""
    global _conversation_service
    _conversation_service = None


# ─── Module 6.3 — Memory Layer ────────────────────────────────────────────

from app.services.memory import (  # noqa: E402
    MemoryService,
    build_default_memory_service,
)


_memory_service: "MemoryService | None" = None  # type: ignore[name-defined]


def _memory_service_singleton() -> "MemoryService":
    global _memory_service
    if _memory_service is None:
        _memory_service = build_default_memory_service()
    return _memory_service


def get_memory_service() -> MemoryService:
    """Dependency injection provider for MemoryService (singleton)."""
    return _memory_service_singleton()


def reset_memory_service() -> None:
    """Reset the MemoryService singleton (used by tests)."""
    global _memory_service
    _memory_service = None


# ─── Module 6.4 — Query Planning Engine ─────────────────────────────────

from app.services.planning import (  # noqa: E402
    QueryPlanner,
    build_default_query_planner,
)


_query_planner: "QueryPlanner | None" = None  # type: ignore[name-defined]


def _query_planner_singleton() -> "QueryPlanner":
    global _query_planner
    if _query_planner is None:
        _query_planner = build_default_query_planner()
    return _query_planner


def get_query_planner() -> QueryPlanner:
    """Dependency injection provider for QueryPlanner (singleton)."""
    return _query_planner_singleton()


def reset_query_planner() -> None:
    """Reset the QueryPlanner singleton (used by tests)."""
    global _query_planner
    _query_planner = None


# ─── Module 6.5 — Multi-Document Reasoning ───────────────────────────────

from app.services.reasoning import (  # noqa: E402
    MultiDocumentReasoner,
    build_default_multi_document_reasoner,
)


_multi_document_reasoner: "MultiDocumentReasoner | None" = None  # type: ignore[name-defined]


def _multi_document_reasoner_singleton() -> "MultiDocumentReasoner":
    global _multi_document_reasoner
    if _multi_document_reasoner is None:
        _multi_document_reasoner = build_default_multi_document_reasoner()
    return _multi_document_reasoner


def get_multi_document_reasoner() -> MultiDocumentReasoner:
    """Dependency injection provider for MultiDocumentReasoner (singleton)."""
    return _multi_document_reasoner_singleton()


def reset_multi_document_reasoner() -> None:
    """Reset the MultiDocumentReasoner singleton (used by tests)."""
    global _multi_document_reasoner
    _multi_document_reasoner = None


# ─── Module 6.6 — Feedback Intelligence ──────────────────────────────────

from app.services.feedback import (  # noqa: E402
    FeedbackService,
    build_default_feedback_service,
)


_feedback_service: "FeedbackService | None" = None  # type: ignore[name-defined]


def _feedback_service_singleton() -> "FeedbackService":
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = build_default_feedback_service()
    return _feedback_service


def get_feedback_service() -> FeedbackService:
    """Dependency injection provider for FeedbackService (singleton)."""
    return _feedback_service_singleton()


def reset_feedback_service() -> None:
    """Reset the FeedbackService singleton (used by tests)."""
    global _feedback_service
    _feedback_service = None


# ─── Module 6.7 — Copilot Analytics ──────────────────────────────────────

from app.services.copilot_analytics import (  # noqa: E402
    CopilotAnalyticsService,
    build_default_copilot_analytics_service,
)


_copilot_analytics_service: "CopilotAnalyticsService | None" = None  # type: ignore[name-defined]


def _copilot_analytics_service_singleton() -> "CopilotAnalyticsService":
    global _copilot_analytics_service
    if _copilot_analytics_service is None:
        _copilot_analytics_service = build_default_copilot_analytics_service()
    return _copilot_analytics_service


def get_copilot_analytics_service() -> CopilotAnalyticsService:
    """Dependency injection provider for CopilotAnalyticsService (singleton)."""
    return _copilot_analytics_service_singleton()


def reset_copilot_analytics_service() -> None:
    """Reset the CopilotAnalyticsService singleton (used by tests)."""
    global _copilot_analytics_service
    _copilot_analytics_service = None


# ─── Module 7.1 — Regulatory Monitoring Engine ─────────────────────────

from app.services.monitoring import (  # noqa: E402
    MonitoringService,
    build_default_monitoring_service,
)

_monitoring_service: "MonitoringService | None" = None  # type: ignore[name-defined]


def _monitoring_service_singleton() -> "MonitoringService":
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = build_default_monitoring_service()
    return _monitoring_service


def get_monitoring_service() -> MonitoringService:
    """Dependency injection provider for MonitoringService (singleton)."""
    return _monitoring_service_singleton()


def reset_monitoring_service() -> None:
    """Reset the MonitoringService singleton (used by tests)."""
    global _monitoring_service
    _monitoring_service = None


# ─── Module 7.2 — Automated Regulatory Ingestion ────────────────────────

from app.services.ingestion import (  # noqa: E402
    AutoIngestionService,
    build_default_auto_ingestion_service,
)

_ingestion_service: "AutoIngestionService | None" = None  # type: ignore[name-defined]


def _ingestion_service_singleton() -> "AutoIngestionService":
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = build_default_auto_ingestion_service()
    return _ingestion_service


async def get_ingestion_service(
    db_session: AsyncSession = Depends(get_db_session)
) -> AutoIngestionService:
    """Dependency injection provider for AutoIngestionService (singleton)."""
    return _ingestion_service_singleton()


def reset_ingestion_service() -> None:
    """Reset the AutoIngestionService singleton (used by tests)."""
    global _ingestion_service
    _ingestion_service = None


# ─── Module 7.3 — Change Detection Engine ──────────────────────────────

from app.services.change_detection import (  # noqa: E402
    ChangeDetectionService,
    build_default_change_detection_service,
)

_change_detection_service: "ChangeDetectionService | None" = None  # type: ignore[name-defined]


def _change_detection_service_singleton() -> "ChangeDetectionService":
    global _change_detection_service
    if _change_detection_service is None:
        _change_detection_service = build_default_change_detection_service()
    return _change_detection_service


def get_change_detection_service() -> ChangeDetectionService:
    """Dependency injection provider for ChangeDetectionService (singleton)."""
    return _change_detection_service_singleton()


def reset_change_detection_service() -> None:
    """Reset the ChangeDetectionService singleton (used by tests)."""
    global _change_detection_service
    _change_detection_service = None


# ─── Module 7.4 — Impact Analysis Engine ───────────────────────────────

from app.services.impact_analysis import (  # noqa: E402
    ImpactAnalysisService,
    build_default_impact_analysis_service,
)

_impact_analysis_service: "ImpactAnalysisService | None" = None  # type: ignore[name-defined]


def _impact_analysis_service_singleton() -> "ImpactAnalysisService":
    global _impact_analysis_service
    if _impact_analysis_service is None:
        _impact_analysis_service = build_default_impact_analysis_service()
    return _impact_analysis_service


def get_impact_analysis_service() -> ImpactAnalysisService:
    """Dependency injection provider for ImpactAnalysisService (singleton)."""
    return _impact_analysis_service_singleton()


def reset_impact_analysis_service() -> None:
    """Reset the ImpactAnalysisService singleton (used by tests)."""
    global _impact_analysis_service
    _impact_analysis_service = None


# ─── Module 7.5 — Regulatory Alerting System ───────────────────────────

from app.services.alerting import (  # noqa: E402
    AlertService,
    build_default_alert_service,
)

_alert_service: "AlertService | None" = None  # type: ignore[name-defined]


def _alert_service_singleton() -> "AlertService":
    global _alert_service
    if _alert_service is None:
        _alert_service = build_default_alert_service()
    return _alert_service


def get_alert_service() -> AlertService:
    """Dependency injection provider for AlertService (singleton)."""
    return _alert_service_singleton()


def reset_alert_service() -> None:
    """Reset the AlertService singleton (used by tests)."""
    global _alert_service
    _alert_service = None


# ─── Module 7.6 — Knowledge Graph Layer ──────────────────────────────

from app.services.knowledge_graph import (  # noqa: E402
    KnowledgeGraphService,
    build_default_knowledge_graph_service,
)

_knowledge_graph_service: "KnowledgeGraphService | None" = None  # type: ignore[name-defined]


def _knowledge_graph_service_singleton() -> "KnowledgeGraphService":
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        _knowledge_graph_service = build_default_knowledge_graph_service()
    return _knowledge_graph_service


def get_knowledge_graph_service() -> KnowledgeGraphService:
    """Dependency injection provider for KnowledgeGraphService (singleton)."""
    return _knowledge_graph_service_singleton()


def reset_knowledge_graph_service() -> None:
    """Reset the KnowledgeGraphService singleton (used by tests)."""
    global _knowledge_graph_service
    _knowledge_graph_service = None


# ─── Module 7.7 — Agentic Regulatory Research ────────────────────────

from app.services.research import (  # noqa: E402
    ResearchService,
    build_default_research_service,
)

_research_service: "ResearchService | None" = None  # type: ignore[name-defined]


def _research_service_singleton() -> "ResearchService":
    global _research_service
    if _research_service is None:
        _research_service = build_default_research_service()
    return _research_service


def get_research_service() -> ResearchService:
    """Dependency injection provider for ResearchService (singleton)."""
    return _research_service_singleton()


def reset_research_service() -> None:
    """Reset the ResearchService singleton (used by tests)."""
    global _research_service
    _research_service = None


# ─── Module 7.8 — Executive Dashboard ────────────────────────────────

from app.services.dashboard import (  # noqa: E402
    ExecutiveDashboardService,
    build_default_executive_dashboard_service,
)

_dashboard_service: "ExecutiveDashboardService | None" = None  # type: ignore[name-defined]


def _dashboard_service_singleton() -> "ExecutiveDashboardService":
    global _dashboard_service
    if _dashboard_service is None:
        _dashboard_service = build_default_executive_dashboard_service()
    return _dashboard_service


def get_executive_dashboard_service() -> ExecutiveDashboardService:
    """Dependency injection provider for ExecutiveDashboardService (singleton)."""
    return _dashboard_service_singleton()


def reset_executive_dashboard_service() -> None:
    """Reset the ExecutiveDashboardService singleton (used by tests)."""
    global _dashboard_service
    _dashboard_service = None


# ─── Module 8.1 — Compliance Risk Intelligence ───────────────────────

from app.services.compliance_risk import (  # noqa: E402
    ComplianceRiskService,
    build_default_compliance_risk_service,
)

_compliance_risk_service: "ComplianceRiskService | None" = None  # type: ignore[name-defined]


def _compliance_risk_service_singleton() -> "ComplianceRiskService":
    global _compliance_risk_service
    if _compliance_risk_service is None:
        _compliance_risk_service = build_default_compliance_risk_service()
    return _compliance_risk_service


def get_compliance_risk_service() -> ComplianceRiskService:
    """Dependency injection provider for ComplianceRiskService (singleton)."""
    return _compliance_risk_service_singleton()


def reset_compliance_risk_service() -> None:
    """Reset the ComplianceRiskService singleton (used by tests)."""
    global _compliance_risk_service
    _compliance_risk_service = None


# ─── Module 8.2 — Regulatory Recommendation Engine ──────────────────

from app.services.recommendations import (  # noqa: E402
    RecommendationService,
    build_default_recommendation_service,
)

_recommendation_service: "RecommendationService | None" = None  # type: ignore[name-defined]


def _recommendation_service_singleton() -> "RecommendationService":
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = build_default_recommendation_service()
    return _recommendation_service


def get_recommendation_service() -> RecommendationService:
    """Dependency injection provider for RecommendationService (singleton)."""
    return _recommendation_service_singleton()


def reset_recommendation_service() -> None:
    """Reset the RecommendationService singleton (used by tests)."""
    global _recommendation_service
    _recommendation_service = None


# ─── Module 8.3 — Risk Forecasting Engine ───────────────────────────

from app.services.forecasting import (  # noqa: E402
    ForecastingService,
    build_default_forecasting_service,
)

_forecasting_service: "ForecastingService | None" = None  # type: ignore[name-defined]


def _forecasting_service_singleton() -> "ForecastingService":
    global _forecasting_service
    if _forecasting_service is None:
        _forecasting_service = build_default_forecasting_service()
    return _forecasting_service


def get_forecasting_service() -> ForecastingService:
    """Dependency injection provider for ForecastingService (singleton)."""
    return _forecasting_service_singleton()


def reset_forecasting_service() -> None:
    """Reset the ForecastingService singleton (used by tests)."""
    global _forecasting_service
    _forecasting_service = None


# ─── Module 8.4 — Workflow Automation Platform ────────────────────

from app.services.workflow import (  # noqa: E402
    AutomationService,
    build_default_automation_service,
)

_automation_service: "AutomationService | None" = None  # type: ignore[name-defined]


def _automation_service_singleton() -> "AutomationService":
    global _automation_service
    if _automation_service is None:
        _automation_service = build_default_automation_service()
    return _automation_service


def get_automation_service() -> AutomationService:
    """Dependency injection provider for AutomationService (singleton)."""
    return _automation_service_singleton()


def reset_automation_service() -> None:
    """Reset the AutomationService singleton (used by tests)."""
    global _automation_service
    _automation_service = None


# ─── Module 8.5 — Human-in-the-Loop Review ─────────────────────────

from app.services.review import (  # noqa: E402
    ReviewService,
    build_default_review_service,
)

_review_service: "ReviewService | None" = None  # type: ignore[name-defined]


def _review_service_singleton() -> "ReviewService":
    global _review_service
    if _review_service is None:
        _review_service = build_default_review_service()
    return _review_service


def get_review_service() -> ReviewService:
    """Dependency injection provider for ReviewService (singleton)."""
    return _review_service_singleton()


def reset_review_service() -> None:
    """Reset the ReviewService singleton (used by tests)."""
    global _review_service
    _review_service = None


# ─── Module 8.6 — AI Governance Layer ────────────────────────

from app.services.governance import (  # noqa: E402
    GovernanceService,
    build_default_governance_service,
)

_governance_service: "GovernanceService | None" = None  # type: ignore[name-defined]


def _governance_service_singleton() -> "GovernanceService":
    global _governance_service
    if _governance_service is None:
        _governance_service = build_default_governance_service()
    return _governance_service


def get_governance_service() -> GovernanceService:
    """Dependency injection provider for GovernanceService (singleton)."""
    return _governance_service_singleton()


def reset_governance_service() -> None:
    """Reset the GovernanceService singleton (used by tests)."""
    global _governance_service
    _governance_service = None


# ─── Module 8.7 — Audit & Compliance Platform ────────────────

from app.services.audit import (  # noqa: E402
    AuditService,
    build_default_audit_service,
)

_audit_service: "AuditService | None" = None  # type: ignore[name-defined]


def _audit_service_singleton() -> "AuditService":
    global _audit_service
    if _audit_service is None:
        _audit_service = build_default_audit_service()
    return _audit_service


def get_audit_service() -> AuditService:
    """Dependency injection provider for AuditService (singleton)."""
    return _audit_service_singleton()


def reset_audit_service() -> None:
    """Reset the AuditService singleton (used by tests)."""
    global _audit_service
    _audit_service = None


# ─── Module 8.8 — Enterprise Administration Dashboard ───────

from app.services.admin import (  # noqa: E402
    AdminService,
    build_default_admin_service,
)

_admin_service: "AdminService | None" = None  # type: ignore[name-defined]


def _admin_service_singleton() -> "AdminService":
    global _admin_service
    if _admin_service is None:
        _admin_service = build_default_admin_service()
    return _admin_service


def get_admin_service() -> AdminService:
    """Dependency injection provider for AdminService (singleton)."""
    return _admin_service_singleton()


def reset_admin_service() -> None:
    """Reset the AdminService singleton (used by tests)."""
    global _admin_service
    _admin_service = None


def bind_cross_module_services() -> None:
    """Wire cross-module references after all singletons are built.

    Called from the FastAPI ``startup`` event (or from tests) so that
    the admin dashboard can pull live metrics from governance, audit,
    workflow and review.
    """
    try:
        admin = get_admin_service()
        admin.bind(
            governance_service=get_governance_service(),
            audit_service=get_audit_service(),
            workflow_service=get_automation_service(),
            review_service=get_review_service(),
        )
    except Exception:  # pragma: no cover - non-fatal
        pass


# ─── Module 9 — Multi-Agent Framework ─────────────────────

from app.services.agents import (  # noqa: E402
    AgentFrameworkService,
    build_default_agent_framework_service,
)

_agent_framework_service: "AgentFrameworkService | None" = None  # type: ignore[name-defined]


def _agent_framework_service_singleton() -> "AgentFrameworkService":
    global _agent_framework_service
    if _agent_framework_service is None:
        _agent_framework_service = build_default_agent_framework_service()
    return _agent_framework_service


def get_agent_framework_service() -> AgentFrameworkService:
    """Dependency injection provider for AgentFrameworkService (singleton)."""
    return _agent_framework_service_singleton()


def reset_agent_framework_service() -> None:
    """Reset the AgentFrameworkService singleton (used by tests)."""
    global _agent_framework_service
    _agent_framework_service = None


# ─── Module 9.4-9.6 — Intelligence Agent Layer ─────────────

from app.services.intelligence_agents import (  # noqa: E402
    IntelligenceAgentService,
    build_default_intelligence_agent_service,
)

_intelligence_agent_service: "IntelligenceAgentService | None" = None  # type: ignore[name-defined]


def _intelligence_agent_service_singleton() -> "IntelligenceAgentService":
    global _intelligence_agent_service
    if _intelligence_agent_service is None:
        _intelligence_agent_service = build_default_intelligence_agent_service()
    return _intelligence_agent_service


def get_intelligence_agent_service() -> IntelligenceAgentService:
    """Dependency injection provider for IntelligenceAgentService (singleton)."""
    return _intelligence_agent_service_singleton()


def reset_intelligence_agent_service() -> None:
    """Reset the IntelligenceAgentService singleton (used by tests)."""
    global _intelligence_agent_service
    _intelligence_agent_service = None


# ─── Module 9.7 — Audit Agent ────────────────────────────────

from app.services.audit_agent import (  # noqa: E402
    AuditAgentService,
    build_default_audit_agent_service,
)

_audit_agent_service: "AuditAgentService | None" = None  # type: ignore[name-defined]


def _audit_agent_service_singleton() -> "AuditAgentService":
    global _audit_agent_service
    if _audit_agent_service is None:
        # Wire cross-module service references lazily — these names
        # are all defined earlier in this file but only when the
        # singletons are first touched.
        audit_svc = get_audit_service() if "get_audit_service" in dir() else None
        gov_svc = get_governance_service() if "get_governance_service" in dir() else None
        kg_svc = get_knowledge_graph_service() if "get_knowledge_graph_service" in dir() else None
        cr_svc = (
            get_compliance_risk_service()
            if "get_compliance_risk_service" in dir()
            else None
        )
        rec_svc = (
            get_recommendation_service()
            if "get_recommendation_service" in dir()
            else None
        )
        _audit_agent_service = build_default_audit_agent_service(
            audit_service=audit_svc,
            governance_service=gov_svc,
            knowledge_graph_service=kg_svc,
            compliance_risk_service=cr_svc,
            recommendation_service=rec_svc,
        )
    return _audit_agent_service


def get_audit_agent_service() -> AuditAgentService:
    """Dependency injection provider for AuditAgentService (singleton)."""
    return _audit_agent_service_singleton()


def reset_audit_agent_service() -> None:
    """Reset the AuditAgentService singleton (used by tests)."""
    global _audit_agent_service
    _audit_agent_service = None


# ─── Module 9.8 — Multi-Agent Orchestration Platform ───────

from app.services.orchestration import (  # noqa: E402
    OrchestrationService,
    build_default_orchestration_service,
)

_orchestration_service: "OrchestrationService | None" = None  # type: ignore[name-defined]


def _orchestration_service_singleton() -> "OrchestrationService":
    global _orchestration_service
    if _orchestration_service is None:
        framework = get_agent_framework_service()
        _orchestration_service = build_default_orchestration_service(
            framework_service=framework
        )
    return _orchestration_service


def get_orchestration_service() -> OrchestrationService:
    """Dependency injection provider for OrchestrationService (singleton)."""
    return _orchestration_service_singleton()


def reset_orchestration_service() -> None:
    """Reset the OrchestrationService singleton (used by tests)."""
    global _orchestration_service
    _orchestration_service = None


# ─── Module 9.9 — Agent Analytics Platform ──────────────

from app.services.agent_analytics import (  # noqa: E402
    AgentAnalyticsService,
    build_default_agent_analytics_service,
)

_agent_analytics_service: "AgentAnalyticsService | None" = None  # type: ignore[name-defined]


def _agent_analytics_service_singleton() -> "AgentAnalyticsService":
    global _agent_analytics_service
    if _agent_analytics_service is None:
        framework = get_agent_framework_service()
        _agent_analytics_service = build_default_agent_analytics_service(
            framework_service=framework,
        )
    return _agent_analytics_service


def get_agent_analytics_service() -> AgentAnalyticsService:
    """Dependency injection provider for AgentAnalyticsService (singleton)."""
    return _agent_analytics_service_singleton()


def reset_agent_analytics_service() -> None:
    """Reset the AgentAnalyticsService singleton (used by tests)."""
    global _agent_analytics_service
    _agent_analytics_service = None
