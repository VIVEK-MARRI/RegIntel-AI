"""Golden Dataset management for retrieval evaluation.

Provides functionality to create, load, and manage golden datasets
containing queries with relevance judgments.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.evaluation.schemas import GoldenDataset, QueryRelevance

logger = logging.getLogger(__name__)

# Default storage path for golden datasets
DEFAULT_DATASET_DIR = Path("storage/evaluation/datasets")


class DatasetManager:
    """Manages golden datasets for retrieval evaluation."""

    def __init__(self, dataset_dir: Optional[Path] = None):
        """Initialize the dataset manager.

        Args:
            dataset_dir: Directory to store/load datasets. Defaults to storage/evaluation/datasets.
        """
        self.dataset_dir = dataset_dir or DEFAULT_DATASET_DIR
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self._datasets: Dict[str, GoldenDataset] = {}

    def create_dataset(
        self,
        name: str,
        queries: List[QueryRelevance],
        description: str = "",
        metadata: Optional[Dict] = None,
    ) -> GoldenDataset:
        """Create a new golden dataset.

        Args:
            name: Name of the dataset.
            queries: List of queries with relevance judgments.
            description: Optional description.
            metadata: Optional metadata dictionary.

        Returns:
            Created GoldenDataset instance.
        """
        dataset = GoldenDataset(
            name=name,
            description=description,
            queries=queries,
            metadata=metadata or {},
        )
        self._datasets[name] = dataset
        logger.info(f"Created golden dataset '{name}' with {len(queries)} queries.")
        return dataset

    def save_dataset(self, dataset: GoldenDataset) -> Path:
        """Save a dataset to disk.

        Args:
            dataset: The dataset to save.

        Returns:
            Path to the saved file.
        """
        file_path = self.dataset_dir / f"{dataset.name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(dataset.model_dump(), f, indent=2, default=str)
        logger.info(f"Saved dataset '{dataset.name}' to {file_path}")
        return file_path

    def load_dataset(self, name: str) -> Optional[GoldenDataset]:
        """Load a dataset from disk.

        Args:
            name: Name of the dataset to load.

        Returns:
            Loaded GoldenDataset or None if not found.
        """
        # Check cache first
        if name in self._datasets:
            return self._datasets[name]

        file_path = self.dataset_dir / f"{name}.json"
        if not file_path.exists():
            logger.warning(f"Dataset '{name}' not found at {file_path}")
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        dataset = GoldenDataset(**data)
        self._datasets[name] = dataset
        logger.info(f"Loaded dataset '{name}' with {len(dataset.queries)} queries.")
        return dataset

    def list_datasets(self) -> List[str]:
        """List all available dataset names.

        Returns:
            List of dataset names.
        """
        datasets = []
        if self.dataset_dir.exists():
            for file_path in self.dataset_dir.glob("*.json"):
                datasets.append(file_path.stem)
        return sorted(datasets)

    def delete_dataset(self, name: str) -> bool:
        """Delete a dataset.

        Args:
            name: Name of the dataset to delete.

        Returns:
            True if deleted, False if not found.
        """
        file_path = self.dataset_dir / f"{name}.json"
        if file_path.exists():
            file_path.unlink()
            self._datasets.pop(name, None)
            logger.info(f"Deleted dataset '{name}'")
            return True
        return False

    def get_or_create_default_dataset(self) -> GoldenDataset:
        """Get the default dataset or create a sample one if it doesn't exist.

        Returns:
            The default GoldenDataset.
        """
        dataset = self.load_dataset("default")
        if dataset is not None:
            return dataset

        # Create a sample dataset for demonstration
        sample_queries = [
            QueryRelevance(
                query_id="q001",
                query_text="What are the capital adequacy requirements for banks?",
                relevant_chunk_ids=[],  # To be populated with actual chunk IDs
                metadata={"category": "capital_adequacy", "source": "RBI"},
            ),
            QueryRelevance(
                query_id="q002",
                query_text="Explain the guidelines for non-performing assets classification",
                relevant_chunk_ids=[],
                metadata={"category": "NPA", "source": "RBI"},
            ),
            QueryRelevance(
                query_id="q003",
                query_text="What are the KYC norms for customer identification?",
                relevant_chunk_ids=[],
                metadata={"category": "KYC", "source": "RBI"},
            ),
            QueryRelevance(
                query_id="q004",
                query_text="Describe the SEBI regulations for mutual funds",
                relevant_chunk_ids=[],
                metadata={"category": "mutual_funds", "source": "SEBI"},
            ),
            QueryRelevance(
                query_id="q005",
                query_text="What are the disclosure requirements for listed companies?",
                relevant_chunk_ids=[],
                metadata={"category": "disclosure", "source": "SEBI"},
            ),
        ]

        dataset = self.create_dataset(
            name="default",
            queries=sample_queries,
            description="Default sample dataset for retrieval evaluation",
            metadata={"version": "1.0", "type": "sample"},
        )
        self.save_dataset(dataset)
        return dataset


def create_sample_dataset_with_ids(
    chunk_ids: List[str],
    queries_data: Optional[List[Dict]] = None,
) -> GoldenDataset:
    """Create a sample dataset with actual chunk IDs for testing.

    Args:
        chunk_ids: List of available chunk IDs to assign as relevant.
        queries_data: Optional custom query data.

    Returns:
        GoldenDataset with populated relevant chunk IDs.
    """
    if queries_data is None:
        queries_data = [
            {
                "query_id": "q001",
                "query_text": "What are the capital adequacy requirements for banks?",
                "relevant_indices": [0, 1, 2],
                "metadata": {"category": "capital_adequacy"},
            },
            {
                "query_id": "q002",
                "query_text": "Explain the guidelines for non-performing assets",
                "relevant_indices": [1, 3, 5],
                "metadata": {"category": "NPA"},
            },
            {
                "query_id": "q003",
                "query_text": "What are the KYC norms for customer identification?",
                "relevant_indices": [0, 4, 6],
                "metadata": {"category": "KYC"},
            },
            {
                "query_id": "q004",
                "query_text": "Describe the SEBI regulations for mutual funds",
                "relevant_indices": [2, 5, 7],
                "metadata": {"category": "mutual_funds"},
            },
            {
                "query_id": "q005",
                "query_text": "What are the disclosure requirements for listed companies?",
                "relevant_indices": [3, 6, 8],
                "metadata": {"category": "disclosure"},
            },
        ]

    queries = []
    for qd in queries_data:
        relevant_ids = []
        for idx in qd.get("relevant_indices", []):
            if idx < len(chunk_ids):
                relevant_ids.append(chunk_ids[idx])

        queries.append(
            QueryRelevance(
                query_id=qd["query_id"],
                query_text=qd["query_text"],
                relevant_chunk_ids=relevant_ids,
                metadata=qd.get("metadata", {}),
            )
        )

    return GoldenDataset(
        name="sample_with_ids",
        description="Sample dataset with actual chunk IDs",
        queries=queries,
        metadata={"version": "1.0", "type": "sample_with_ids"},
    )
