import pytest
import os
import json
import tempfile
from app.services.query_analysis.base import (
    QueryType,
    RetrievalStrategy,
    ClassificationRule,
    QueryClassifier,
    StrategyRecommender,
)
from app.services.query_analysis.service import (
    QueryAnalyzer,
    RuleBasedQueryClassifier,
    RuleBasedStrategyRecommender,
    MLQueryClassifier,
    AnalyticsManager,
    CircularSearchRule,
    RegulationSearchRule,
    DefinitionQueryRule,
    ComparativeQueryRule,
    SemanticQuestionRule,
    KeywordLookupRule,
)


# =============================================================================
# Individual Rule Tests
# =============================================================================

class TestCircularSearchRule:
    """Tests for CircularSearchRule."""

    def setup_method(self):
        self.rule = CircularSearchRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.CIRCULAR

    def test_circular_with_year_pattern(self):
        assert self.rule.evaluate("RBI Circular 17/2024") > 0.9

    def test_circular_no_format(self):
        assert self.rule.evaluate("circular no 12") > 0.9

    def test_circular_no_with_period(self):
        assert self.rule.evaluate("circular no. 12") > 0.9

    def test_notification_no_format(self):
        assert self.rule.evaluate("notification no 5") > 0.9

    def test_sebi_notification(self):
        assert self.rule.evaluate("SEBI Notification") > 0.7

    def test_master_circular(self):
        assert self.rule.evaluate("master circular on KYC") > 0.7

    def test_master_direction(self):
        assert self.rule.evaluate("master direction on lending") > 0.7

    def test_sebi_ho_path(self):
        assert self.rule.evaluate("SEBI/HO/DDHS/P/CIR/2024/123") > 0.9

    def test_rbi_year_path(self):
        assert self.rule.evaluate("rbi/2024") > 0.9

    def test_date_slash_pattern(self):
        assert self.rule.evaluate("2024/12/001") > 0.9

    def test_fiscal_year_pattern(self):
        assert self.rule.evaluate("2024-25/123") > 0.9

    def test_normal_search_returns_zero(self):
        assert self.rule.evaluate("normal search") == 0.0

    def test_empty_query(self):
        assert self.rule.evaluate("") == 0.0


class TestRegulationSearchRule:
    """Tests for RegulationSearchRule."""

    def setup_method(self):
        self.rule = RegulationSearchRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.REGULATION

    def test_section_with_number(self):
        assert self.rule.evaluate("section 45 of RBI Act") > 0.9

    def test_section_with_letter(self):
        assert self.rule.evaluate("section 12A") > 0.9

    def test_sec_abbreviation(self):
        assert self.rule.evaluate("sec. 12") > 0.9

    def test_sec_no_period(self):
        assert self.rule.evaluate("sec 45") > 0.9

    def test_clause_reference(self):
        assert self.rule.evaluate("clause 4") > 0.9

    def test_rule_reference(self):
        assert self.rule.evaluate("rule 9") > 0.9

    def test_chapter_roman(self):
        assert self.rule.evaluate("chapter III") > 0.9

    def test_chapter_number(self):
        assert self.rule.evaluate("chapter 3") > 0.9

    def test_sub_section(self):
        assert self.rule.evaluate("sub-section 2") > 0.9

    def test_sub_clause(self):
        assert self.rule.evaluate("sub-clause 1") > 0.9

    def test_schedule(self):
        assert self.rule.evaluate("schedule III") > 0.9

    def test_part(self):
        assert self.rule.evaluate("part A") > 0.9

    def test_annexure(self):
        assert self.rule.evaluate("annexure 1") > 0.9

    def test_regulation_number(self):
        assert self.rule.evaluate("regulation 12") > 0.9

    def test_sebi_regulations(self):
        assert self.rule.evaluate("SEBI Regulations") > 0.7

    def test_rbi_act(self):
        assert self.rule.evaluate("RBI Act") > 0.7

    def test_guidelines(self):
        assert self.rule.evaluate("RBI Guidelines") > 0.7

    def test_directions(self):
        assert self.rule.evaluate("RBI Directions") > 0.7

    def test_framework(self):
        assert self.rule.evaluate("regulatory framework") > 0.7

    def test_what_is_returns_zero(self):
        assert self.rule.evaluate("what is that") == 0.0


class TestDefinitionQueryRule:
    """Tests for DefinitionQueryRule."""

    def setup_method(self):
        self.rule = DefinitionQueryRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.DEFINITION

    def test_what_is(self):
        assert self.rule.evaluate("what is KYC diligence") > 0.8

    def test_what_are(self):
        assert self.rule.evaluate("what are the requirements") > 0.8

    def test_what_does(self):
        assert self.rule.evaluate("what does AML mean") > 0.8

    def test_define(self):
        assert self.rule.evaluate("define mutual fund") > 0.8

    def test_definition_of(self):
        assert self.rule.evaluate("definition of compliance") > 0.7

    def test_meaning_of(self):
        assert self.rule.evaluate("meaning of compliance") > 0.8

    def test_meaning(self):
        assert self.rule.evaluate("meaning diligence") > 0.7

    def test_stands_for(self):
        assert self.rule.evaluate("stands for AML") > 0.8

    def test_abbreviation_of(self):
        assert self.rule.evaluate("abbreviation of KYC") > 0.8

    def test_full_form_of(self):
        assert self.rule.evaluate("full form of IPO") > 0.8

    def test_expand(self):
        assert self.rule.evaluate("expand AML") > 0.8

    def test_explain_what(self):
        assert self.rule.evaluate("explain what is KYC") > 0.8

    def test_rbi_circular_returns_zero(self):
        assert self.rule.evaluate("RBI Circular") == 0.0


class TestComparativeQueryRule:
    """Tests for ComparativeQueryRule."""

    def setup_method(self):
        self.rule = ComparativeQueryRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.COMPARATIVE

    def test_vs(self):
        assert self.rule.evaluate("RBI vs SEBI") > 0.9

    def test_vs_with_period(self):
        assert self.rule.evaluate("RBI vs. SEBI") > 0.9

    def test_versus(self):
        assert self.rule.evaluate("mutual fund versus equity") > 0.9

    def test_difference_between(self):
        assert self.rule.evaluate("difference between KYC and diligence") > 0.9

    def test_differences_between(self):
        assert self.rule.evaluate("differences between IPO and FPO") > 0.9

    def test_compare(self):
        assert self.rule.evaluate("compare IPO and FPO") > 0.9

    def test_comparison(self):
        assert self.rule.evaluate("comparison of debt and equity") > 0.9

    def test_comparing(self):
        assert self.rule.evaluate("comparing mutual funds and stocks") > 0.9

    def test_different_from(self):
        assert self.rule.evaluate("different from equity") > 0.9

    def test_distinction_between(self):
        assert self.rule.evaluate("distinction between KYC and AML") > 0.9

    def test_distinguish_between(self):
        assert self.rule.evaluate("distinguish between IPO and FPO") > 0.9

    def test_contrast_between(self):
        assert self.rule.evaluate("contrast between debt and equity") > 0.9

    def test_pros_and_cons(self):
        assert self.rule.evaluate("pros and cons of mutual funds") > 0.9

    def test_advantages_and_disadvantages(self):
        assert self.rule.evaluate("advantages and disadvantages of IPO") > 0.9

    def test_which_is_better(self):
        assert self.rule.evaluate("which is better mutual fund or FD") > 0.9

    def test_what_is_returns_zero(self):
        assert self.rule.evaluate("what is KYC") == 0.0


class TestSemanticQuestionRule:
    """Tests for SemanticQuestionRule."""

    def setup_method(self):
        self.rule = SemanticQuestionRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.SEMANTIC

    def test_how_do(self):
        assert self.rule.evaluate("how do we comply with AML?") > 0.8

    def test_how_does(self):
        assert self.rule.evaluate("how does KYC work?") > 0.8

    def test_how_can(self):
        assert self.rule.evaluate("how can we verify identity?") > 0.8

    def test_how_should(self):
        assert self.rule.evaluate("how should we file returns?") > 0.8

    def test_how_to(self):
        assert self.rule.evaluate("how to apply for PAN") > 0.8

    def test_why_did(self):
        assert self.rule.evaluate("why did SEBI amend guidelines?") > 0.8

    def test_why_is(self):
        assert self.rule.evaluate("why is KYC required?") > 0.8

    def test_who(self):
        assert self.rule.evaluate("who regulates mutual funds?") > 0.8

    def test_where(self):
        assert self.rule.evaluate("where to file complaint?") > 0.8

    def test_when(self):
        assert self.rule.evaluate("when is the filing deadline?") > 0.8

    def test_what_changed(self):
        assert self.rule.evaluate("what changed in KYC requirements?") > 0.8

    def test_which(self):
        assert self.rule.evaluate("which documents are required?") > 0.8

    def test_explain(self):
        assert self.rule.evaluate("explain the role of board") > 0.8

    def test_describe(self):
        assert self.rule.evaluate("describe the compliance process") > 0.8

    def test_elaborate(self):
        assert self.rule.evaluate("elaborate on KYC norms") > 0.8

    def test_clarify(self):
        assert self.rule.evaluate("clarify the amendment") > 0.8

    def test_summarize(self):
        assert self.rule.evaluate("summarize the circular") > 0.8

    def test_outline(self):
        assert self.rule.evaluate("outline the requirements") > 0.8

    def test_question_mark(self):
        assert self.rule.evaluate("is this compliant?") > 0.7

    def test_impact_of(self):
        assert self.rule.evaluate("impact of circular") > 0.6

    def test_requirements_for(self):
        assert self.rule.evaluate("requirements for KYC") > 0.6

    def test_compliance_with(self):
        assert self.rule.evaluate("compliance with AML") > 0.6

    def test_amendment(self):
        assert self.rule.evaluate("latest amendment to regulations") > 0.6

    def test_update(self):
        assert self.rule.evaluate("update on SEBI guidelines") > 0.6

    def test_process_for(self):
        assert self.rule.evaluate("process for incorporation") > 0.6

    def test_tell_me_about(self):
        assert self.rule.evaluate("tell me about KYC") > 0.6

    def test_help_me_understand(self):
        assert self.rule.evaluate("help me understand compliance") > 0.6

    def test_aadhaar_pan_returns_zero(self):
        assert self.rule.evaluate("Aadhaar PAN") == 0.0


class TestKeywordLookupRule:
    """Tests for KeywordLookupRule."""

    def setup_method(self):
        self.rule = KeywordLookupRule()

    def test_query_type(self):
        assert self.rule.query_type == QueryType.KEYWORD

    def test_single_word(self):
        assert self.rule.evaluate("KYC") > 0.8

    def test_two_words(self):
        assert self.rule.evaluate("KYC Aadhaar") > 0.7

    def test_three_words(self):
        assert self.rule.evaluate("KYC Aadhaar PAN") > 0.5

    def test_long_query_low_score(self):
        assert self.rule.evaluate("this is a very long keyword query that is not standard") < 0.4


# =============================================================================
# Classifier Tests
# =============================================================================

class TestRuleBasedQueryClassifier:
    """Tests for RuleBasedQueryClassifier."""

    def setup_method(self):
        self.classifier = RuleBasedQueryClassifier()

    def test_circular_classification(self):
        qtype, conf = self.classifier.classify("RBI Circular 17/2024")
        assert qtype == QueryType.CIRCULAR
        assert conf > 0.9

    def test_definition_classification(self):
        qtype, conf = self.classifier.classify("define compliance")
        assert qtype == QueryType.DEFINITION
        assert conf > 0.8

    def test_comparative_classification(self):
        qtype, conf = self.classifier.classify("mutual fund vs stock")
        assert qtype == QueryType.COMPARATIVE
        assert conf > 0.9

    def test_regulation_classification(self):
        qtype, conf = self.classifier.classify("section 45 of RBI Act")
        assert qtype == QueryType.REGULATION
        assert conf > 0.9

    def test_semantic_classification(self):
        qtype, conf = self.classifier.classify("how do we comply with AML?")
        assert qtype == QueryType.SEMANTIC
        assert conf > 0.8

    def test_keyword_classification(self):
        qtype, conf = self.classifier.classify("KYC")
        assert qtype == QueryType.KEYWORD
        assert conf > 0.8

    def test_empty_query(self):
        qtype, conf = self.classifier.classify("")
        assert qtype == QueryType.KEYWORD
        assert conf == 1.0

    def test_whitespace_query(self):
        qtype, conf = self.classifier.classify("   ")
        assert qtype == QueryType.KEYWORD
        assert conf == 1.0

    def test_custom_rules(self):
        """Test that custom rules can be injected."""
        custom_rule = CircularSearchRule()
        classifier = RuleBasedQueryClassifier(rules=[custom_rule])
        qtype, conf = classifier.classify("RBI Circular 17/2024")
        assert qtype == QueryType.CIRCULAR
        assert conf > 0.9

    def test_no_rules_match(self):
        """Test fallback when no rules match.

        For a long query with no matching patterns, the KeywordLookupRule
        returns 0.3 (low baseline for long queries), which becomes the
        best score since no other rules match.
        """
        qtype, conf = self.classifier.classify("xyz abc def ghi jkl")
        assert qtype == QueryType.KEYWORD
        assert conf == 0.3


class TestMLQueryClassifier:
    """Tests for MLQueryClassifier (fallback behavior)."""

    def test_fallback_without_model(self):
        """Without a model, should fall back to rule-based."""
        classifier = MLQueryClassifier(model_path=None)
        qtype, conf = classifier.classify("RBI Circular 17/2024")
        assert qtype == QueryType.CIRCULAR
        assert conf > 0.9

    def test_fallback_with_invalid_path(self):
        """With an invalid model path, should fall back to rule-based."""
        classifier = MLQueryClassifier(model_path="/nonexistent/path")
        qtype, conf = classifier.classify("define compliance")
        assert qtype == QueryType.DEFINITION
        assert conf > 0.8

    def test_custom_fallback_classifier(self):
        """Test that a custom fallback classifier can be injected."""
        fallback = RuleBasedQueryClassifier()
        classifier = MLQueryClassifier(
            model_path=None,
            fallback_classifier=fallback,
        )
        qtype, conf = classifier.classify("mutual fund vs stock")
        assert qtype == QueryType.COMPARATIVE
        assert conf > 0.9


# =============================================================================
# Strategy Recommender Tests
# =============================================================================

class TestRuleBasedStrategyRecommender:
    """Tests for RuleBasedStrategyRecommender."""

    def setup_method(self):
        self.recommender = RuleBasedStrategyRecommender()

    def test_circular_recommends_bm25(self):
        strategy = self.recommender.recommend(QueryType.CIRCULAR, 0.95, "RBI Circular 17/2024")
        assert strategy == RetrievalStrategy.BM25

    def test_regulation_recommends_bm25(self):
        strategy = self.recommender.recommend(QueryType.REGULATION, 0.95, "section 45")
        assert strategy == RetrievalStrategy.BM25

    def test_keyword_recommends_bm25(self):
        strategy = self.recommender.recommend(QueryType.KEYWORD, 0.85, "KYC")
        assert strategy == RetrievalStrategy.BM25

    def test_semantic_recommends_dense(self):
        strategy = self.recommender.recommend(QueryType.SEMANTIC, 0.85, "how to comply?")
        assert strategy == RetrievalStrategy.DENSE

    def test_definition_recommends_dense(self):
        strategy = self.recommender.recommend(QueryType.DEFINITION, 0.90, "what is KYC")
        assert strategy == RetrievalStrategy.DENSE

    def test_comparative_recommends_hybrid(self):
        strategy = self.recommender.recommend(QueryType.COMPARATIVE, 0.95, "RBI vs SEBI")
        assert strategy == RetrievalStrategy.HYBRID

    def test_low_confidence_recommends_hybrid(self):
        """Low confidence should always recommend hybrid."""
        strategy = self.recommender.recommend(QueryType.CIRCULAR, 0.3, "something vague")
        assert strategy == RetrievalStrategy.HYBRID

    def test_medium_confidence_type_based(self):
        """Medium confidence should still use type-based routing."""
        strategy = self.recommender.recommend(QueryType.CIRCULAR, 0.6, "circular on KYC")
        assert strategy == RetrievalStrategy.BM25

    def test_boundary_confidence(self):
        """Test at the confidence threshold boundary."""
        strategy = self.recommender.recommend(QueryType.KEYWORD, 0.5, "KYC")
        assert strategy == RetrievalStrategy.BM25

    def test_just_below_threshold(self):
        """Test just below the confidence threshold."""
        strategy = self.recommender.recommend(QueryType.KEYWORD, 0.49, "KYC")
        assert strategy == RetrievalStrategy.HYBRID


# =============================================================================
# Analytics Manager Tests
# =============================================================================

class TestAnalyticsManager:
    """Tests for AnalyticsManager."""

    def test_log_and_retrieve(self, tmp_path):
        analytics = AnalyticsManager(analytics_dir=str(tmp_path))

        from app.schemas.query_analysis import QueryAnalysisResult
        result = QueryAnalysisResult(
            query="RBI Circular 17/2024",
            query_type="circular",
            confidence=0.95,
            optimal_strategy="bm25",
        )
        analytics.log_analysis(result)

        records = analytics.get_recent_analyses()
        assert len(records) == 1
        assert records[0]["query"] == "RBI Circular 17/2024"
        assert records[0]["query_type"] == "circular"
        assert records[0]["confidence"] == 0.95
        assert records[0]["optimal_strategy"] == "bm25"
        assert "timestamp" in records[0]

    def test_multiple_logs(self, tmp_path):
        analytics = AnalyticsManager(analytics_dir=str(tmp_path))

        from app.schemas.query_analysis import QueryAnalysisResult
        for i in range(5):
            result = QueryAnalysisResult(
                query=f"query {i}",
                query_type="semantic",
                confidence=0.8,
                optimal_strategy="dense",
            )
            analytics.log_analysis(result)

        records = analytics.get_recent_analyses()
        assert len(records) == 5

    def test_get_recent_with_limit(self, tmp_path):
        analytics = AnalyticsManager(analytics_dir=str(tmp_path))

        from app.schemas.query_analysis import QueryAnalysisResult
        for i in range(10):
            result = QueryAnalysisResult(
                query=f"query {i}",
                query_type="keyword",
                confidence=0.7,
                optimal_strategy="bm25",
            )
            analytics.log_analysis(result)

        records = analytics.get_recent_analyses(limit=3)
        assert len(records) == 3

    def test_get_recent_empty(self, tmp_path):
        analytics = AnalyticsManager(analytics_dir=str(tmp_path))
        records = analytics.get_recent_analyses()
        assert records == []

    def test_log_file_format(self, tmp_path):
        analytics = AnalyticsManager(analytics_dir=str(tmp_path))

        from app.schemas.query_analysis import QueryAnalysisResult
        result = QueryAnalysisResult(
            query="test query",
            query_type="definition",
            confidence=0.9,
            optimal_strategy="dense",
        )
        analytics.log_analysis(result)

        log_file = os.path.join(tmp_path, "query_analyses.jsonl")
        assert os.path.exists(log_file)

        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["query"] == "test query"
        assert record["query_type"] == "definition"


# =============================================================================
# Query Analyzer Integration Tests
# =============================================================================

class TestQueryAnalyzer:
    """Integration tests for QueryAnalyzer."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analytics = AnalyticsManager(analytics_dir=self.tmp_dir)
        self.analyzer = QueryAnalyzer(analytics=self.analytics)

    def test_circular_query(self):
        result = self.analyzer.analyze("RBI Circular 17/2024")
        assert result.query_type == "circular"
        assert result.confidence > 0.9
        assert result.optimal_strategy == "bm25"

    def test_regulation_query(self):
        result = self.analyzer.analyze("section 45 of RBI Act")
        assert result.query_type == "regulation"
        assert result.confidence > 0.9
        assert result.optimal_strategy == "bm25"

    def test_definition_query(self):
        result = self.analyzer.analyze("what is KYC")
        assert result.query_type == "definition"
        assert result.confidence > 0.8
        assert result.optimal_strategy == "dense"

    def test_comparative_query(self):
        result = self.analyzer.analyze("RBI vs SEBI")
        assert result.query_type == "comparative"
        assert result.confidence > 0.9
        assert result.optimal_strategy == "hybrid"

    def test_semantic_query(self):
        result = self.analyzer.analyze("how do we complete Aadhaar verification?")
        assert result.query_type == "semantic"
        assert result.confidence > 0.8
        assert result.optimal_strategy == "dense"

    def test_keyword_query(self):
        result = self.analyzer.analyze("KYC")
        assert result.query_type == "keyword"
        assert result.confidence > 0.8
        assert result.optimal_strategy == "bm25"

    def test_analytics_logging(self):
        self.analyzer.analyze("RBI Circular 17/2024")
        self.analyzer.analyze("how do we complete Aadhaar verification?")

        log_file = os.path.join(self.tmp_dir, "query_analyses.jsonl")
        assert os.path.exists(log_file)

        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2

        log_data_1 = json.loads(lines[0])
        assert log_data_1["query"] == "RBI Circular 17/2024"
        assert log_data_1["query_type"] == "circular"
        assert log_data_1["optimal_strategy"] == "bm25"
        assert "timestamp" in log_data_1

        log_data_2 = json.loads(lines[1])
        assert log_data_2["query"] == "how do we complete Aadhaar verification?"
        assert log_data_2["query_type"] == "semantic"
        assert log_data_2["optimal_strategy"] == "dense"

    def test_custom_classifier(self):
        """Test that a custom classifier can be injected."""
        custom_classifier = RuleBasedQueryClassifier()
        analyzer = QueryAnalyzer(
            classifier=custom_classifier,
            analytics=self.analytics,
        )
        result = analyzer.analyze("RBI Circular 17/2024")
        assert result.query_type == "circular"

    def test_custom_recommender(self):
        """Test that a custom recommender can be injected."""
        custom_recommender = RuleBasedStrategyRecommender()
        analyzer = QueryAnalyzer(
            recommender=custom_recommender,
            analytics=self.analytics,
        )
        result = analyzer.analyze("RBI Circular 17/2024")
        assert result.optimal_strategy == "bm25"

    def test_result_contains_original_query(self):
        result = self.analyzer.analyze("test query string")
        assert result.query == "test query string"

    def test_confidence_in_valid_range(self):
        """All confidence scores should be between 0 and 1."""
        queries = [
            "RBI Circular 17/2024",
            "what is KYC",
            "RBI vs SEBI",
            "section 45",
            "how to comply",
            "KYC",
        ]
        for query in queries:
            result = self.analyzer.analyze(query)
            assert 0.0 <= result.confidence <= 1.0

    def test_all_query_types_covered(self):
        """Test that all query types can be classified."""
        test_cases = [
            ("RBI Circular 17/2024", "circular"),
            ("section 45 of RBI Act", "regulation"),
            ("what is KYC", "definition"),
            ("RBI vs SEBI", "comparative"),
            ("how do we comply?", "semantic"),
            ("KYC", "keyword"),
        ]
        for query, expected_type in test_cases:
            result = self.analyzer.analyze(query)
            assert result.query_type == expected_type, f"Failed for query: {query}"

    def test_all_strategies_recommended(self):
        """Test that all three strategies can be recommended."""
        bm25_result = self.analyzer.analyze("RBI Circular 17/2024")
        assert bm25_result.optimal_strategy == "bm25"

        dense_result = self.analyzer.analyze("what is KYC")
        assert dense_result.optimal_strategy == "dense"

        hybrid_result = self.analyzer.analyze("RBI vs SEBI")
        assert hybrid_result.optimal_strategy == "hybrid"


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Edge case tests for the query analysis engine."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analytics = AnalyticsManager(analytics_dir=self.tmp_dir)
        self.analyzer = QueryAnalyzer(analytics=self.analytics)

    def test_empty_string(self):
        result = self.analyzer.analyze("")
        assert result.query_type == "keyword"
        assert result.confidence == 1.0

    def test_whitespace_only(self):
        result = self.analyzer.analyze("   ")
        assert result.query_type == "keyword"

    def test_very_long_query(self):
        long_query = " ".join(["word"] * 100)
        result = self.analyzer.analyze(long_query)
        assert result.query_type in [t.value for t in QueryType]
        assert 0.0 <= result.confidence <= 1.0

    def test_special_characters(self):
        result = self.analyzer.analyze("RBI@SEBI#2024")
        assert result.query_type in [t.value for t in QueryType]

    def test_unicode_query(self):
        result = self.analyzer.analyze("केवाईसी क्या है")
        assert result.query_type in [t.value for t in QueryType]

    def test_mixed_case(self):
        result = self.analyzer.analyze("RbI CiRcUlAr 17/2024")
        assert result.query_type == "circular"

    def test_multiple_spaces(self):
        result = self.analyzer.analyze("RBI   Circular   17/2024")
        assert result.query_type == "circular"

    def test_leading_trailing_spaces(self):
        result = self.analyzer.analyze("  RBI Circular 17/2024  ")
        assert result.query_type == "circular"

    def test_case_insensitive_definition(self):
        result = self.analyzer.analyze("WHAT IS KYC")
        assert result.query_type == "definition"

    def test_case_insensitive_comparative(self):
        result = self.analyzer.analyze("RBI VS SEBI")
        assert result.query_type == "comparative"