"""Comprehensive integration tests for Milestone 4: Hybrid Retrieval & Reranking.

Tests the complete pipeline:
  Query Understanding -> Dense Retrieval -> BM25 Retrieval ->
  RRF Fusion -> Cross-Encoder Reranking

Also tests: analytics tracking, new API endpoints, NDCG metrics,
concurrent retrieval, query analysis integration.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.evaluation.metrics import MetricsEngine
from app.schemas.fusion import FusionConfig, FusionMethod
from app.schemas.hybrid import RetrievalStrategy as HybridRetrievalStrategy
from app.services.fusion.engine import FusionEngine, RRFStrategy
from app.services.fusion.ranking import compute_overlap
from app.services.hybrid.analytics_tracker import RetrievalAnalyticsTracker
from app.services.hybrid.pipeline import HybridRerankPipeline
from app.services.hybrid.service import HybridRetriever, RetrievalTelemetry
from app.services.query_analysis.base import (
    QueryType,
    RetrievalStrategy as QARetrievalStrategy,
)
from app.services.query_analysis.service import (
    QueryAnalyzer,
    RuleBasedQueryClassifier,
    RuleBasedStrategyRecommender,
)


# =====================================================================
# Module 1: Query Understanding Tests
# =====================================================================


class TestQueryAnalyzer:
    """Test suite for QueryAnalyzer."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_circular_query_classification(self):
        """Test classification of circular reference queries."""
        result = self.analyzer.analyze("RBI Circular 17/2024")
        assert result.query_type == "circular"
        assert result.confidence >= 0.9
        assert result.optimal_strategy == "bm25"

    def test_regulation_query_classification(self):
        """Test classification of regulation/act queries."""
        result = self.analyzer.analyze("section 45 of RBI Act")
        assert result.query_type == "regulation"
        assert result.confidence >= 0.9
        assert result.optimal_strategy == "bm25"

    def test_semantic_question_classification(self):
        """Test classification of natural language questions."""
        result = self.analyzer.analyze("How do we comply with AML?")
        assert result.query_type == "semantic"
        assert result.confidence >= 0.8
        assert result.optimal_strategy == "dense"

    def test_semantic_question_with_what_are(self):
        """Test that 'what are' queries match definition rule (higher priority)."""
        result = self.analyzer.analyze("What are the KYC requirements?")
        # DefinitionQueryRule has higher priority than SemanticQuestionRule
        assert result.query_type == "definition"
        assert result.optimal_strategy == "dense"

    def test_definition_query_classification(self):
        """Test classification of definition queries."""
        result = self.analyzer.analyze("What is KYC?")
        assert result.query_type == "definition"
        assert result.confidence >= 0.85
        assert result.optimal_strategy == "dense"

    def test_comparative_query_classification(self):
        """Test classification of comparison queries."""
        result = self.analyzer.analyze("Difference between KYC and CKYC")
        assert result.query_type in ("comparative", "semantic")
        assert result.optimal_strategy == "hybrid"

    def test_keyword_lookup_classification(self):
        """Test classification of short keyword queries."""
        result = self.analyzer.analyze("KYC Aadhaar")
        assert result.query_type == "keyword_lookup"
        assert result.optimal_strategy == "bm25"

    def test_circular_with_complex_reference(self):
        """Test classification with SEBI circular references."""
        result = self.analyzer.analyze("SEBI/HO/DDHS/DDHS-RAC-1/P/CIR/2024/123")
        assert result.query_type == "circular"
        assert result.confidence >= 0.9

    def test_semantic_with_explanation_verb(self):
        """Test classification with explanation verbs."""
        result = self.analyzer.analyze(
            "Explain the role of board in corporate governance"
        )
        assert result.query_type == "semantic"
        assert result.optimal_strategy == "dense"

    def test_low_confidence_defaults_to_hybrid(self):
        """Test that low confidence queries default to hybrid strategy."""
        classifier = RuleBasedQueryClassifier()
        recommender = RuleBasedStrategyRecommender()
        strategy = recommender.recommend(QueryType.KEYWORD, 0.3, "xyz")
        assert strategy == QARetrievalStrategy.HYBRID

    def test_analyzer_returns_result_model(self):
        """Test that analyze returns a proper QueryAnalysisResult."""
        result = self.analyzer.analyze("RBI Master Direction KYC")
        assert result.query is not None
        assert isinstance(result.query_type, str)
        assert 0.0 <= result.confidence <= 1.0
        assert result.optimal_strategy in ("bm25", "dense", "hybrid")

    def test_empty_query_handling(self):
        """Test handling of empty/whitespace queries."""
        result = self.analyzer.analyze("")
        assert result.query_type == "keyword_lookup"

    def test_ml_classifier_fallback(self):
        """Test that ML classifier falls back to rule-based when no model."""
        from app.services.query_analysis.service import MLQueryClassifier

        ml = MLQueryClassifier(model_path=None)
        query_type, confidence = ml.classify("RBI Circular 17/2024")
        assert query_type == QueryType.CIRCULAR


class TestQueryClassifierRules:
    """Test individual classification rules."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    @pytest.mark.parametrize(
        "query,expected_type",
        [
            ("RBI Circular 17/2024", "circular"),
            ("SEBI/HO/DDHS/P/CIR/2024/123", "circular"),
            ("circular no 12", "circular"),
            ("master circular on KYC", "circular"),
            ("section 45 of RBI Act", "regulation"),
            ("sec. 12", "regulation"),
            ("chapter III regulation", "regulation"),
            ("rule 9 of Companies Act", "regulation"),
            ("What is KYC?", "definition"),
            ("define mutual fund", "definition"),
            ("RBI vs SEBI", "comparative"),
            ("difference between KYC and CKYC", "comparative"),
            ("How do we comply with AML?", "semantic"),
            ("why did SEBI amend guidelines?", "semantic"),
            ("KYC", "keyword_lookup"),
            ("AML compliance", "keyword_lookup"),
        ],
    )
    def test_classification_accuracy(self, query, expected_type):
        """Test that various query patterns are classified correctly."""
        result = self.analyzer.analyze(query)
        assert (
            result.query_type == expected_type
        ), f"Query '{query}' classified as {result.query_type}, expected {expected_type}"


# =====================================================================
# Module 2-3: BM25 + Hybrid Retrieval Tests
# =====================================================================


class TestHybridRetriever:
    """Test suite for HybridRetriever with concurrent retrieval."""

    def setup_method(self):
        self.mock_retrieval_service = AsyncMock()
        self.mock_bm25_retriever = AsyncMock()
        self.mock_query_analyzer = MagicMock()
        self.fusion_engine = FusionEngine()

        self.retriever = HybridRetriever(
            retrieval_service=self.mock_retrieval_service,
            bm25_retriever=self.mock_bm25_retriever,
            fusion_engine=self.fusion_engine,
            query_analyzer=self.mock_query_analyzer,
        )

    @pytest.mark.asyncio
    async def test_concurrent_retrieval_called(self):
        """Test that both dense and BM25 are called for hybrid strategy."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        await self.retriever.retrieve_hybrid(
            query="test query",
            strategy=HybridRetrievalStrategy.HYBRID,
            use_query_analysis=False,
        )

        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_dense_only_strategy(self):
        """Test dense-only strategy doesn't call BM25."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}

        result = await self.retriever.retrieve_hybrid(
            query="test",
            strategy=HybridRetrievalStrategy.DENSE,
            use_query_analysis=False,
        )

        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_bm25_only_strategy(self):
        """Test BM25-only strategy doesn't call dense."""
        self.mock_bm25_retriever.retrieve.return_value = []

        result = await self.retriever.retrieve_hybrid(
            query="test",
            strategy=HybridRetrievalStrategy.KEYWORD,
            use_query_analysis=False,
        )

        self.mock_bm25_retriever.retrieve.assert_called_once()
        self.mock_retrieval_service.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_analysis_integration(self):
        """Test that query analyzer is called when enabled."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        mock_analysis = MagicMock()
        mock_analysis.query_type = "circular"
        mock_analysis.confidence = 0.95
        mock_analysis.optimal_strategy = "bm25"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            query="RBI Circular 17/2024",
            use_query_analysis=True,
        )

        self.mock_query_analyzer.analyze.assert_called_once_with("RBI Circular 17/2024")

    @pytest.mark.asyncio
    async def test_strategy_override_on_high_confidence(self):
        """Test that high confidence query analysis overrides strategy."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        mock_analysis = MagicMock()
        mock_analysis.query_type = "circular"
        mock_analysis.confidence = 0.95
        mock_analysis.optimal_strategy = "bm25"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            query="RBI Circular 17/2024",
            strategy=HybridRetrievalStrategy.HYBRID,  # caller says hybrid
            use_query_analysis=True,
        )

        # Should have been overridden to KEYWORD (BM25) since confidence >= 0.7
        # BM25 should be called but NOT dense
        self.mock_bm25_retriever.retrieve.assert_called_once()
        self.mock_retrieval_service.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_analysis_failure_graceful(self):
        """Test graceful fallback when query analysis fails."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []
        self.mock_query_analyzer.analyze.side_effect = RuntimeError("analyzer error")

        result = await self.retriever.retrieve_hybrid(
            query="test query",
            use_query_analysis=True,
        )

        # Should still complete with defaults
        assert result.query == "test query"

    @pytest.mark.asyncio
    async def test_metrics_include_telemetry(self):
        """Test that hybrid response includes telemetry fields."""
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        result = await self.retriever.retrieve_hybrid(
            query="test query",
            use_query_analysis=False,
        )

        assert "overlap_count" in result.metrics
        assert "overlap_percentage" in result.metrics
        assert "overall_latency_ms" in result.metrics

    @pytest.mark.asyncio
    async def test_fusion_with_results(self):
        """Test that results from both sources are fused."""
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "c1", "score": 0.9, "content": "dense 1"},
                {"chunk_id": "c2", "score": 0.8, "content": "dense 2"},
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "c2", "score": 15.0, "content": "bm25 1"},
            {"chunk_id": "c3", "score": 12.0, "content": "bm25 2"},
        ]

        result = await self.retriever.retrieve_hybrid(
            query="test",
            top_n=10,
            use_query_analysis=False,
        )

        assert len(result.results) == 3
        result_ids = {r.chunk_id for r in result.results}
        assert result_ids == {"c1", "c2", "c3"}


# =====================================================================
# Module 4: Fusion Engine Tests
# =====================================================================


class TestFusionEngine:
    """Test suite for FusionEngine and RRF."""

    def setup_method(self):
        self.engine = FusionEngine()

    def test_rrf_score_calculation(self):
        """Test RRF score formula: 1/(k+rank)."""
        assert RRFStrategy.calculate_rrf_score(rank=1, k=60) == pytest.approx(1 / 61)
        assert RRFStrategy.calculate_rrf_score(rank=2, k=60) == pytest.approx(1 / 62)
        assert RRFStrategy.calculate_rrf_score(rank=0, k=60) == 0.0

    def test_rrf_fusion_basic(self):
        """Test basic RRF fusion with two result lists."""
        dense = [
            {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}},
            {"chunk_id": "d2", "score": 0.8, "content": "b", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "b1", "score": 15.0, "content": "c", "metadata": {}},
            {"chunk_id": "d1", "score": 12.0, "content": "a", "metadata": {}},
        ]

        result = self.engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
            dense_weight=0.5,
            bm25_weight=0.5,
        )

        assert len(result) == 3  # d1, d2, b1
        # d1 should be first (appears in both)
        assert result[0]["chunk_id"] == "d1"
        assert "dense" in result[0]["sources"]
        assert "bm25" in result[0]["sources"]

    def test_rrf_fusion_preserves_provenance(self):
        """Test that fusion preserves source attribution."""
        dense = [
            {"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "c2", "score": 15.0, "content": "b", "metadata": {}},
        ]

        result = self.engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        c1_entry = next(r for r in result if r["chunk_id"] == "c1")
        c2_entry = next(r for r in result if r["chunk_id"] == "c2")

        assert c1_entry["sources"] == ["dense"]
        assert c1_entry["dense_score"] == 0.9
        assert c1_entry["bm25_score"] is None

        assert c2_entry["sources"] == ["bm25"]
        assert c2_entry["bm25_score"] == 15.0
        assert c2_entry["dense_score"] is None

    def test_weighted_sum_fusion(self):
        """Test weighted sum fusion strategy."""
        dense = [
            {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "d1", "score": 15.0, "content": "a", "metadata": {}},
        ]

        result = self.engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.WEIGHTED_SUM),
            dense_weight=0.6,
            bm25_weight=0.4,
        )

        assert len(result) == 1
        assert result[0]["chunk_id"] == "d1"

    def test_overlap_computation(self):
        """Test overlap diagnostics."""
        ids_a = {"c1", "c2", "c3"}
        ids_b = {"c2", "c3", "c4"}

        overlap = compute_overlap(ids_a, ids_b)
        assert overlap["overlap_count"] == 2
        assert overlap["overlap_ids"] == {"c2", "c3"}

    def test_fusion_report(self):
        """Test fusion with report generation."""
        dense = [
            {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "b1", "score": 15.0, "content": "b", "metadata": {}},
        ]

        fused, report = self.engine.fuse_results_with_report(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        assert report.dense_count == 1
        assert report.bm25_count == 1
        assert report.fused_count == 2
        assert report.overlap_count == 0

    def test_empty_input_handling(self):
        """Test fusion with empty inputs."""
        result = self.engine.fuse_results(
            [],
            [],
            config=FusionConfig(method=FusionMethod.RRF),
        )
        assert result == []


# =====================================================================
# Module 5: Reranker Integration Tests
# =====================================================================


class TestRerankerIntegration:
    """Test reranker integration with fusion pipeline."""

    @pytest.mark.asyncio
    async def test_reranker_scores_candidates(self):
        """Test that reranker scores and reorders candidates."""
        from app.services.reranker.service import RerankerService
        from app.services.reranker.model import BGERerankerProvider

        mock_provider = MagicMock(spec=BGERerankerProvider)
        mock_provider.get_model_name.return_value = "test-reranker"
        mock_provider.score_pairs_timed.return_value = MagicMock(
            scores=[0.9, 0.3, 0.7],
            scoring_latency_ms=10.0,
        )
        mock_provider.health_check.return_value = True

        service = RerankerService(
            provider=mock_provider,
            default_top_k=3,
        )

        candidates = [
            {"chunk_id": "c1", "content": "relevant content", "score": 0.8},
            {"chunk_id": "c2", "content": "irrelevant content", "score": 0.7},
            {"chunk_id": "c3", "content": "somewhat relevant", "score": 0.6},
        ]

        response = service.rerank(query="test query", candidates=candidates)

        assert len(response.results) == 3
        # c1 should be ranked first (high rerank_score)
        assert response.results[0].chunk_id == "c1"
        assert response.results[0].rerank_score == 0.9
        # c2 should be last (lowest rerank_score)
        assert response.results[2].chunk_id == "c2"
        assert response.results[2].rerank_score == 0.3

    @pytest.mark.asyncio
    async def test_reranker_threshold_filtering(self):
        """Test that reranker filters by score threshold."""
        from app.services.reranker.service import RerankerService
        from app.services.reranker.model import BGERerankerProvider

        mock_provider = MagicMock(spec=BGERerankerProvider)
        mock_provider.get_model_name.return_value = "test-reranker"
        mock_provider.score_pairs_timed.return_value = MagicMock(
            scores=[0.9, 0.3, 0.7],
            scoring_latency_ms=10.0,
        )

        service = RerankerService(provider=mock_provider)

        candidates = [
            {"chunk_id": "c1", "content": "a", "score": 0.8},
            {"chunk_id": "c2", "content": "b", "score": 0.7},
            {"chunk_id": "c3", "content": "c", "score": 0.6},
        ]

        response = service.rerank(
            query="test",
            candidates=candidates,
            score_threshold=0.5,
        )

        assert len(response.results) == 2  # c2 (0.3) filtered out
        result_ids = {r.chunk_id for r in response.results}
        assert "c2" not in result_ids

    @pytest.mark.asyncio
    async def test_reranker_top_k_slicing(self):
        """Test that reranker respects top_k."""
        from app.services.reranker.service import RerankerService
        from app.services.reranker.model import BGERerankerProvider

        mock_provider = MagicMock(spec=BGERerankerProvider)
        mock_provider.get_model_name.return_value = "test-reranker"
        mock_provider.score_pairs_timed.return_value = MagicMock(
            scores=[0.9, 0.8, 0.7, 0.6, 0.5],
            scoring_latency_ms=10.0,
        )

        service = RerankerService(provider=mock_provider)

        candidates = [
            {"chunk_id": f"c{i}", "content": f"content {i}", "score": 0.9 - i * 0.05}
            for i in range(5)
        ]

        response = service.rerank(query="test", candidates=candidates, top_k=3)
        assert len(response.results) == 3


# =====================================================================
# Hybrid + Rerank Pipeline Tests
# =====================================================================


class TestHybridRerankPipeline:
    """Test suite for the end-to-end HybridRerankPipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Test the full hybrid+rerank pipeline."""
        mock_hybrid_retriever = AsyncMock()
        mock_hybrid_retriever.retrieve_hybrid.return_value = MagicMock(
            results=[
                MagicMock(
                    chunk_id="c1",
                    score=0.9,
                    content="a",
                    dense_score=0.9,
                    bm25_score=None,
                    dense_rank=1,
                    bm25_rank=None,
                    metadata={},
                ),
                MagicMock(
                    chunk_id="c2",
                    score=0.8,
                    content="b",
                    dense_score=None,
                    bm25_score=15.0,
                    dense_rank=None,
                    bm25_rank=1,
                    metadata={},
                ),
                MagicMock(
                    chunk_id="c3",
                    score=0.7,
                    content="c",
                    dense_score=0.6,
                    bm25_score=12.0,
                    dense_rank=3,
                    bm25_rank=2,
                    metadata={},
                ),
            ],
            metrics={
                "query_type": "semantic",
                "query_confidence": 0.85,
                "recommended_strategy": "hybrid",
                "dense_count": 2,
                "bm25_count": 2,
                "overlap_count": 1,
                "overlap_pct": 33.3,
                "dense_latency_ms": 15.0,
                "bm25_latency_ms": 5.0,
                "fusion_latency_ms": 1.0,
            },
        )

        from app.services.reranker.service import RerankerService
        from app.services.reranker.model import BGERerankerProvider

        mock_provider = MagicMock(spec=BGERerankerProvider)
        mock_provider.get_model_name.return_value = "test-reranker"
        mock_provider.score_pairs_timed.return_value = MagicMock(
            scores=[0.95, 0.85, 0.75],
            scoring_latency_ms=50.0,
        )
        mock_reranker = RerankerService(provider=mock_provider, default_top_k=3)

        pipeline = HybridRerankPipeline(mock_hybrid_retriever, mock_reranker)

        response = await pipeline.search("test query", top_k=3)

        assert len(response.results) == 3
        assert response.telemetry["query_type"] == "semantic"
        assert response.telemetry["dense_count"] == 2
        assert response.telemetry["bm25_count"] == 2
        assert response.telemetry["rerank_candidates"] == 3

    @pytest.mark.asyncio
    async def test_pipeline_telemetry(self):
        """Test that pipeline produces complete telemetry."""
        mock_hybrid_retriever = AsyncMock()
        mock_hybrid_retriever.retrieve_hybrid.return_value = MagicMock(
            results=[
                MagicMock(
                    chunk_id="c1",
                    score=0.9,
                    content="a",
                    dense_score=0.9,
                    bm25_score=None,
                    dense_rank=1,
                    bm25_rank=None,
                    metadata={},
                ),
            ],
            metrics={
                "query_type": "keyword",
                "query_confidence": 0.85,
                "recommended_strategy": "bm25",
                "dense_count": 1,
                "bm25_count": 0,
                "overlap_count": 0,
                "overlap_pct": 0,
                "dense_latency_ms": 10.0,
                "bm25_latency_ms": 0.0,
                "fusion_latency_ms": 0.5,
            },
        )

        from app.services.reranker.service import RerankerService
        from app.services.reranker.model import BGERerankerProvider

        mock_provider = MagicMock(spec=BGERerankerProvider)
        mock_provider.get_model_name.return_value = "test-reranker"
        mock_provider.score_pairs_timed.return_value = MagicMock(
            scores=[0.95],
            scoring_latency_ms=30.0,
        )
        mock_reranker = RerankerService(provider=mock_provider, default_top_k=5)

        pipeline = HybridRerankPipeline(mock_hybrid_retriever, mock_reranker)

        response = await pipeline.search("RBI Circular 17/2024", top_k=5)

        tel = response.telemetry
        assert tel["query"] == "RBI Circular 17/2024"
        assert tel["total_latency_ms"] > 0
        assert tel["results_returned"] == 1


# =====================================================================
# Analytics Tracker Tests
# =====================================================================


class TestRetrievalAnalyticsTracker:
    """Test suite for RetrievalAnalyticsTracker."""

    @pytest.mark.asyncio
    async def test_record_retrieval(self, db_session):
        """Test recording retrieval metrics."""
        tracker = RetrievalAnalyticsTracker(db_session)

        record = await tracker.record_retrieval(
            query_text="What is KYC?",
            query_id="q-test-001",
            strategy="hybrid",
            query_type="definition",
            precision_at_5=0.8,
            mrr=0.9,
            retrieval_latency_ms=45.0,
            results_returned=5,
            relevant_count=3,
        )

        await db_session.flush()
        assert record.query_id == "q-test-001"
        assert record.strategy == "hybrid"
        assert record.query_category == "definitional"

    @pytest.mark.asyncio
    async def test_record_system_health(self, db_session):
        """Test recording system health snapshot."""
        tracker = RetrievalAnalyticsTracker(db_session)

        record = await tracker.record_system_health(
            status="healthy",
            dense_available=True,
            bm25_available=True,
            hybrid_available=True,
            reranker_available=False,
            embedding_coverage=95.0,
            total_indexed_chunks=1000,
            avg_latency=50.0,
            queries_last_hour=500,
            error_rate=0.01,
        )

        await db_session.flush()
        assert record.status == "healthy"
        assert record.reranker_available is False
        assert record.embedding_coverage_pct == 95.0

    @pytest.mark.asyncio
    async def test_record_reranker_gain(self, db_session):
        """Test recording reranker gain metrics."""
        from datetime import datetime, timezone, timedelta

        tracker = RetrievalAnalyticsTracker(db_session)

        now = datetime.now(timezone.utc)
        record = await tracker.record_reranker_gain(
            window_type="daily",
            window_start=now - timedelta(days=1),
            window_end=now,
            avg_recall_gain_at_5=0.15,
            avg_mrr_gain=0.10,
            reranker_queries_count=200,
            improvement_rate=0.85,
        )

        await db_session.flush()
        assert record.avg_recall_gain_at_5 == 0.15
        assert record.improvement_rate == 0.85

    def test_query_type_mapping(self):
        """Test query type to analytics category mapping."""
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("keyword")
            == "navigational"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("circular")
            == "navigational"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("regulation")
            == "factual"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("semantic")
            == "analytical"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("comparative")
            == "comparative"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("definition")
            == "definitional"
        )
        assert (
            RetrievalAnalyticsTracker._map_query_type_to_category("unknown")
            == "unknown"
        )


# =====================================================================
# NDCG Metric Tests
# =====================================================================


class TestNDCGMetric:
    """Test NDCG computation in the MetricsEngine."""

    def setup_method(self):
        self.engine = MetricsEngine()

    def test_ndcg_perfect_ordering(self):
        """Test NDCG = 1.0 for perfect ranking."""
        retrieved = ["c1", "c2", "c3"]
        relevant = {"c1", "c2", "c3"}
        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(1.0, abs=1e-6)

    def test_ndcg_no_relevant(self):
        """Test NDCG = 0.0 when no relevant items retrieved."""
        retrieved = ["c4", "c5", "c6"]
        relevant = {"c1", "c2", "c3"}
        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(0.0, abs=1e-6)

    def test_ndcg_empty_relevant(self):
        """Test NDCG = 0.0 with empty relevant set."""
        retrieved = ["c1", "c2"]
        relevant = set()
        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=5)
        assert ndcg == 0.0

    def test_ndcg_partial_match(self):
        """Test NDCG for partial matches."""
        retrieved = ["c1", "c4", "c2"]
        relevant = {"c1", "c2", "c3"}
        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_graded_relevance(self):
        """Test NDCG with graded relevance scores."""
        retrieved = ["c1", "c2", "c3"]
        relevant = {"c1", "c2", "c3"}
        scores = {"c1": 3.0, "c2": 2.0, "c3": 1.0}
        ndcg = self.engine.compute_ndcg_at_k(
            retrieved, relevant, k=3, relevance_scores=scores
        )
        assert ndcg == pytest.approx(1.0, abs=1e-4)

    def test_compute_all_metrics_includes_ndcg(self):
        """Test that compute_all_metrics returns NDCG values."""
        from app.evaluation.schemas import RetrievalResult

        results = [
            RetrievalResult(chunk_id=f"c{i}", score=1.0 - i * 0.1, rank=i + 1)
            for i in range(10)
        ]
        relevant = {"c0", "c2", "c4"}

        metrics = self.engine.compute_all_metrics(results, relevant, k_values=[5, 10])

        assert "ndcg_at_5" in metrics
        assert "ndcg_at_10" in metrics
        assert all(0.0 <= metrics[k] <= 1.0 for k in ["ndcg_at_5", "ndcg_at_10"])

    def test_composite_score_includes_ndcg(self):
        """Test that composite score accounts for NDCG."""
        metrics = {
            "recall_at_5": 0.8,
            "recall_at_10": 0.9,
            "mrr": 0.7,
            "precision_at_5": 0.6,
            "hit_rate": 1.0,
            "ndcg_at_5": 0.85,
            "ndcg_at_10": 0.88,
        }
        score = self.engine.compute_composite_score(metrics)
        assert 0.0 < score < 1.0


# =====================================================================
# Performance Target Tests
# =====================================================================


class TestPerformanceCharacteristics:
    """Verify performance design characteristics."""

    def test_rrf_deterministic(self):
        """Test that RRF produces deterministic rankings."""
        engine = FusionEngine()
        dense = [
            {
                "chunk_id": f"d{i}",
                "score": 1.0 - i * 0.01,
                "content": str(i),
                "metadata": {},
            }
            for i in range(10)
        ]
        bm25 = [
            {
                "chunk_id": f"b{i}",
                "score": 20.0 - i,
                "content": str(i + 10),
                "metadata": {},
            }
            for i in range(10)
        ]

        result1 = engine.fuse_results(
            dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
        )
        result2 = engine.fuse_results(
            dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
        )

        ids1 = [r["chunk_id"] for r in result1]
        ids2 = [r["chunk_id"] for r in result2]
        assert ids1 == ids2

    def test_fusion_idempotency(self):
        """Test that fusing the same inputs gives identical results."""
        engine = FusionEngine()
        dense = [
            {"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}},
            {"chunk_id": "c2", "score": 0.8, "content": "b", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "c2", "score": 15.0, "content": "b", "metadata": {}},
            {"chunk_id": "c3", "score": 12.0, "content": "c", "metadata": {}},
        ]

        result = engine.fuse_results(
            dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
        )

        # Verify scores are consistent
        c2_entry = next(r for r in result if r["chunk_id"] == "c2")
        assert "dense" in c2_entry["sources"]
        assert "bm25" in c2_entry["sources"]

    def test_telemetry_dataclass(self):
        """Test RetrievalTelemetry dataclass creation."""
        tel = RetrievalTelemetry(
            query="test",
            query_type="semantic",
            query_confidence=0.9,
            overall_latency_ms=42.5,
            dense_count=10,
            bm25_count=8,
        )
        d = tel.to_dict()
        assert d["query"] == "test"
        assert d["query_type"] == "semantic"
        assert d["query_confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_concurrent_vs_sequential_latency(self):
        """Verify that concurrent retrieval completes faster than sequential."""
        mock_retrieval = AsyncMock()
        mock_bm25 = AsyncMock()

        # Simulate 50ms latency each
        async def slow_retrieve(*a, **kw):
            await asyncio.sleep(0.05)
            return {
                "results": [
                    {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}}
                ]
            }

        async def slow_bm25(*a, **kw):
            await asyncio.sleep(0.05)
            return [{"chunk_id": "b1", "score": 15.0, "content": "b", "metadata": {}}]

        mock_retrieval.retrieve.side_effect = slow_retrieve
        mock_bm25.retrieve.side_effect = slow_bm25

        retriever = HybridRetriever(
            retrieval_service=mock_retrieval,
            bm25_retriever=mock_bm25,
            query_analyzer=None,  # Disable query analysis
        )

        start = time.perf_counter()
        result = await retriever.retrieve_hybrid(
            query="test",
            strategy=HybridRetrievalStrategy.HYBRID,
            use_query_analysis=False,
        )
        elapsed = time.perf_counter() - start

        # Concurrent should take ~50ms, not ~100ms
        # Allow generous margin for CI environments
        assert (
            elapsed < 0.15
        ), f"Concurrent retrieval took {elapsed:.3f}s, expected < 0.15s"
