from abc import ABC, abstractmethod
from typing import List

class EmbeddingProvider(ABC):
    """Abstract Base Class (interface) for vector embedding providers."""

    @abstractmethod
    def encode_text(self, text: str) -> List[float]:
        """Encodes a single text string into a vector embedding.

        Args:
            text: Input text string.

        Returns:
            A list of floats representing the embedding vector.
        """
        pass

    @abstractmethod
    def encode_query(self, query: str) -> List[float]:
        """Encodes a retrieval query, applying model-specific instructions if needed.

        Args:
            query: The search query text string.

        Returns:
            A list of floats representing the query embedding vector.
        """
        pass

    @abstractmethod
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encodes a list of text strings in batch.

        Args:
            texts: A list of text strings.

        Returns:
            A list of lists of floats representing embedding vectors.
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """Returns the size of the vector embeddings produced by the model."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Returns the name or identifier of the configured model."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Runs a validation inference pass to ensure the model is loaded and working."""
        pass
