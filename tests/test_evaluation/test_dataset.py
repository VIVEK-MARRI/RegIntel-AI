"""Tests for the Golden Dataset management."""

import json
import pytest
from pathlib import Path
from app.evaluation.dataset import DatasetManager, create_sample_dataset_with_ids
from app.evaluation.schemas import GoldenDataset, QueryRelevance


class TestDatasetManager:
    """Test suite for DatasetManager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_dir = Path("storage/evaluation/test_datasets")
        self.manager = DatasetManager(dataset_dir=self.test_dir)

    def teardown_method(self):
        """Clean up test files."""
        if self.test_dir.exists():
            for f in self.test_dir.glob("*"):
                f.unlink()
            self.test_dir.rmdir()

    def test_create_dataset(self):
        """Test creating a new dataset."""
        queries = [
            QueryRelevance(
                query_id="q1",
                query_text="Test query",
                relevant_chunk_ids=["chunk_1", "chunk_2"],
            )
        ]

        dataset = self.manager.create_dataset(
            name="test_dataset",
            queries=queries,
            description="Test description",
        )

        assert dataset.name == "test_dataset"
        assert len(dataset.queries) == 1
        assert dataset.description == "Test description"

    def test_save_and_load_dataset(self):
        """Test saving and loading a dataset."""
        queries = [
            QueryRelevance(
                query_id="q1",
                query_text="Test query",
                relevant_chunk_ids=["chunk_1"],
            )
        ]

        dataset = self.manager.create_dataset(name="test_save", queries=queries)
        self.manager.save_dataset(dataset)

        loaded = self.manager.load_dataset("test_save")
        assert loaded is not None
        assert loaded.name == "test_save"
        assert len(loaded.queries) == 1

    def test_load_nonexistent_dataset(self):
        """Test loading a dataset that doesn't exist."""
        loaded = self.manager.load_dataset("nonexistent")
        assert loaded is None

    def test_list_datasets(self):
        """Test listing available datasets."""
        # Create a few datasets
        for name in ["ds1", "ds2", "ds3"]:
            dataset = self.manager.create_dataset(
                name=name,
                queries=[],
            )
            self.manager.save_dataset(dataset)

        datasets = self.manager.list_datasets()
        assert "ds1" in datasets
        assert "ds2" in datasets
        assert "ds3" in datasets

    def test_delete_dataset(self):
        """Test deleting a dataset."""
        dataset = self.manager.create_dataset(
            name="to_delete",
            queries=[],
        )
        self.manager.save_dataset(dataset)

        assert self.manager.delete_dataset("to_delete") is True
        assert self.manager.load_dataset("to_delete") is None

    def test_delete_nonexistent_dataset(self):
        """Test deleting a dataset that doesn't exist."""
        assert self.manager.delete_dataset("nonexistent") is False

    def test_get_or_create_default_dataset(self):
        """Test getting or creating the default dataset."""
        dataset = self.manager.get_or_create_default_dataset()
        assert dataset is not None
        assert dataset.name == "default"
        assert len(dataset.queries) > 0

    def test_dataset_caching(self):
        """Test that datasets are cached after loading."""
        queries = [
            QueryRelevance(
                query_id="q1",
                query_text="Test",
                relevant_chunk_ids=["chunk_1"],
            )
        ]
        dataset = self.manager.create_dataset(name="cached", queries=queries)
        self.manager.save_dataset(dataset)

        # Load twice - second should come from cache
        loaded1 = self.manager.load_dataset("cached")
        loaded2 = self.manager.load_dataset("cached")

        assert loaded1 is not None
        assert loaded2 is not None


class TestCreateSampleDatasetWithIds:
    """Test suite for create_sample_dataset_with_ids helper."""

    def test_create_with_default_queries(self):
        """Test creating sample dataset with default queries."""
        chunk_ids = [f"chunk_{i}" for i in range(10)]
        dataset = create_sample_dataset_with_ids(chunk_ids)

        assert dataset.name == "sample_with_ids"
        assert len(dataset.queries) > 0

        # Check that relevant IDs are populated
        for query in dataset.queries:
            assert len(query.relevant_chunk_ids) > 0
            for chunk_id in query.relevant_chunk_ids:
                assert chunk_id in chunk_ids

    def test_create_with_custom_queries(self):
        """Test creating sample dataset with custom queries."""
        chunk_ids = [f"chunk_{i}" for i in range(5)]
        custom_queries = [
            {
                "query_id": "custom_1",
                "query_text": "Custom query",
                "relevant_indices": [0, 1],
                "metadata": {"custom": True},
            }
        ]

        dataset = create_sample_dataset_with_ids(chunk_ids, custom_queries)

        assert len(dataset.queries) == 1
        assert dataset.queries[0].query_id == "custom_1"
        assert dataset.queries[0].relevant_chunk_ids == ["chunk_0", "chunk_1"]

    def test_create_with_insufficient_chunks(self):
        """Test creating dataset when chunk list is shorter than indices."""
        chunk_ids = ["chunk_0", "chunk_1"]
        custom_queries = [
            {
                "query_id": "q1",
                "query_text": "Test",
                "relevant_indices": [0, 1, 5, 10],  # Some indices out of range
            }
        ]

        dataset = create_sample_dataset_with_ids(chunk_ids, custom_queries)

        # Only valid indices should be included
        assert dataset.queries[0].relevant_chunk_ids == ["chunk_0", "chunk_1"]


class TestQueryRelevance:
    """Test suite for QueryRelevance schema."""

    def test_create_query_relevance(self):
        """Test creating a QueryRelevance instance."""
        qr = QueryRelevance(
            query_id="q1",
            query_text="Test query",
            relevant_chunk_ids=["chunk_1", "chunk_2"],
            metadata={"category": "test"},
        )

        assert qr.query_id == "q1"
        assert qr.query_text == "Test query"
        assert len(qr.relevant_chunk_ids) == 2
        assert qr.metadata["category"] == "test"

    def test_query_relevance_empty_metadata(self):
        """Test QueryRelevance with default empty metadata."""
        qr = QueryRelevance(
            query_id="q1",
            query_text="Test",
            relevant_chunk_ids=[],
        )

        assert qr.metadata == {}


class TestGoldenDataset:
    """Test suite for GoldenDataset schema."""

    def test_create_golden_dataset(self):
        """Test creating a GoldenDataset instance."""
        queries = [
            QueryRelevance(
                query_id="q1",
                query_text="Query 1",
                relevant_chunk_ids=["chunk_1"],
            ),
            QueryRelevance(
                query_id="q2",
                query_text="Query 2",
                relevant_chunk_ids=["chunk_2", "chunk_3"],
            ),
        ]

        dataset = GoldenDataset(
            name="test",
            description="Test dataset",
            queries=queries,
        )

        assert dataset.name == "test"
        assert len(dataset.queries) == 2
        assert dataset.created_at is not None

    def test_golden_dataset_serialization(self):
        """Test serializing GoldenDataset to dict."""
        dataset = GoldenDataset(
            name="test",
            queries=[
                QueryRelevance(
                    query_id="q1",
                    query_text="Test",
                    relevant_chunk_ids=["chunk_1"],
                )
            ],
        )

        data = dataset.model_dump()
        assert data["name"] == "test"
        assert len(data["queries"]) == 1
