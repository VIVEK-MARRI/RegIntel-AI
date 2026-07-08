from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.schemas.structure import StructureElement


class BaseStructureExtractor(ABC):
    """Abstract Base Class defining the structure extractor interface."""

    @abstractmethod
    def extract_structure(self, pages: List[Dict[str, Any]]) -> List[StructureElement]:
        """Parses page text content list and returns a list of hierarchical structural elements.

        Args:
            pages: List of dictionaries with keys "page_number" (int) and "content" (str).

        Returns:
            A list of detected StructureElement objects.
        """
        pass
