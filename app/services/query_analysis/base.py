from abc import ABC, abstractmethod
from enum import Enum
from typing import Tuple, List, Optional


class QueryType(str, Enum):
    """Enumeration of supported search query types."""
    KEYWORD = "keyword"
    KEYWORD_LOOKUP = "keyword_lookup"
    SEMANTIC = "semantic"
    REGULATION = "regulation"
    CIRCULAR = "circular"
    COMPARATIVE = "comparative"
    DEFINITION = "definition"


class RetrievalStrategy(str, Enum):
    """Enumeration of supported retrieval strategies."""
    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"


class ClassificationRule(ABC):
    """Abstract base class representing a single classification rule.

    Each rule evaluates a query and returns a confidence score between 0.0 and 1.0.
    Rules are evaluated in priority order by the classifier.
    """

    @property
    @abstractmethod
    def query_type(self) -> QueryType:
        """The query type this rule evaluates."""
        pass

    @abstractmethod
    def evaluate(self, query: str) -> float:
        """Evaluates the query text.

        Args:
            query: The raw user query string.

        Returns:
            A confidence score float between 0.0 and 1.0.
        """
        pass


class QueryClassifier(ABC):
    """Abstract interface for pluggable query classifiers.

    Supports both rule-based and machine learning classifiers.
    Implementations must be stateless and thread-safe.
    """

    @abstractmethod
    def classify(self, query: str) -> Tuple[QueryType, float]:
        """Classifies the given query string.

        Args:
            query: The raw user query string.

        Returns:
            A tuple of (QueryType, confidence_score).
        """
        pass


class StrategyRecommender(ABC):
    """Abstract interface for retrieval strategy recommendation.

    Maps classified query types and confidence scores to optimal
    retrieval strategies (BM25, Dense, or Hybrid).
    """

    @abstractmethod
    def recommend(
        self,
        query_type: QueryType,
        confidence: float,
        query: str
    ) -> RetrievalStrategy:
        """Recommends a retrieval strategy based on classification results.

        Args:
            query_type: The classified query type.
            confidence: The classification confidence score.
            query: The original query text (for additional heuristics).

        Returns:
            The recommended RetrievalStrategy.
        """
        pass