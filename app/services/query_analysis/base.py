from abc import ABC, abstractmethod
from enum import Enum
from typing import Tuple

class QueryType(str, Enum):
    """Enumeration of supported search query types."""
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    REGULATION = "regulation"
    CIRCULAR = "circular"
    COMPARATIVE = "comparative"
    DEFINITION = "definition"

class ClassificationRule(ABC):
    """Abstract base class representing a single classification rule."""
    
    @property
    @abstractmethod
    def query_type(self) -> QueryType:
        """The query type this rule evaluates."""
        pass

    @abstractmethod
    def evaluate(self, query: str) -> float:
        """Evaluates the query text.
        
        Returns:
            A confidence score float between 0.0 and 1.0.
        """
        pass

class QueryClassifier(ABC):
    """Abstract interface for pluggable query classifiers (rule-based or machine learning)."""

    @abstractmethod
    def classify(self, query: str) -> Tuple[QueryType, float]:
        """Classifies the given query string.
        
        Returns:
            A tuple of (QueryType, confidence_score).
        """
        pass
