import os
import re
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from app.core.config import settings
from app.schemas.query_analysis import QueryAnalysisResult
from app.services.query_analysis.base import (
    QueryType,
    RetrievalStrategy,
    ClassificationRule,
    QueryClassifier,
    StrategyRecommender,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Classification Rules
# =============================================================================


class CircularSearchRule(ClassificationRule):
    """Rule matching circular and notification search intent.

    Detects patterns like:
    - "RBI Circular 17/2024"
    - "SEBI/HO/DDHS/DDHS-RAC-1/P/CIR/2024/123"
    - "circular no 12"
    - "master circular on KYC"
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.CIRCULAR

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()

        # High-confidence: circular reference number patterns
        ref_patterns = [
            r"\b\d+/\d{4}\b",  # "17/2024", "12/2023"
            r"\b\d{4}-\d{2,4}/\d+\b",  # "2024-25/123"
            r"\brbi/\d{4}\b",  # "rbi/2024"
            r"\bsebi/\w+",  # "sebi/ho/..."
            r"\bho/d\w+\b",  # "ho/dfd"
            r"\bcircular\s+no\b\.?",  # "circular no 12"
            r"\bcircular\s+no\.\s*\d+",  # "circular no. 12"
            r"\bnotification\s+no\b\.?",  # "notification no 5"
            r"\b\d{4}/\d+/\d+\b",  # "2024/12/001"
        ]
        if any(re.search(pat, q_lower) for pat in ref_patterns):
            return 0.95

        # Medium-confidence: general circular/notification terms
        strong_terms = [
            "circular",
            "notification",
            "master circular",
            "master direction",
        ]
        if any(t in q_lower for t in strong_terms):
            return 0.80

        # Lower-confidence: related terms
        weak_terms = ["circulars", "notifications", "office order", "press release"]
        if any(t in q_lower for t in weak_terms):
            return 0.60

        return 0.0


class RegulationSearchRule(ClassificationRule):
    """Rule matching specific acts, rules, chapters, and sections search intent.

    Detects patterns like:
    - "section 45 of RBI Act"
    - "sec. 12"
    - "chapter III"
    - "SEBI (LODR) Regulations"
    - "rule 9 of Companies Act"
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.REGULATION

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()

        # High-confidence: section/clause/rule/chapter references
        sec_patterns = [
            r"\bsection\s+\d+[a-z]?\b",  # "section 45", "section 12A"
            r"\bsec\b\.?\s*\d+[a-z]?\b",  # "sec. 12", "sec 45"
            r"\bclause\s+\d+\b",  # "clause 4"
            r"\brule\s+\d+\b",  # "rule 9"
            r"\bchapter\s+[ivxlcdm]+\b",  # "chapter III"
            r"\bchapter\s+\d+\b",  # "chapter 3"
            r"\bsub-section\s+\d+\b",  # "sub-section 2"
            r"\bsub-clause\s+\d+\b",  # "sub-clause 1"
            r"\bschedule\s+[a-z\d]+\b",  # "schedule III"
            r"\bpart\s+[a-z\d]+\b",  # "part A"
            r"\bannexure\s+[a-z\d]+\b",  # "annexure 1"
            r"\bregulation\s+\d+\b",  # "regulation 12"
        ]
        if any(re.search(pat, q_lower) for pat in sec_patterns):
            return 0.95

        # Medium-confidence: act/regulation references
        act_patterns = [
            r"\bact\b",  # "RBI Act", "Companies Act"
            r"\bregulations?\b",  # "SEBI Regulations"
            r"\bguidelines?\b",  # "RBI Guidelines"
            r"\bdirections?\b",  # "RBI Directions"
            r"\bframework\b",  # "regulatory framework"
        ]
        if any(re.search(pat, q_lower) for pat in act_patterns):
            return 0.75

        return 0.0


class DefinitionQueryRule(ClassificationRule):
    """Rule matching queries seeking term definitions.

    Detects patterns like:
    - "what is KYC"
    - "define mutual fund"
    - "meaning of compliance"
    - "AML stands for"
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.DEFINITION

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()

        # High-confidence: starts with definition patterns
        starts_with_patterns = [
            "what is ",
            "what are ",
            "what does ",
            "define ",
            "definition of ",
            "meaning of ",
            "meaning ",
            "stands for ",
            "abbreviation of ",
            "full form of ",
            "expand ",
            "explain what ",
        ]
        if any(q_lower.startswith(pat) for pat in starts_with_patterns):
            return 0.90

        # Medium-confidence: contains definition terms
        terms = ["definition", "define", "stands for", "meaning of", "full form"]
        if any(t in q_lower for t in terms):
            return 0.75

        # Lower-confidence: acronym expansion patterns
        acronym_patterns = [
            r"\b[A-Z]{2,}\b\s+(?:stands? for|means?|refers? to)",
            r"\bwhat\s+(?:is|are)\s+[A-Z]{2,}\b",
        ]
        if any(re.search(pat, q_lower) for pat in acronym_patterns):
            return 0.70

        return 0.0


class ComparativeQueryRule(ClassificationRule):
    """Rule matching intent to compare distinct items, regulations, or bodies.

    Detects patterns like:
    - "RBI vs SEBI"
    - "difference between KYC and diligence"
    - "mutual fund versus equity"
    - "compare IPO and FPO"
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.COMPARATIVE

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()

        # High-confidence: explicit comparison patterns
        vs_patterns = [
            r"\bversus\b",
            r"\bvs\b\.?",
            r"\bdifference\s+between\b",
            r"\bdifferences\s+between\b",
            r"\bcompare\b",
            r"\bcomparison\b",
            r"\bcomparing\b",
            r"\bdifferent\s+from\b",
            r"\bdistinction\s+between\b",
            r"\bdistinguish\s+between\b",
            r"\bcontrast\s+between\b",
            r"\bpros\s+and\s+cons\b",
            r"\badvantages?\s+(?:and|&)\s+disadvantages?\b",
            r"\bwhich\s+is\s+better\b",
        ]
        if any(re.search(pat, q_lower) for pat in vs_patterns):
            return 0.95

        # Medium-confidence: "and" between two known entities (heuristic)
        # e.g., "RBI and SEBI guidelines"
        if re.search(r"\b(\w+)\s+and\s+(\w+)\b", q_lower):
            # Check if query also contains regulatory terms
            reg_terms = [
                "guidelines",
                "regulations",
                "act",
                "rules",
                "circular",
                "notification",
            ]
            if any(t in q_lower for t in reg_terms):
                return 0.65

        return 0.0


class SemanticQuestionRule(ClassificationRule):
    """Rule matching general semantic question inquiries.

    Detects patterns like:
    - "how do we comply with AML?"
    - "why did SEBI amend guidelines?"
    - "explain the role of board"
    - "what changed in KYC requirements?"
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.SEMANTIC

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()

        # High-confidence: starts with WH-question words
        q_words = [
            "how ",
            "how do",
            "how does",
            "how can",
            "how should",
            "how to",
            "why ",
            "why did",
            "why is",
            "why are",
            "why was",
            "who ",
            "who is",
            "who are",
            "where ",
            "where is",
            "where can",
            "when ",
            "when did",
            "when is",
            "when should",
            "what ",
            "what is",
            "what are",
            "what was",
            "what were",
            "which ",
            "which is",
            "which are",
        ]
        if any(q_lower.startswith(w) for w in q_words):
            return 0.85

        # High-confidence: starts with imperative explanation verbs
        explain_verbs = [
            "explain ",
            "describe ",
            "elaborate ",
            "clarify ",
            "illustrate ",
            "summarize ",
            "outline ",
        ]
        if any(q_lower.startswith(v) for v in explain_verbs):
            return 0.85

        # Medium-confidence: ends with question mark (natural language question)
        if q_lower.endswith("?"):
            return 0.80

        # Medium-confidence: contains query helper phrases
        helpers = [
            "change",
            "amendment",
            "update",
            "impact of",
            "requirements for",
            "compliance with",
            "process for",
            "procedure for",
            "steps to",
            "way to",
            "method for",
            "implications of",
            "consequences of",
            "effect of",
        ]
        if any(h in q_lower for h in helpers):
            return 0.70

        # Lower-confidence: contains "tell me about" or similar
        tell_patterns = [
            r"\btell\s+me\s+about\b",
            r"\bhelp\s+me\s+understand\b",
            r"\bi\s+want\s+to\s+know\b",
        ]
        if any(re.search(pat, q_lower) for pat in tell_patterns):
            return 0.65

        return 0.0


class KeywordLookupRule(ClassificationRule):
    """Rule matching short search query strings lacking natural language verbs.

    This is a fallback rule that scores based on query length and structure.
    Short queries (1-3 words) without question structure are likely keyword lookups.

    Examples:
    * "KYC" -> keyword_lookup
    * "KYC Aadhaar PAN" -> keyword_lookup
    * "RBI Circular 17/2024" -> keyword (but CircularSearchRule takes priority)
    """

    @property
    def query_type(self) -> QueryType:
        return QueryType.KEYWORD_LOOKUP

    def evaluate(self, query: str) -> float:
        words = query.strip().split()
        word_count = len(words)

        # Very short queries are almost certainly keyword lookups
        if word_count == 1:
            return 0.85
        if word_count == 2:
            return 0.75
        if word_count == 3:
            return 0.65

        # Longer queries get a low baseline score
        # (other rules should dominate for longer queries)
        return 0.30


# =============================================================================
# 2. Classifier Implementation
# =============================================================================


class RuleBasedQueryClassifier(QueryClassifier):
    """Classifies user queries using a prioritized set of rules.

    Rules are evaluated in order, and the highest-confidence match wins.
    The default rule priority order is:
    1. CircularSearchRule (highest priority for exact reference matches)
    2. RegulationSearchRule
    3. ComparativeQueryRule
    4. DefinitionQueryRule
    5. SemanticQuestionRule
    6. KeywordLookupRule (lowest priority, acts as fallback)

    This ordering ensures that specific structural patterns (like circular numbers)
    are matched before general semantic patterns.
    """

    def __init__(self, rules: Optional[List[ClassificationRule]] = None):
        self.rules = rules or [
            CircularSearchRule(),
            RegulationSearchRule(),
            ComparativeQueryRule(),
            DefinitionQueryRule(),
            SemanticQuestionRule(),
            KeywordLookupRule(),
        ]

    def classify(self, query: str) -> Tuple[QueryType, float]:
        """Classifies the query using all registered rules.

        Args:
            query: The raw user query string.

        Returns:
            A tuple of (QueryType, confidence_score).
        """
        if not query or not query.strip():
            return QueryType.KEYWORD_LOOKUP, 1.0

        best_type = QueryType.KEYWORD_LOOKUP
        best_score = 0.0

        for rule in self.rules:
            score = rule.evaluate(query)
            if score > best_score:
                best_score = score
                best_type = rule.query_type

        # Default fallback if no rules match cleanly
        if best_score == 0.0:
            return QueryType.KEYWORD_LOOKUP, 0.5

        return best_type, best_score


class MLQueryClassifier(QueryClassifier):
    """Adapter for future ML-based query classification.

    This class provides the integration point for a machine learning model.
    When an ML model is available, it will be used for classification.
    Otherwise, it falls back to the rule-based classifier.

    Usage:
        ml_classifier = MLQueryClassifier(
            model_path="path/to/model",
            fallback_classifier=RuleBasedQueryClassifier()
        )
        query_type, confidence = ml_classifier.classify("RBI Circular 17/2024")
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        fallback_classifier: Optional[QueryClassifier] = None,
    ):
        self.model_path = model_path
        self.fallback = fallback_classifier or RuleBasedQueryClassifier()
        self._model = None

    def _load_model(self):
        """Lazy-loads the ML model when first needed.

        Override this method to integrate with your ML framework
        (e.g., scikit-learn, PyTorch, TensorFlow, HuggingFace).
        """
        if self._model is None and self.model_path:
            # Placeholder for model loading logic
            # Example:
            # import joblib
            # self._model = joblib.load(self.model_path)
            logger.info(
                f"ML model loading not yet implemented. Path: {self.model_path}"
            )
        return self._model

    def classify(self, query: str) -> Tuple[QueryType, float]:
        """Classifies using ML model if available, otherwise falls back to rules.

        Args:
            query: The raw user query string.

        Returns:
            A tuple of (QueryType, confidence_score).
        """
        model = self._load_model()

        if model is not None:
            try:
                # Placeholder for ML inference
                # Example:
                # prediction = model.predict([query])[0]
                # confidence = max(model.predict_proba([query])[0])
                # return QueryType(prediction), confidence
                pass
            except Exception as e:
                logger.warning(f"ML classification failed, falling back to rules: {e}")

        # Fallback to rule-based classification
        return self.fallback.classify(query)


# =============================================================================
# 3. Strategy Recommender
# =============================================================================


class RuleBasedStrategyRecommender(StrategyRecommender):
    """Recommends retrieval strategy based on query classification.

    Strategy mapping:
    - BM25 (keyword): For exact reference lookups (circulars, regulations, keywords)
    - Dense (semantic): For natural language questions and definitions
    - Hybrid: For comparative queries and low-confidence classifications

    The recommender also considers confidence scores:
    - High confidence (>0.8): Use the primary strategy for the query type
    - Medium confidence (0.5-0.8): Use hybrid for broader coverage
    - Low confidence (<0.5): Use hybrid as safe default
    """

    # Query types that benefit most from BM25 (exact match)
    BM25_TYPES = {
        QueryType.KEYWORD,
        QueryType.KEYWORD_LOOKUP,
        QueryType.CIRCULAR,
        QueryType.REGULATION,
    }

    # Query types that benefit most from dense (semantic) retrieval
    DENSE_TYPES = {QueryType.SEMANTIC, QueryType.DEFINITION}

    # Query types that benefit from hybrid retrieval
    HYBRID_TYPES = {QueryType.COMPARATIVE}

    # Confidence threshold below which we default to hybrid
    HYBRID_CONFIDENCE_THRESHOLD = 0.5

    def recommend(
        self, query_type: QueryType, confidence: float, query: str
    ) -> RetrievalStrategy:
        """Recommends a retrieval strategy.

        Args:
            query_type: The classified query type.
            confidence: The classification confidence score.
            query: The original query text.

        Returns:
            The recommended RetrievalStrategy.
        """
        # Low confidence → hybrid for safety
        if confidence < self.HYBRID_CONFIDENCE_THRESHOLD:
            return RetrievalStrategy.HYBRID

        # Type-based routing
        if query_type in self.BM25_TYPES:
            return RetrievalStrategy.BM25
        elif query_type in self.DENSE_TYPES:
            return RetrievalStrategy.DENSE
        elif query_type in self.HYBRID_TYPES:
            return RetrievalStrategy.HYBRID

        # Default fallback
        return RetrievalStrategy.HYBRID


# =============================================================================
# 4. Analytics Integration
# =============================================================================


class AnalyticsManager:
    """Logs classified query telemetry to disk for analytics reporting.

    Records are appended to a JSONL file for easy processing by
    analytics pipelines. Each record includes the query, classification
    result, confidence, recommended strategy, and timestamp.
    """

    def __init__(self, analytics_dir: Optional[str] = None):
        self.analytics_dir = analytics_dir or os.path.join(
            settings.STORAGE_ROOT, "analytics"
        )
        os.makedirs(self.analytics_dir, exist_ok=True)
        self.filepath = os.path.join(self.analytics_dir, "query_analyses.jsonl")

    def log_analysis(self, result: QueryAnalysisResult) -> None:
        """Appends a query analysis record to the analytics log file.

        Args:
            result: The QueryAnalysisResult to log.
        """
        record = {
            "query": result.query,
            "query_type": result.query_type,
            "confidence": result.confidence,
            "optimal_strategy": result.optimal_strategy,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"Failed to log query analysis to analytics file: {e}")

    def get_recent_analyses(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Reads recent analysis records from the log file.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of analysis record dictionaries.
        """
        if not os.path.exists(self.filepath):
            return []

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = []
            for line in lines[-limit:]:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            return records
        except Exception as e:
            logger.error(f"Failed to read analytics file: {e}")
            return []


# =============================================================================
# 5. Query Analyzer (Main Entry Point)
# =============================================================================


class QueryAnalyzer:
    """Main entry point for query understanding.

    Orchestrates classification, strategy recommendation, and analytics logging.
    All components are injectable for testability and future extensibility.

    Usage:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("RBI Circular 17/2024")
        print(result.query_type)       # "circular"
        print(result.confidence)       # 0.95
        print(result.optimal_strategy) # "bm25"
    """

    def __init__(
        self,
        classifier: Optional[QueryClassifier] = None,
        recommender: Optional[StrategyRecommender] = None,
        analytics: Optional[AnalyticsManager] = None,
    ):
        self.classifier = classifier or RuleBasedQueryClassifier()
        self.recommender = recommender or RuleBasedStrategyRecommender()
        self.analytics = analytics or AnalyticsManager()

    def analyze(self, query: str) -> QueryAnalysisResult:
        """Analyzes a search query and returns classification + strategy recommendation.

        Args:
            query: The raw user query string.

        Returns:
            QueryAnalysisResult with query_type, confidence, and optimal_strategy.
        """
        query_type, confidence = self.classifier.classify(query)
        strategy = self.recommender.recommend(query_type, confidence, query)

        result = QueryAnalysisResult(
            query=query,
            query_type=query_type.value,
            confidence=confidence,
            optimal_strategy=strategy.value,
        )

        # Log to analytics and debug loggers
        self.analytics.log_analysis(result)
        logger.info(
            "Query analyzed: '%s' -> type=%s (confidence=%.2f, strategy=%s)",
            query,
            query_type.value,
            confidence,
            strategy.value,
        )
        return result
