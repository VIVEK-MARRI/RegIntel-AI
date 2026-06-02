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
    ClassificationRule,
    QueryClassifier
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------
# 1. Classification Rules
# ----------------------------------------------------

class CircularSearchRule(ClassificationRule):
    """Rule matching circular and notification search intent."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.CIRCULAR

    def evaluate(self, query: str) -> float:
        q_lower = query.lower()
        
        # Regex to detect circular reference patterns: "17/2024", "rbi/2024-25/123", "sebi/ho/dfd"
        ref_patterns = [
            r"\b\d+/\d{4}\b",
            r"\brbi/\d{4}\b",
            r"\bsebi/\w+\b",
            r"\bho/d\w+\b",
            r"\bcircular\s+no\b"
        ]
        if any(re.search(pat, q_lower) for pat in ref_patterns):
            return 0.95
            
        # General circular terms
        terms = ["circular", "notification", "circulars", "notifications", "master circular"]
        if any(t in q_lower for t in terms):
            return 0.80
            
        return 0.0

class RegulationSearchRule(ClassificationRule):
    """Rule matching specific acts, rules, chapters, and sections search intent."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.REGULATION

    def evaluate(self, query: str) -> float:
        q_lower = query.lower()
        
        # Regex to detect section or clause references: "sec 45", "section 12A", "clause 4(1)", "rule 9"
        sec_patterns = [
            r"\bsection\s+\d+\b",
            r"\bsec\b\.?\s*\d+\b",
            r"\bclause\s+\d+\b",
            r"\brule\s+\d+\b",
            r"\bchapter\s+[ivxlcdm]+\b",
            r"\bchapter\s+\d+\b",
            r"\bact\b"
        ]
        if any(re.search(pat, q_lower) for pat in sec_patterns):
            return 0.95
            
        # General terms
        terms = ["regulation", "regulations", "sub-section", "sub-clause", "guidelines"]
        if any(t in q_lower for t in terms):
            return 0.75
            
        return 0.0

class DefinitionQueryRule(ClassificationRule):
    """Rule matching queries seeking terms definitions."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.DEFINITION

    def evaluate(self, query: str) -> float:
        q_lower = query.lower().strip()
        
        # Exact definition patterns
        starts_with_patterns = [
            "what is ", "what does ", "define ", "definition of ", "meaning of ", "meaning ", "stands for "
        ]
        if any(q_lower.startswith(pat) for pat in starts_with_patterns):
            return 0.90
            
        terms = ["definition", "define", "stands for", "meaning of"]
        if any(t in q_lower for t in terms):
            return 0.75
            
        return 0.0

class ComparativeQueryRule(ClassificationRule):
    """Rule matching intent to compare distinct items, regulations, or bodies."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.COMPARATIVE

    def evaluate(self, query: str) -> float:
        q_lower = query.lower()
        
        # Comparative triggers
        vs_patterns = [
            r"\bversus\b",
            r"\bvs\b\.?",
            r"\bdifference\s+between\b",
            r"\bcompare\b",
            r"\bcomparison\b",
            r"\bdifferent\s+from\b",
            r"\brelationship\s+between\b"
        ]
        if any(re.search(pat, q_lower) for pat in vs_patterns):
            return 0.95
            
        return 0.0

class SemanticQuestionRule(ClassificationRule):
    """Rule matching general semantic question inquiries."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.SEMANTIC

    def evaluate(self, query: str) -> float:
        q_lower = query.lower()
        
        # Starts with query words
        q_words = ["how ", "why ", "who ", "where ", "when ", "explain ", "describe ", "can we ", "should we ", "is there "]
        if any(q_lower.startswith(w) for w in q_words):
            return 0.85
            
        # Ends with question mark
        if q_lower.endswith("?"):
            return 0.80
            
        # General query helpers
        helpers = ["change", "amendment", "update", "impact of", "requirements for", "compliance with"]
        if any(h in q_lower for h in helpers):
            return 0.70
            
        return 0.0

class KeywordLookupRule(ClassificationRule):
    """Rule matching short search query strings lacking natural language verbs."""
    @property
    def query_type(self) -> QueryType:
        return QueryType.KEYWORD

    def evaluate(self, query: str) -> float:
        # Fallback keyword scoring based on token count
        words = query.strip().split()
        word_count = len(words)
        
        if word_count <= 3:
            # Short search query is heavily keyword based
            return max(0.9 - (word_count * 0.1), 0.6)
            
        return 0.3

# ----------------------------------------------------
# 2. Classifier Implementation
# ----------------------------------------------------

class RuleBasedQueryClassifier(QueryClassifier):
    """Classifies user queries using a set of rules, returning the highest confidence match."""

    def __init__(self, rules: Optional[List[ClassificationRule]] = None):
        self.rules = rules or [
            CircularSearchRule(),
            RegulationSearchRule(),
            DefinitionQueryRule(),
            ComparativeQueryRule(),
            SemanticQuestionRule(),
            KeywordLookupRule()
        ]

    def classify(self, query: str) -> Tuple[QueryType, float]:
        if not query or not query.strip():
            return QueryType.KEYWORD, 1.0

        best_type = QueryType.KEYWORD
        best_score = 0.0

        for rule in self.rules:
            score = rule.evaluate(query)
            if score > best_score:
                best_score = score
                best_type = rule.query_type

        # Default fallback if no rules match cleanly
        if best_score == 0.0:
            return QueryType.KEYWORD, 0.5

        return best_type, best_score

# ----------------------------------------------------
# 3. Analytics Integration
# ----------------------------------------------------

class AnalyticsManager:
    """Logs classified query telemetry results to disk for analytics reporting."""

    def __init__(self, analytics_dir: Optional[str] = None):
        self.analytics_dir = analytics_dir or os.path.join(settings.STORAGE_ROOT, "analytics")
        os.makedirs(self.analytics_dir, exist_ok=True)
        self.filepath = os.path.join(self.analytics_dir, "query_analyses.jsonl")

    def log_analysis(self, result: QueryAnalysisResult) -> None:
        """Appends a query analysis record to the analytics log file."""
        record = {
            "query": result.query,
            "query_type": result.query_type,
            "confidence": result.confidence,
            "optimal_strategy": result.optimal_strategy,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"Failed to log query analysis to analytics file: {e}")

# ----------------------------------------------------
# 4. Analyzer Implementation
# ----------------------------------------------------

class QueryAnalyzer:
    """Analyzes search query semantics and recommends the optimal retrieval strategy."""

    def __init__(self, classifier: Optional[QueryClassifier] = None, analytics: Optional[AnalyticsManager] = None):
        self.classifier = classifier or RuleBasedQueryClassifier()
        self.analytics = analytics or AnalyticsManager()

    def analyze(self, query: str) -> QueryAnalysisResult:
        """Determines the query type, confidence level, and recommended search strategy."""
        query_type, confidence = self.classifier.classify(query)
        
        # Optimal Strategy Recommendation
        # Keyword-heavy categories default to keyword/BM25 retrieval.
        # Semantic, Definition, and Comparative queries benefit from semantic vector searches.
        keyword_types = [QueryType.KEYWORD, QueryType.CIRCULAR, QueryType.REGULATION]
        if query_type in keyword_types:
            strategy = "keyword"
        else:
            strategy = "semantic"
            
        result = QueryAnalysisResult(
            query=query,
            query_type=query_type.value,
            confidence=confidence,
            optimal_strategy=strategy
        )
        
        # Log to analytics and debug loggers
        self.analytics.log_analysis(result)
        logger.info(
            f"Query analyzed: '{query}' -> type={query_type.value} "
            f"(confidence={confidence:.2f}, strategy={strategy})"
        )
        return result
