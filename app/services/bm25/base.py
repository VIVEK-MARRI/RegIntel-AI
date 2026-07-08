from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import uuid
from app.models.document import SourceEnum


class BM25Retriever(ABC):
    """Abstract interface defining the operations for BM25-based keyword search and retrieval."""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves top-K chunks matching query via BM25 keyword scoring.

        Args:
            query: The search query text.
            top_k: The number of top documents to return.
            score_threshold: The minimum BM25 score required to be included.
            source: SourceEnum filter (RBI or SEBI).
            document_id: specific Document UUID filter.

        Returns:
            List of result dicts containing:
              - chunk_id: str
              - score: float
              - section: str
              - content: str
              - metadata: dict
        """
        pass
