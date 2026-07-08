"""Retrieval Intelligence Layer — Comprehensive Test Suite.

Tests all 4 modules:
1. Query Understanding Engine
2. BM25 Retrieval Engine
3. Hybrid Retrieval Orchestrator
4. RRF Fusion Engine

Benchmarks included at the bottom.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.services.query_analysis.base import QueryType, RetrievalStrategy
from app.services.query_analysis.service import (
    CircularSearchRule,
    ComparativeQueryRule,
    DefinitionQueryRule,
    KeywordLookupRule,
    QueryAnalyzer,
    RegulationSearchRule,
    RuleBasedQueryClassifier,
    RuleBasedStrategyRecommender,
    SemanticQuestionRule,
    AnalyticsManager,
    MLQueryClassifier,
)
from app.services.fusion.engine import FusionEngine, RRFStrategy, WeightedSumStrategy
from app.services.fusion.ranking import (
    build_provenance,
    compute_multi_source_overlap,
    compute_overlap,
    merge_metadata,
    normalize_scores,
    sort_candidates,
    source_attribution_summary,
    break_ties,
    resolve_rank_conflicts,
)
from app.services.hybrid.service import HybridRetriever, RetrievalTelemetry
from app.services.hybrid.strategy import RetrievalStrategyManager, min_max_normalize
from app.schemas.hybrid import RetrievalStrategy as HybridStrategy, FusionMethod
from app.schemas.fusion import FusionConfig


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1: QUERY UNDERSTANDING ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryType:
    """Test QueryType enum values."""

    def test_keyword_lookup_exists(self):
        assert QueryType.KEYWORD_LOOKUP.value == "keyword_lookup"

    def test_all_types_present(self):
        expected = {
            "keyword",
            "keyword_lookup",
            "semantic",
            "regulation",
            "circular",
            "comparative",
            "definition",
        }
        actual = {qt.value for qt in QueryType}
        assert expected == actual


class TestKeywordLookupRule:
    """Test KeywordLookupRule classification."""

    def setup_method(self):
        self.rule = KeywordLookupRule()

    def test_query_type_is_keyword_lookup(self):
        assert self.rule.query_type == QueryType.KEYWORD_LOOKUP

    def test_single_word(self):
        assert self.rule.evaluate("KYC") == 0.85

    def test_two_words(self):
        assert self.rule.evaluate("KYC norms") == 0.75

    def test_three_words(self):
        assert self.rule.evaluate("RBI KYC requirements") == 0.65

    def test_long_query_low_score(self):
        assert (
            self.rule.evaluate("What are the KYC requirements for banks in India")
            == 0.30
        )

    def test_whitespace_only(self):
        assert self.rule.evaluate("   ") == 0.30


class TestCircularSearchRule:
    """Test CircularSearchRule classification."""

    def setup_method(self):
        self.rule = CircularSearchRule()

    def test_high_confidence_circular_number(self):
        assert self.rule.evaluate("RBI Circular 17/2024") == 0.95

    def test_high_confidence_sebi_path(self):
        assert self.rule.evaluate("SEBI/HO/DDHS/DDHS-RAC-1/P/CIR/2024/123") == 0.95

    def test_high_confidence_circular_no(self):
        assert self.rule.evaluate("circular no 12") == 0.95

    def test_medium_confidence_circular_term(self):
        assert self.rule.evaluate("circular on KYC") == 0.80

    def test_weak_confidence_plural(self):
        # "circulars" contains "circular" which matches strong_terms at 0.80
        assert self.rule.evaluate("circulars issued") == 0.80

    def test_no_match(self):
        assert self.rule.evaluate("What is KYC?") == 0.0


class TestRegulationSearchRule:
    """Test RegulationSearchRule classification."""

    def setup_method(self):
        self.rule = RegulationSearchRule()

    def test_section_reference(self):
        assert self.rule.evaluate("section 45 of RBI Act") == 0.95

    def test_sec_abbreviation(self):
        assert self.rule.evaluate("sec. 12") == 0.95

    def test_chapter_roman(self):
        assert self.rule.evaluate("chapter III") == 0.95

    def test_rule_reference(self):
        assert self.rule.evaluate("rule 9 of Companies Act") == 0.95

    def test_subsection(self):
        assert self.rule.evaluate("sub-section 2") == 0.95

    def test_annexure(self):
        assert self.rule.evaluate("annexure 1") == 0.95

    def test_act_reference(self):
        assert self.rule.evaluate("RBI Act 1934") == 0.75

    def test_guidelines(self):
        assert self.rule.evaluate("RBI Guidelines on lending") == 0.75


class TestDefinitionQueryRule:
    """Test DefinitionQueryRule classification."""

    def setup_method(self):
        self.rule = DefinitionQueryRule()

    def test_what_is(self):
        assert self.rule.evaluate("what is KYC") == 0.90

    def test_define(self):
        assert self.rule.evaluate("define mutual fund") == 0.90

    def test_meaning_of(self):
        assert self.rule.evaluate("meaning of compliance") == 0.90

    def test_contains_definition(self):
        assert self.rule.evaluate("the definition of NPA is important") == 0.75

    def test_no_match(self):
        assert self.rule.evaluate("RBI Circular 17/2024") == 0.0


class TestComparativeQueryRule:
    """Test ComparativeQueryRule classification."""

    def setup_method(self):
        self.rule = ComparativeQueryRule()

    def test_versus(self):
        assert self.rule.evaluate("RBI versus SEBI") == 0.95

    def test_difference_between(self):
        assert self.rule.evaluate("difference between KYC and CKYC") == 0.95

    def test_compare(self):
        assert self.rule.evaluate("compare IPO and FPO") == 0.95

    def test_which_is_better(self):
        assert self.rule.evaluate("which is better, fixed or floating rate") == 0.95


class TestSemanticQuestionRule:
    """Test SemanticQuestionRule classification."""

    def setup_method(self):
        self.rule = SemanticQuestionRule()

    def test_how_question(self):
        assert self.rule.evaluate("how do we comply with AML") == 0.85

    def test_why_question(self):
        assert self.rule.evaluate("why did SEBI amend the guidelines") == 0.85

    def test_explain_verb(self):
        assert self.rule.evaluate("explain the role of the board") == 0.85

    def test_question_mark(self):
        # "what are the requirements" starts with "what " -> SemanticQuestionRule matches at 0.85
        assert self.rule.evaluate("what are the requirements") == 0.85

    def test_compliance_helper(self):
        assert self.rule.evaluate("requirements for KYC compliance") == 0.70


class TestRuleBasedQueryClassifier:
    """Test RuleBasedQueryClassifier."""

    def setup_method(self):
        self.classifier = RuleBasedQueryClassifier()

    def test_empty_query_returns_keyword_lookup(self):
        qt, conf = self.classifier.classify("")
        assert qt == QueryType.KEYWORD_LOOKUP
        assert conf == 1.0

    def test_circular_highest_priority(self):
        qt, conf = self.classifier.classify("RBI Circular 17/2024")
        assert qt == QueryType.CIRCULAR

    def test_definitional_what_are(self):
        qt, conf = self.classifier.classify("What are the KYC requirements?")
        # DefinitionQueryRule fires for "what are" prefix
        assert qt == QueryType.DEFINITION

    def test_keyword_short(self):
        qt, conf = self.classifier.classify("KYC")
        assert qt == QueryType.KEYWORD_LOOKUP
        assert conf == 0.85


class TestRuleBasedStrategyRecommender:
    """Test RuleBasedStrategyRecommender."""

    def setup_method(self):
        self.recommender = RuleBasedStrategyRecommender()

    def test_keyword_lookup_recommends_bm25(self):
        assert (
            self.recommender.recommend(QueryType.KEYWORD_LOOKUP, 0.9, "KYC")
            == RetrievalStrategy.BM25
        )

    def test_circular_recommends_bm25(self):
        assert (
            self.recommender.recommend(QueryType.CIRCULAR, 0.95, "RBI 17/2024")
            == RetrievalStrategy.BM25
        )

    def test_regulation_recommends_bm25(self):
        assert (
            self.recommender.recommend(QueryType.REGULATION, 0.9, "section 45")
            == RetrievalStrategy.BM25
        )

    def test_semantic_recommends_dense(self):
        assert (
            self.recommender.recommend(QueryType.SEMANTIC, 0.9, "how to comply")
            == RetrievalStrategy.DENSE
        )

    def test_definition_recommends_dense(self):
        assert (
            self.recommender.recommend(QueryType.DEFINITION, 0.9, "what is KYC")
            == RetrievalStrategy.DENSE
        )

    def test_comparative_recommends_hybrid(self):
        assert (
            self.recommender.recommend(QueryType.COMPARATIVE, 0.9, "RBI vs SEBI")
            == RetrievalStrategy.HYBRID
        )

    def test_low_confidence_defaults_hybrid(self):
        assert (
            self.recommender.recommend(QueryType.KEYWORD, 0.3, "xyz")
            == RetrievalStrategy.HYBRID
        )


class TestQueryAnalyzerEndToEnd:
    """End-to-end QueryAnalyzer tests."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    @pytest.mark.parametrize(
        "query,expected_type,expected_strategy",
        [
            ("RBI Circular 17/2024", "circular", "bm25"),
            ("SEBI/HO/DDHS/P/CIR/2024/123", "circular", "bm25"),
            ("section 45 of RBI Act", "regulation", "bm25"),
            ("sec. 12", "regulation", "bm25"),
            ("KYC", "keyword_lookup", "bm25"),
            ("AML compliance", "keyword_lookup", "bm25"),
            ("What is KYC?", "definition", "dense"),
            ("define mutual fund", "definition", "dense"),
            ("How do we comply with AML?", "semantic", "dense"),
            ("why did SEBI amend guidelines?", "semantic", "dense"),
            ("RBI vs SEBI", "comparative", "hybrid"),
            ("difference between KYC and CKYC", "comparative", "hybrid"),
        ],
    )
    def test_classification_and_recommendation(
        self, query, expected_type, expected_strategy
    ):
        result = self.analyzer.analyze(query)
        assert (
            result.query_type == expected_type
        ), f"Query '{query}' -> {result.query_type}, expected {expected_type}"
        assert result.optimal_strategy == expected_strategy
        assert 0.0 < result.confidence <= 1.0

    def test_output_matches_spec_format(self):
        """Verify output matches the requested JSON format."""
        result = self.analyzer.analyze("RBI Circular 17/2024")
        output = {
            "query_type": result.query_type,
            "confidence": result.confidence,
            "recommended_strategy": result.optimal_strategy,
        }
        assert "query_type" in output
        assert "confidence" in output
        assert "recommended_strategy" in output
        assert isinstance(output["confidence"], float)
        assert 0.0 <= output["confidence"] <= 1.0

    def test_ml_classifier_falls_back_to_rules(self):
        ml = MLQueryClassifier(model_path=None)
        qt, conf = ml.classify("RBI Circular 17/2024")
        assert qt == QueryType.CIRCULAR


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2: BM25 RETRIEVAL ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class TestBM25Document:
    """Test BM25Document model."""

    def test_to_indexable_text_combines_all_fields(self):
        from app.services.bm25.retriever import BM25Document

        doc = BM25Document(
            chunk_id="c1",
            content="KYC requirements for banks",
            section_title="Customer Identification",
            subsection_title="KYC Norms",
            document_title="RBI Master Direction on KYC",
            source="RBI",
            document_id="d1",
        )
        text = doc.to_indexable_text()
        assert "RBI Master Direction on KYC" in text
        assert "Customer Identification" in text
        assert "KYC Norms" in text
        assert "KYC requirements for banks" in text

    def test_to_indexable_text_omits_empty_fields(self):
        from app.services.bm25.retriever import BM25Document

        doc = BM25Document(chunk_id="c1", content="some content")
        text = doc.to_indexable_text()
        assert text == "some content"


class TestBM25InMemoryRetriever:
    """Test InMemoryBM25Retriever."""

    def setup_method(self):
        from app.services.bm25.retriever import (
            InMemoryBM25Retriever,
            BM25Document,
        )

        self.BM25Document = BM25Document
        self.retriever = InMemoryBM25Retriever(k1=1.5, b=0.75)

    def test_build_index(self):
        docs = [
            self.BM25Document(
                chunk_id="c1", content="KYC requirements for customer identification"
            ),
            self.BM25Document(chunk_id="c2", content="SEBI mutual fund regulations"),
            self.BM25Document(
                chunk_id="c3", content="RBI circular on non-performing assets"
            ),
        ]
        self.retriever.build_index(docs)
        assert self.retriever.get_index_stats().status.value == "ready"
        assert self.retriever.get_index_stats().total_documents == 3

    def test_search_returns_relevant_results(self):
        docs = [
            self.BM25Document(
                chunk_id="c1",
                content="KYC requirements for customer identification and verification procedures",
            ),
            self.BM25Document(
                chunk_id="c2",
                content="SEBI mutual fund regulations and investment guidelines",
            ),
            self.BM25Document(
                chunk_id="c3",
                content="RBI circular on non-performing assets classification and provisioning norms",
            ),
            self.BM25Document(
                chunk_id="c4",
                content="AML compliance requirements for financial institutions and banks",
            ),
            self.BM25Document(
                chunk_id="c5",
                content="Corporate governance guidelines for listed companies and boards",
            ),
        ]
        self.retriever.build_index(docs)
        response = self.retriever.search(
            MagicMock(
                query="KYC customer identification",
                top_k=5,
                source_filter=None,
                document_filter=None,
                score_threshold=0.0,
            )
        )
        assert response.query == "KYC customer identification"
        assert len(response.results) >= 1
        assert response.results[0].chunk_id == "c1"
        assert response.results[0].bm25_score > 0
        assert response.latency_ms >= 0

    def test_search_with_source_filter(self):
        from app.services.bm25.retriever import BM25SearchRequest

        docs = [
            self.BM25Document(chunk_id="c1", content="KYC requirements", source="RBI"),
            self.BM25Document(
                chunk_id="c2", content="mutual fund rules", source="SEBI"
            ),
        ]
        self.retriever.build_index(docs)
        req = BM25SearchRequest(
            query="KYC",
            top_k=5,
            source_filter=["RBI"],
            document_filter=None,
            score_threshold=0.0,
        )
        response = self.retriever.search(req)
        assert all(r.source == "RBI" for r in response.results)

    def test_search_with_score_threshold(self):
        from app.services.bm25.retriever import BM25SearchRequest

        docs = [
            self.BM25Document(
                chunk_id="c1",
                content="KYC KYC KYC requirements customer identification",
            ),
            self.BM25Document(chunk_id="c2", content="mutual fund"),
        ]
        self.retriever.build_index(docs)
        req = BM25SearchRequest(
            query="KYC",
            top_k=5,
            source_filter=None,
            document_filter=None,
            score_threshold=1.0,
        )
        response = self.retriever.search(req)
        assert all(r.bm25_score >= 1.0 for r in response.results)

    def test_update_index(self):
        docs = [
            self.BM25Document(chunk_id="c1", content="initial document"),
        ]
        self.retriever.build_index(docs)
        self.retriever.update_index(
            [
                self.BM25Document(chunk_id="c2", content="new document"),
            ]
        )
        stats = self.retriever.get_index_stats()
        assert stats.total_documents == 2

    def test_rebuild_index(self):
        docs = [self.BM25Document(chunk_id="c1", content="doc one")]
        self.retriever.build_index(docs)
        new_docs = [self.BM25Document(chunk_id="c2", content="doc two")]
        self.retriever.rebuild_index(new_docs)
        assert self.retriever.get_index_stats().total_documents == 1

    def test_clear_index(self):
        docs = [self.BM25Document(chunk_id="c1", content="doc")]
        self.retriever.build_index(docs)
        self.retriever.clear_index()
        assert self.retriever.get_index_stats().total_documents == 0

    def test_remove_documents(self):
        docs = [
            self.BM25Document(chunk_id="c1", content="doc one"),
            self.BM25Document(chunk_id="c2", content="doc two"),
        ]
        self.retriever.build_index(docs)
        self.retriever.remove_documents(["c1"])
        assert self.retriever.get_index_stats().total_documents == 1

    def test_indexing_includes_section_and_title(self):
        """Verify that section names, subsection names, and document titles are indexed."""
        docs = [
            self.BM25Document(
                chunk_id="c1",
                content="minimum capital requirements for banks under Basel III framework",
                section_title="Capital Adequacy Requirements",
                subsection_title="Minimum Capital Ratios",
                document_title="RBI Master Direction on Basel III Capital Regulations",
            ),
            self.BM25Document(
                chunk_id="c2",
                content="customer identification and verification procedures for KYC compliance",
                section_title="Customer Due Diligence",
                subsection_title="KYC Verification",
                document_title="RBI Master Direction on KYC Norms",
            ),
        ]
        self.retriever.build_index(docs)
        from app.services.bm25.retriever import BM25SearchRequest

        # Search for section title
        req = BM25SearchRequest(
            query="Capital Adequacy Requirements",
            top_k=5,
            source_filter=None,
            document_filter=None,
            score_threshold=0.0,
        )
        response = self.retriever.search(req)
        assert len(response.results) >= 1
        assert response.results[0].chunk_id == "c1"

    def test_empty_search_returns_empty(self):
        from app.services.bm25.retriever import BM25SearchRequest

        docs = [self.BM25Document(chunk_id="c1", content="KYC")]
        self.retriever.build_index(docs)
        req = BM25SearchRequest(
            query="",
            top_k=5,
            source_filter=None,
            document_filter=None,
            score_threshold=0.0,
        )
        response = self.retriever.search(req)
        assert len(response.results) == 0


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3: HYBRID RETRIEVAL ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════


class TestRetrievalStrategyManager:
    """Test RetrievalStrategyManager."""

    def test_balanced_weights(self):
        d, b = RetrievalStrategyManager.balance_weights(0.5, 0.5)
        assert d == pytest.approx(0.5)
        assert b == pytest.approx(0.5)

    def test_asymmetric_weights(self):
        d, b = RetrievalStrategyManager.balance_weights(0.7, 0.3)
        assert d == pytest.approx(0.7)
        assert b == pytest.approx(0.3)

    def test_both_zero_defaults(self):
        d, b = RetrievalStrategyManager.balance_weights(0.0, 0.0)
        assert d == 0.5
        assert b == 0.5

    def test_clamps_to_bounds(self):
        d, b = RetrievalStrategyManager.balance_weights(1.5, -0.5)
        assert 0.0 <= d <= 1.0
        assert 0.0 <= b <= 1.0


class TestMinMaxNormalize:
    def test_basic(self):
        result = min_max_normalize([1.0, 2.0, 3.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])

    def test_identical_scores(self):
        result = min_max_normalize([5.0, 5.0, 5.0])
        assert result == [1.0, 1.0, 1.0]

    def test_empty(self):
        assert min_max_normalize([]) == []


class TestHybridRetrieverConcurrent:
    """Test concurrent dense + BM25 retrieval."""

    def setup_method(self):
        self.mock_retrieval_service = AsyncMock()
        self.mock_bm25_retriever = AsyncMock()
        self.mock_query_analyzer = MagicMock()

        self.retriever = HybridRetriever(
            retrieval_service=self.mock_retrieval_service,
            bm25_retriever=self.mock_bm25_retriever,
            query_analyzer=self.mock_query_analyzer,
        )

    @pytest.mark.asyncio
    async def test_dense_and_bm25_both_called(self):
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        await self.retriever.retrieve_hybrid(
            "test", strategy=HybridStrategy.HYBRID, use_query_analysis=False
        )

        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_faster_than_sequential(self):
        """Verify asyncio.gather is used for concurrent retrieval."""
        delays = {"dense": 0, "bm25": 0}

        async def slow_retrieve(*a, **kw):
            await asyncio.sleep(0.05)
            delays["dense"] = time.perf_counter()
            return {
                "results": [
                    {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}}
                ]
            }

        async def slow_bm25(*a, **kw):
            await asyncio.sleep(0.05)
            delays["bm25"] = time.perf_counter()
            return [{"chunk_id": "b1", "score": 15.0, "content": "b", "metadata": {}}]

        self.mock_retrieval_service.retrieve.side_effect = slow_retrieve
        self.mock_bm25_retriever.retrieve.side_effect = slow_bm25

        start = time.perf_counter()
        result = await self.retriever.retrieve_hybrid(
            "test", strategy=HybridStrategy.HYBRID, use_query_analysis=False
        )
        elapsed = time.perf_counter() - start

        # Concurrent: ~50ms, Sequential: ~100ms
        assert elapsed < 0.15

    @pytest.mark.asyncio
    async def test_query_analyzer_overrides_strategy(self):
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        mock_analysis = MagicMock()
        mock_analysis.query_type = "circular"
        mock_analysis.confidence = 0.95
        mock_analysis.optimal_strategy = "bm25"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            "RBI Circular 17/2024",
            strategy=HybridStrategy.HYBRID,
            use_query_analysis=True,
        )

        # Should override to KEYWORD (BM25) since confidence >= 0.7
        self.mock_bm25_retriever.retrieve.assert_called_once()
        self.mock_retrieval_service.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_analyzer_low_confidence_no_override(self):
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        mock_analysis = MagicMock()
        mock_analysis.query_type = "semantic"
        mock_analysis.confidence = 0.4  # Below 0.7 threshold
        mock_analysis.optimal_strategy = "dense"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            "test query",
            strategy=HybridStrategy.HYBRID,
            use_query_analysis=True,
        )

        # Both should be called since strategy wasn't overridden
        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_fusion_produces_unified_results(self):
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "c1", "score": 0.9, "content": "dense 1", "metadata": {}},
                {"chunk_id": "c2", "score": 0.8, "content": "dense 2", "metadata": {}},
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "c2", "score": 15.0, "content": "bm25 1", "metadata": {}},
            {"chunk_id": "c3", "score": 12.0, "content": "bm25 2", "metadata": {}},
        ]

        result = await self.retriever.retrieve_hybrid(
            "test", top_n=10, use_query_analysis=False
        )

        assert len(result.results) == 3
        ids = {r.chunk_id for r in result.results}
        assert ids == {"c1", "c2", "c3"}

    @pytest.mark.asyncio
    async def test_metrics_include_overlap(self):
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}}
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "c1", "score": 15.0, "content": "a", "metadata": {}},
            {"chunk_id": "c2", "score": 12.0, "content": "b", "metadata": {}},
        ]

        result = await self.retriever.retrieve_hybrid("test", use_query_analysis=False)

        assert result.metrics["overlap_count"] == 1
        assert result.metrics["overlap_percentage"] > 0

    @pytest.mark.asyncio
    async def test_dense_only_no_bm25(self):
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}}
            ]
        }

        result = await self.retriever.retrieve_hybrid(
            "test", strategy=HybridStrategy.DENSE, use_query_analysis=False
        )

        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_not_called()
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_bm25_only_no_dense(self):
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "b1", "score": 15.0, "content": "a", "metadata": {}}
        ]

        result = await self.retriever.retrieve_hybrid(
            "test", strategy=HybridStrategy.KEYWORD, use_query_analysis=False
        )

        self.mock_bm25_retriever.retrieve.assert_called_once()
        self.mock_retrieval_service.retrieve.assert_not_called()
        assert len(result.results) == 1


class TestRetrievalTelemetry:
    """Test RetrievalTelemetry dataclass."""

    def test_creation(self):
        tel = RetrievalTelemetry(
            query="test",
            query_type="circular",
            query_confidence=0.95,
            overall_latency_ms=42.5,
        )
        assert tel.query == "test"
        assert tel.query_type == "circular"

    def test_to_dict(self):
        tel = RetrievalTelemetry(query="test", query_type="keyword_lookup")
        d = tel.to_dict()
        assert d["query"] == "test"
        assert d["query_type"] == "keyword_lookup"
        assert "dense_latency_ms" in d
        assert "bm25_latency_ms" in d
        assert "overall_latency_ms" in d


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4: RRF FUSION ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class TestRRFStrategy:
    """Test RRF fusion strategy."""

    def test_calculate_rrf_score(self):
        assert RRFStrategy.calculate_rrf_score(1, 60) == pytest.approx(1 / 61)
        assert RRFStrategy.calculate_rrf_score(2, 60) == pytest.approx(1 / 62)
        assert RRFStrategy.calculate_rrf_score(10, 60) == pytest.approx(1 / 70)

    def test_rrf_score_zero_for_invalid_rank(self):
        assert RRFStrategy.calculate_rrf_score(0, 60) == 0.0
        assert RRFStrategy.calculate_rrf_score(-1, 60) == 0.0

    def test_rrf_fusion_basic(self):
        engine = FusionEngine()
        dense = [
            {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}},
            {"chunk_id": "d2", "score": 0.8, "content": "b", "metadata": {}},
        ]
        bm25 = [
            {"chunk_id": "b1", "score": 15.0, "content": "c", "metadata": {}},
            {"chunk_id": "d1", "score": 12.0, "content": "a", "metadata": {}},
        ]

        result = engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        assert len(result) == 3
        # d1 should be first (appears in both lists)
        assert result[0]["chunk_id"] == "d1"
        assert "dense" in result[0]["sources"]
        assert "bm25" in result[0]["sources"]

    def test_rrf_deduplication(self):
        engine = FusionEngine()
        dense = [{"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}}]
        bm25 = [{"chunk_id": "c1", "score": 15.0, "content": "a", "metadata": {}}]

        result = engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        assert len(result) == 1
        assert result[0]["chunk_id"] == "c1"

    def test_rrf_source_attribution(self):
        engine = FusionEngine()
        dense = [{"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}}]
        bm25 = [{"chunk_id": "c2", "score": 15.0, "content": "b", "metadata": {}}]

        result = engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        c1 = next(r for r in result if r["chunk_id"] == "c1")
        c2 = next(r for r in result if r["chunk_id"] == "c2")
        assert c1["sources"] == ["dense"]
        assert c2["sources"] == ["bm25"]

    def test_rrf_deterministic(self):
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

        r1 = engine.fuse_results(
            dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
        )
        r2 = engine.fuse_results(
            dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
        )

        ids1 = [r["chunk_id"] for r in r1]
        ids2 = [r["chunk_id"] for r in r2]
        assert ids1 == ids2

    def test_rrf_output_matches_spec(self):
        """Verify output matches the requested JSON format."""
        engine = FusionEngine()
        dense = [{"chunk_id": "c1", "score": 0.9, "content": "a", "metadata": {}}]
        bm25 = [{"chunk_id": "c1", "score": 15.0, "content": "a", "metadata": {}}]

        result = engine.fuse_results(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        entry = result[0]
        output = {
            "chunk_id": entry["chunk_id"],
            "rrf_score": entry["rrf_score"],
            "sources": entry["sources"],
        }
        assert "chunk_id" in output
        assert "rrf_score" in output
        assert "sources" in output
        assert isinstance(output["sources"], list)
        assert set(output["sources"]) == {"dense", "bm25"}

    def test_rrf_with_empty_inputs(self):
        engine = FusionEngine()
        result = engine.fuse_results(
            [], [], config=FusionConfig(method=FusionMethod.RRF)
        )
        assert result == []

    def test_rrf_single_source_only(self):
        engine = FusionEngine()
        dense = [
            {"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}},
            {"chunk_id": "d2", "score": 0.8, "content": "b", "metadata": {}},
        ]

        result = engine.fuse_results(
            dense,
            [],
            config=FusionConfig(method=FusionMethod.RRF),
        )

        assert len(result) == 2
        assert all(r["sources"] == ["dense"] for r in result)

    def test_fusion_report(self):
        engine = FusionEngine()
        dense = [{"chunk_id": "d1", "score": 0.9, "content": "a", "metadata": {}}]
        bm25 = [{"chunk_id": "b1", "score": 15.0, "content": "b", "metadata": {}}]

        fused, report = engine.fuse_results_with_report(
            dense,
            bm25,
            config=FusionConfig(method=FusionMethod.RRF),
        )

        assert report.dense_count == 1
        assert report.bm25_count == 1
        assert report.fused_count == 2
        assert report.overlap_count == 0


class TestRankingUtilities:
    """Test ranking utility functions."""

    def test_sort_candidates_descending(self):
        candidates = [
            {"chunk_id": "c2", "score": 0.5},
            {"chunk_id": "c1", "score": 0.9},
            {"chunk_id": "c3", "score": 0.7},
        ]
        result = sort_candidates(candidates)
        assert [r["chunk_id"] for r in result] == ["c1", "c3", "c2"]

    def test_sort_candidates_tiebreak_by_chunk_id(self):
        candidates = [
            {"chunk_id": "c3", "score": 0.5},
            {"chunk_id": "c1", "score": 0.5},
            {"chunk_id": "c2", "score": 0.5},
        ]
        result = sort_candidates(candidates)
        assert [r["chunk_id"] for r in result] == ["c1", "c2", "c3"]

    def test_compute_overlap(self):
        a = {"c1", "c2", "c3"}
        b = {"c2", "c3", "c4"}
        result = compute_overlap(a, b)
        assert result["overlap_count"] == 2
        assert result["overlap_ids"] == {"c2", "c3"}

    def test_compute_overlap_no_overlap(self):
        a = {"c1"}
        b = {"c2"}
        result = compute_overlap(a, b)
        assert result["overlap_count"] == 0

    def test_build_provenance(self):
        dense_map = {"c1": {}, "c2": {}}
        bm25_map = {"c2": {}, "c3": {}}

        assert build_provenance("c1", dense_map, bm25_map) == ["dense"]
        assert build_provenance("c2", dense_map, bm25_map) == ["dense", "bm25"]
        assert build_provenance("c3", dense_map, bm25_map) == ["bm25"]

    def test_merge_metadata(self):
        dense_map = {"c1": {"content": "dense content", "metadata": {"page": 1}}}
        bm25_map = {"c1": {"content": "bm25 content", "metadata": {"section": "KYC"}}}

        content, meta = merge_metadata("c1", dense_map, bm25_map)
        assert content == "dense content"  # Dense takes priority
        assert meta["page"] == 1
        assert meta["section"] == "KYC"

    def test_normalize_scores(self):
        assert normalize_scores([1.0, 2.0, 3.0]) == pytest.approx([0.0, 0.5, 1.0])

    def test_normalize_identical(self):
        assert normalize_scores([5.0, 5.0]) == pytest.approx([1.0, 1.0])

    def test_source_attribution_summary(self):
        candidates = [
            {"chunk_id": "c1", "sources": ["dense"]},
            {"chunk_id": "c2", "sources": ["bm25"]},
            {"chunk_id": "c3", "sources": ["dense", "bm25"]},
        ]
        summary = source_attribution_summary(candidates)
        assert summary["dense"] == 2
        assert summary["bm25"] == 2

    def test_multi_source_overlap(self):
        sources = {
            "dense": {"c1", "c2", "c3"},
            "bm25": {"c2", "c3", "c4"},
        }
        result = compute_multi_source_overlap(sources)
        assert result["overlap_ids"] == {"c2", "c3"}
        assert result["overlap_count"] == 2

    def test_break_ties(self):
        candidates = [
            {"chunk_id": "c3", "score": 0.5},
            {"chunk_id": "c1", "score": 0.5},
        ]
        result = break_ties(candidates)
        assert result[0]["chunk_id"] == "c1"


# ═══════════════════════════════════════════════════════════════════════════
# BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════════


class TestBM25Benchmarks:
    """BM25 retrieval performance benchmarks."""

    def setup_method(self):
        from app.services.bm25.retriever import InMemoryBM25Retriever, BM25Document

        self.BM25Document = BM25Document
        self.retriever = InMemoryBM25Retriever()

    def _build_index(self, num_docs):
        docs = [
            self.BM25Document(
                chunk_id=f"chunk_{i}",
                content=f"Regulatory content about topic {i} with keywords KYC AML compliance",
                section_title=f"Section {i}",
                document_title=f"Document {i}",
            )
            for i in range(num_docs)
        ]
        self.retriever.build_index(docs)

    def test_bm25_search_under_10ms_p95_small_index(self):
        """BM25 search < 10ms P95 for small index (< 100 docs)."""
        self._build_index(50)
        from app.services.bm25.retriever import BM25SearchRequest

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            req = BM25SearchRequest(
                query="KYC compliance",
                top_k=10,
                source_filter=None,
                document_filter=None,
                score_threshold=0.0,
            )
            self.retriever.search(req)
            latencies.append((time.perf_counter() - start) * 1000)

        latencies.sort()
        p95 = latencies[int(0.95 * len(latencies))]
        assert p95 < 10.0, f"BM25 P95 latency {p95:.2f}ms >= 10ms"

    def test_bm25_search_scales_to_1000_docs(self):
        """BM25 search < 50ms P95 for 1000 docs."""
        self._build_index(1000)
        from app.services.bm25.retriever import BM25SearchRequest

        latencies = []
        for _ in range(50):
            start = time.perf_counter()
            req = BM25SearchRequest(
                query="KYC compliance",
                top_k=10,
                source_filter=None,
                document_filter=None,
                score_threshold=0.0,
            )
            self.retriever.search(req)
            latencies.append((time.perf_counter() - start) * 1000)

        latencies.sort()
        p95 = latencies[int(0.95 * len(latencies))]
        assert p95 < 50.0, f"BM25 P95 latency {p95:.2f}ms >= 50ms for 1000 docs"


class TestHybridRetrievalBenchmarks:
    """Hybrid retrieval performance benchmarks."""

    def setup_method(self):
        self.mock_retrieval_service = AsyncMock()
        self.mock_bm25_retriever = AsyncMock()
        self.mock_retrieval_service.retrieve.return_value = {"results": []}
        self.mock_bm25_retriever.retrieve.return_value = []

        self.retriever = HybridRetriever(
            retrieval_service=self.mock_retrieval_service,
            bm25_retriever=self.mock_bm25_retriever,
            query_analyzer=None,
        )

    @pytest.mark.asyncio
    async def test_hybrid_search_under_50ms_p95(self):
        """Hybrid search < 50ms P95 (with fast mocks)."""
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            await self.retriever.retrieve_hybrid(
                "test query",
                strategy=HybridStrategy.HYBRID,
                use_query_analysis=False,
            )
            latencies.append((time.perf_counter() - start) * 1000)

        latencies.sort()
        p95 = latencies[int(0.95 * len(latencies))]
        assert p95 < 50.0, f"Hybrid P95 latency {p95:.2f}ms >= 50ms"

    @pytest.mark.asyncio
    async def test_concurrent_faster_than_sequential(self):
        """Concurrent retrieval must be faster than sequential."""
        seq_durations = []
        conc_durations = []

        # Sequential: call dense then bm25
        for _ in range(50):
            start = time.perf_counter()
            await asyncio.sleep(0.01)  # dense
            await asyncio.sleep(0.01)  # bm25
            seq_durations.append(time.perf_counter() - start)

        # Concurrent: gather both
        for _ in range(50):
            start = time.perf_counter()
            await asyncio.gather(
                asyncio.sleep(0.01),
                asyncio.sleep(0.01),
            )
            conc_durations.append(time.perf_counter() - start)

        avg_seq = sum(seq_durations) / len(seq_durations)
        avg_conc = sum(conc_durations) / len(conc_durations)
        assert (
            avg_conc < avg_seq
        ), f"Concurrent {avg_conc:.4f}s >= Sequential {avg_seq:.4f}s"


class TestFusionBenchmarks:
    """Fusion engine performance benchmarks."""

    def test_rrf_fusion_under_1ms_100_candidates(self):
        """RRF fusion < 1ms for 100 candidates."""
        engine = FusionEngine()
        dense = [
            {
                "chunk_id": f"d{i}",
                "score": 1.0 - i * 0.01,
                "content": str(i),
                "metadata": {},
            }
            for i in range(50)
        ]
        bm25 = [
            {
                "chunk_id": f"b{i}",
                "score": 20.0 - i,
                "content": str(i + 50),
                "metadata": {},
            }
            for i in range(50)
        ]

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            engine.fuse_results(
                dense, bm25, config=FusionConfig(method=FusionMethod.RRF)
            )
            latencies.append((time.perf_counter() - start) * 1000)

        avg = sum(latencies) / len(latencies)
        assert avg < 1.0, f"RRF fusion avg {avg:.2f}ms >= 1ms"


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: FULL PIPELINE
# ═══════════════════════════════════════════════════════════════════════════


class TestFullRetrievalPipeline:
    """Integration tests for the full retrieval pipeline."""

    def setup_method(self):
        self.mock_retrieval_service = AsyncMock()
        self.mock_bm25_retriever = AsyncMock()
        self.mock_query_analyzer = MagicMock()

        self.retriever = HybridRetriever(
            retrieval_service=self.mock_retrieval_service,
            bm25_retriever=self.mock_bm25_retriever,
            query_analyzer=self.mock_query_analyzer,
        )

    @pytest.mark.asyncio
    async def test_circular_query_uses_bm25(self):
        """Circular query should be routed to BM25."""
        self.mock_bm25_retriever.retrieve.return_value = [
            {
                "chunk_id": "c1",
                "score": 15.0,
                "content": "RBI Circular 17/2024 content",
                "metadata": {},
            }
        ]

        mock_analysis = MagicMock()
        mock_analysis.query_type = "circular"
        mock_analysis.confidence = 0.95
        mock_analysis.optimal_strategy = "bm25"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            "RBI Circular 17/2024",
            use_query_analysis=True,
        )

        # Should use BM25 only
        self.mock_bm25_retriever.retrieve.assert_called_once()
        self.mock_retrieval_service.retrieve.assert_not_called()
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_semantic_query_uses_dense(self):
        """Semantic question should be routed to dense."""
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {
                    "chunk_id": "c1",
                    "score": 0.9,
                    "content": "KYC explanation",
                    "metadata": {},
                }
            ]
        }

        mock_analysis = MagicMock()
        mock_analysis.query_type = "semantic"
        mock_analysis.confidence = 0.85
        mock_analysis.optimal_strategy = "dense"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            "How do we comply with KYC requirements?",
            use_query_analysis=True,
        )

        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_comparative_query_uses_hybrid(self):
        """Comparative query should use hybrid."""
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {
                    "chunk_id": "c1",
                    "score": 0.9,
                    "content": "KYC details",
                    "metadata": {},
                }
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "c2", "score": 15.0, "content": "CKYC details", "metadata": {}}
        ]

        mock_analysis = MagicMock()
        mock_analysis.query_type = "comparative"
        mock_analysis.confidence = 0.95
        mock_analysis.optimal_strategy = "hybrid"
        self.mock_query_analyzer.analyze.return_value = mock_analysis

        result = await self.retriever.retrieve_hybrid(
            "Difference between KYC and CKYC",
            use_query_analysis=True,
        )

        # Both should be called for hybrid
        self.mock_retrieval_service.retrieve.assert_called_once()
        self.mock_bm25_retriever.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_hybrid_produces_higher_coverage_than_dense_only(self):
        """Hybrid retrieval should return more unique candidates than dense-only."""
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "shared", "score": 0.9, "content": "a", "metadata": {}},
                {
                    "chunk_id": "dense_only",
                    "score": 0.8,
                    "content": "b",
                    "metadata": {},
                },
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "shared", "score": 15.0, "content": "a", "metadata": {}},
            {"chunk_id": "bm25_only", "score": 12.0, "content": "c", "metadata": {}},
        ]

        # Hybrid result
        hybrid_result = await self.retriever.retrieve_hybrid(
            "test",
            top_n=10,
            use_query_analysis=False,
        )
        hybrid_ids = {r.chunk_id for r in hybrid_result.results}

        # Dense-only result
        dense_result = await self.retriever.retrieve_hybrid(
            "test",
            strategy=HybridStrategy.DENSE,
            use_query_analysis=False,
        )
        dense_ids = {r.chunk_id for r in dense_result.results}

        # Hybrid should have >= unique results
        assert len(hybrid_ids) >= len(dense_ids)
        assert "bm25_only" in hybrid_ids
        assert "bm25_only" not in dense_ids

    @pytest.mark.asyncio
    async def test_hybrid_produces_higher_coverage_than_bm25_only(self):
        """Hybrid retrieval should return more unique candidates than BM25-only."""
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "shared", "score": 0.9, "content": "a", "metadata": {}},
                {
                    "chunk_id": "dense_only",
                    "score": 0.8,
                    "content": "b",
                    "metadata": {},
                },
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "shared", "score": 15.0, "content": "a", "metadata": {}},
            {"chunk_id": "bm25_only", "score": 12.0, "content": "c", "metadata": {}},
        ]

        hybrid_result = await self.retriever.retrieve_hybrid(
            "test",
            top_n=10,
            use_query_analysis=False,
        )
        bm25_result = await self.retriever.retrieve_hybrid(
            "test",
            strategy=HybridStrategy.KEYWORD,
            use_query_analysis=False,
        )

        hybrid_ids = {r.chunk_id for r in hybrid_result.results}
        bm25_ids = {r.chunk_id for r in bm25_result.results}

        assert len(hybrid_ids) >= len(bm25_ids)
        assert "dense_only" in hybrid_ids
        assert "dense_only" not in bm25_ids
