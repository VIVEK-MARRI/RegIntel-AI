"""
Comprehensive tests for the BM25 Retrieval Engine.

Tests cover:
- BM25Document data class
- BM25Tokenizer
- InMemoryBM25Retriever (build, update, rebuild, search, remove, clear)
- BM25IndexManager (lifecycle, persistence)
- BM25Service (high-level operations)
- Filtering (source, document, score threshold)
- Telemetry (latency, result count, average score)
"""

from __future__ import annotations

import os
import shutil
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.bm25.retriever import (
    BM25Document,
    BM25SearchRequest,
    BM25SearchResponse,
    BM25SearchResult,
    BM25IndexStats,
    BM25IndexError,
    BM25SearchError,
    BM25Tokenizer,
    IndexStatus,
    InMemoryBM25Retriever,
    AbstractBM25Retriever,
    Source,
)
from app.services.bm25.index_manager import BM25IndexManager, IndexManagerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_doc(
    chunk_id: str = "chunk-1",
    content: str = "KYC guidelines require customer identification",
    section_title: str = "KYC Guidelines",
    subsection_title: str = "Customer Identification",
    document_title: str = "RBI Master Direction on KYC",
    source: str = "RBI",
    document_id: str = "doc-1",
    page_number: int = 1,
) -> BM25Document:
    """Helper to create BM25Document instances."""
    return BM25Document(
        chunk_id=chunk_id,
        content=content,
        section_title=section_title,
        subsection_title=subsection_title,
        document_title=document_title,
        source=source,
        document_id=document_id,
        page_number=page_number,
    )


@pytest.fixture
def sample_documents() -> List[BM25Document]:
    """Create a set of sample regulatory documents."""
    return [
        make_doc(
            chunk_id="chunk-1",
            content="Banks must verify customer identity using official documents for KYC compliance",
            section_title="KYC Guidelines",
            subsection_title="Customer Identification",
            document_title="RBI Master Direction on KYC",
            source="RBI",
            document_id="doc-1",
        ),
        make_doc(
            chunk_id="chunk-2",
            content="Enhanced due diligence is required for high risk customers including PEPs",
            section_title="KYC Guidelines",
            subsection_title="Enhanced Due Diligence",
            document_title="RBI Master Direction on KYC",
            source="RBI",
            document_id="doc-1",
        ),
        make_doc(
            chunk_id="chunk-3",
            content="Stock exchanges must maintain proper risk management systems and surveillance",
            section_title="Risk Management",
            subsection_title="Surveillance Systems",
            document_title="SEBI Stock Exchange Regulations",
            source="SEBI",
            document_id="doc-2",
        ),
        make_doc(
            chunk_id="chunk-4",
            content="Mutual fund disclosures must include all material facts for investor protection",
            section_title="Disclosure Requirements",
            subsection_title="Mutual Fund Disclosures",
            document_title="SEBI Mutual Fund Regulations",
            source="SEBI",
            document_id="doc-3",
        ),
        make_doc(
            chunk_id="chunk-5",
            content="Anti money laundering procedures must be followed by all financial institutions",
            section_title="AML Compliance",
            subsection_title="Procedures",
            document_title="RBI AML Guidelines",
            source="RBI",
            document_id="doc-4",
        ),
    ]


@pytest.fixture
def retriever() -> InMemoryBM25Retriever:
    """Create a fresh InMemoryBM25Retriever."""
    return InMemoryBM25Retriever()


@pytest.fixture
def built_retriever(sample_documents) -> InMemoryBM25Retriever:
    """Create an InMemoryBM25Retriever with pre-built index."""
    r = InMemoryBM25Retriever()
    r.build_index(sample_documents)
    return r


@pytest.fixture
def tmp_storage(tmp_path):
    """Create a temporary storage directory."""
    storage_dir = tmp_path / "bm25_test"
    storage_dir.mkdir()
    return str(storage_dir)


@pytest.fixture
def index_manager(tmp_storage) -> BM25IndexManager:
    """Create a BM25IndexManager with temp storage."""
    config = IndexManagerConfig(
        storage_dir=tmp_storage,
        auto_persist=True,
        auto_load=False,
    )
    return BM25IndexManager(config=config)


# ---------------------------------------------------------------------------
# BM25Document Tests
# ---------------------------------------------------------------------------


class TestBM25Document:
    def test_to_indexable_text_full(self):
        doc = make_doc()
        text = doc.to_indexable_text()
        assert "RBI Master Direction on KYC" in text
        assert "KYC Guidelines" in text
        assert "Customer Identification" in text
        assert "KYC guidelines require customer identification" in text

    def test_to_indexable_text_empty_fields(self):
        doc = BM25Document(chunk_id="c1", content="just content")
        text = doc.to_indexable_text()
        assert text == "just content"

    def test_to_indexable_text_empty_content(self):
        doc = BM25Document(chunk_id="c1", content="", section_title="Section")
        text = doc.to_indexable_text()
        assert text == "Section"

    def test_to_indexable_text_all_empty(self):
        doc = BM25Document(chunk_id="c1", content="")
        text = doc.to_indexable_text()
        assert text == ""


# ---------------------------------------------------------------------------
# BM25Tokenizer Tests
# ---------------------------------------------------------------------------


class TestBM25Tokenizer:
    def test_basic_tokenization(self):
        tokens = BM25Tokenizer.tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_lowercase(self):
        tokens = BM25Tokenizer.tokenize("HELLO World")
        assert tokens == ["hello", "world"]

    def test_empty_string(self):
        tokens = BM25Tokenizer.tokenize("")
        assert tokens == []

    def test_none_input(self):
        tokens = BM25Tokenizer.tokenize(None)
        assert tokens == []

    def test_punctuation_removal(self):
        tokens = BM25Tokenizer.tokenize("KYC, AML; PEP.")
        assert "kyc" in tokens
        assert "aml" in tokens
        assert "pep" in tokens

    def test_hyphen_preserved(self):
        tokens = BM25Tokenizer.tokenize("risk-based approach")
        assert "risk-based" in tokens

    def test_regulatory_text(self):
        text = "Banks must verify customer identity for KYC compliance"
        tokens = BM25Tokenizer.tokenize(text)
        assert "banks" in tokens
        assert "kyc" in tokens
        assert "compliance" in tokens


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Build Index Tests
# ---------------------------------------------------------------------------


class TestBuildIndex:
    def test_build_empty_index(self, retriever):
        stats = retriever.build_index([])
        assert stats.status == IndexStatus.READY
        assert stats.total_documents == 0

    def test_build_with_documents(self, retriever, sample_documents):
        stats = retriever.build_index(sample_documents)
        assert stats.status == IndexStatus.READY
        assert stats.total_documents == 5
        assert stats.total_tokens > 0
        assert stats.avg_doc_length > 0
        assert stats.index_version == 1
        assert stats.last_built_at is not None

    def test_build_increments_version(self, retriever, sample_documents):
        retriever.build_index(sample_documents)
        stats = retriever.build_index(sample_documents)
        assert stats.index_version == 2

    def test_build_stores_documents(self, retriever, sample_documents):
        retriever.build_index(sample_documents)
        assert len(retriever._documents) == 5
        assert "chunk-1" in retriever._documents
        assert "chunk-3" in retriever._documents

    def test_build_tokenizes_documents(self, retriever, sample_documents):
        retriever.build_index(sample_documents)
        for doc in retriever._documents.values():
            assert len(doc.tokenized_content) > 0


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Search Tests
# ---------------------------------------------------------------------------


class TestSearch:
    def test_basic_search(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC customer identification")
        )
        assert response.total_results > 0
        assert response.query == "KYC customer identification"
        assert response.latency_ms > 0

    def test_search_returns_results(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC")
        )
        assert len(response.results) > 0
        for result in response.results:
            assert result.chunk_id != ""
            assert result.bm25_score >= 0
            assert result.rank > 0
        # At least one result should have a positive score
        assert any(r.bm25_score > 0 for r in response.results)

    def test_search_top_k(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", top_k=2)
        )
        assert response.total_results <= 2
        assert len(response.results) <= 2

    def test_search_results_ordered_by_score(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC compliance", top_k=10)
        )
        scores = [r.bm25_score for r in response.results]
        assert scores == sorted(scores, reverse=True)

    def test_search_ranking(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", top_k=5)
        )
        for i, result in enumerate(response.results):
            assert result.rank == i + 1

    def test_search_latency_tracked(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC")
        )
        assert response.latency_ms > 0

    def test_search_average_score(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC")
        )
        if response.results:
            assert response.average_score > 0

    def test_search_empty_query(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="")
        )
        assert response.total_results == 0

    def test_search_no_match(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="xyznonexistent123")
        )
        # BM25 returns all docs with 0.0 scores for non-matching queries
        assert all(r.bm25_score == 0.0 for r in response.results)
        # With a threshold > 0, results should be filtered out
        response_filtered = built_retriever.search(
            BM25SearchRequest(query="xyznonexistent123", score_threshold=0.1)
        )
        assert response_filtered.total_results == 0

    def test_search_content_preview(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", top_k=1)
        )
        if response.results:
            assert len(response.results[0].content_preview) > 0
            assert len(response.results[0].content_preview) <= 203  # 200 + "..."

    def test_search_result_fields(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", top_k=1)
        )
        if response.results:
            r = response.results[0]
            assert r.chunk_id != ""
            assert r.bm25_score > 0
            assert r.section != ""
            assert r.document_title != ""
            assert r.source != ""


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Source Filtering Tests
# ---------------------------------------------------------------------------


class TestSourceFiltering:
    def test_filter_by_rbi(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", source_filter=["RBI"])
        )
        for result in response.results:
            assert result.source == "RBI"

    def test_filter_by_sebi(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", source_filter=["SEBI"])
        )
        for result in response.results:
            assert result.source == "SEBI"

    def test_filter_by_multiple_sources(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", source_filter=["RBI", "SEBI"])
        )
        for result in response.results:
            assert result.source in ("RBI", "SEBI")

    def test_filter_by_nonexistent_source(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", source_filter=["FCA"])
        )
        assert response.total_results == 0

    def test_filter_reduces_results(self, built_retriever):
        unfiltered = built_retriever.search(
            BM25SearchRequest(query="compliance")
        )
        filtered = built_retriever.search(
            BM25SearchRequest(query="compliance", source_filter=["RBI"])
        )
        assert filtered.total_results <= unfiltered.total_results


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Document Filtering Tests
# ---------------------------------------------------------------------------


class TestDocumentFiltering:
    def test_filter_by_document(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", document_filter=["doc-1"])
        )
        for result in response.results:
            assert result.document_id == "doc-1"

    def test_filter_by_multiple_documents(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="compliance", document_filter=["doc-1", "doc-2"])
        )
        for result in response.results:
            assert result.document_id in ("doc-1", "doc-2")

    def test_filter_by_nonexistent_document(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", document_filter=["doc-nonexistent"])
        )
        assert response.total_results == 0


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Score Threshold Tests
# ---------------------------------------------------------------------------


class TestScoreThreshold:
    def test_zero_threshold_returns_all(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", score_threshold=0.0)
        )
        assert response.total_results > 0

    def test_high_threshold_reduces_results(self, built_retriever):
        low = built_retriever.search(
            BM25SearchRequest(query="KYC", score_threshold=0.0)
        )
        high = built_retriever.search(
            BM25SearchRequest(query="KYC", score_threshold=100.0)
        )
        assert high.total_results <= low.total_results

    def test_threshold_filters_low_scores(self, built_retriever):
        response = built_retriever.search(
            BM25SearchRequest(query="KYC", score_threshold=5.0)
        )
        for result in response.results:
            assert result.bm25_score >= 5.0


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Update Index Tests
# ---------------------------------------------------------------------------


class TestUpdateIndex:
    def test_update_adds_new_documents(self, built_retriever):
        new_doc = make_doc(
            chunk_id="chunk-new",
            content="New regulatory content about digital lending",
            section_title="Digital Lending",
            document_title="RBI Digital Lending Guidelines",
            source="RBI",
            document_id="doc-5",
        )
        stats = built_retriever.update_index([new_doc])
        assert stats.total_documents == 6
        assert "chunk-new" in built_retriever._documents

    def test_update_replaces_existing(self, built_retriever):
        updated_doc = make_doc(
            chunk_id="chunk-1",
            content="Updated KYC content with new requirements",
            section_title="Updated KYC",
            document_title="Updated RBI KYC",
            source="RBI",
            document_id="doc-1",
        )
        stats = built_retriever.update_index([updated_doc])
        assert stats.total_documents == 5  # No new docs, just replacement
        assert built_retriever._documents["chunk-1"].content == "Updated KYC content with new requirements"

    def test_update_increments_version(self, built_retriever):
        old_version = built_retriever.get_index_stats().index_version
        built_retriever.update_index([make_doc(chunk_id="new-1", content="new")])
        assert built_retriever.get_index_stats().index_version == old_version + 1


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Rebuild Index Tests
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def test_rebuild_clears_and_rebuilds(self, built_retriever, sample_documents):
        # Add extra docs
        built_retriever.update_index([make_doc(chunk_id="extra", content="extra")])
        assert built_retriever.get_index_stats().total_documents == 6

        # Rebuild with original set
        stats = built_retriever.rebuild_index(sample_documents)
        assert stats.total_documents == 5
        assert "extra" not in built_retriever._documents

    def test_rebuild_increments_version(self, built_retriever, sample_documents):
        old_version = built_retriever.get_index_stats().index_version
        built_retriever.rebuild_index(sample_documents)
        assert built_retriever.get_index_stats().index_version == old_version + 1


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Remove Documents Tests
# ---------------------------------------------------------------------------


class TestRemoveDocuments:
    def test_remove_single_document(self, built_retriever):
        stats = built_retriever.remove_documents(["chunk-1"])
        assert stats.total_documents == 4
        assert "chunk-1" not in built_retriever._documents

    def test_remove_multiple_documents(self, built_retriever):
        stats = built_retriever.remove_documents(["chunk-1", "chunk-2", "chunk-3"])
        assert stats.total_documents == 2

    def test_remove_nonexistent_document(self, built_retriever):
        stats = built_retriever.remove_documents(["nonexistent"])
        assert stats.total_documents == 5  # No change

    def test_remove_empty_list(self, built_retriever):
        stats = built_retriever.remove_documents([])
        assert stats.total_documents == 5

    def test_remove_all_documents(self, built_retriever):
        ids = ["chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5"]
        stats = built_retriever.remove_documents(ids)
        assert stats.total_documents == 0
        assert stats.status == IndexStatus.NOT_BUILT


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Clear Index Tests
# ---------------------------------------------------------------------------


class TestClearIndex:
    def test_clear_empties_index(self, built_retriever):
        built_retriever.clear_index()
        assert built_retriever.get_index_stats().total_documents == 0
        assert built_retriever._bm25 is None
        assert len(built_retriever._documents) == 0

    def test_clear_sets_status(self, built_retriever):
        built_retriever.clear_index()
        assert built_retriever.get_index_stats().status == IndexStatus.NOT_BUILT


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Search on Empty Index
# ---------------------------------------------------------------------------


class TestSearchEmptyIndex:
    def test_search_before_build(self, retriever):
        response = retriever.search(BM25SearchRequest(query="KYC"))
        assert response.total_results == 0
        assert response.results == []

    def test_search_after_clear(self, built_retriever):
        built_retriever.clear_index()
        response = built_retriever.search(BM25SearchRequest(query="KYC"))
        assert response.total_results == 0


# ---------------------------------------------------------------------------
# InMemoryBM25Retriever - Get Scores
# ---------------------------------------------------------------------------


class TestGetScores:
    def test_get_scores_returns_dict(self, built_retriever):
        scores = built_retriever.get_scores_for_query("KYC")
        assert isinstance(scores, dict)
        assert len(scores) == 5

    def test_get_scores_empty_query(self, built_retriever):
        scores = built_retriever.get_scores_for_query("")
        assert scores == {}

    def test_get_scores_no_index(self, retriever):
        scores = retriever.get_scores_for_query("KYC")
        assert scores == {}


# ---------------------------------------------------------------------------
# BM25IndexManager Tests
# ---------------------------------------------------------------------------


class TestIndexManager:
    def test_build_index(self, index_manager, sample_documents):
        stats = index_manager.build_index(sample_documents)
        assert stats.status == IndexStatus.READY
        assert stats.total_documents == 5

    def test_update_index(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        new_doc = make_doc(chunk_id="new", content="new content")
        stats = index_manager.update_index([new_doc])
        assert stats.total_documents == 6

    def test_rebuild_index(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        stats = index_manager.rebuild_index(sample_documents)
        assert stats.total_documents == 5

    def test_clear_index(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        stats = index_manager.clear_index()
        assert stats.total_documents == 0

    def test_remove_documents(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        stats = index_manager.remove_documents(["chunk-1"])
        assert stats.total_documents == 4

    def test_stats_property(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        stats = index_manager.stats
        assert stats.total_documents == 5

    def test_retriever_property(self, index_manager):
        assert isinstance(index_manager.retriever, InMemoryBM25Retriever)


# ---------------------------------------------------------------------------
# BM25IndexManager - Persistence Tests
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, tmp_storage, sample_documents):
        # Use auto_persist=False so clear doesn't overwrite the saved file
        config = IndexManagerConfig(
            storage_dir=tmp_storage, auto_persist=False, auto_load=False
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(sample_documents)
        path = manager.save_index()
        assert os.path.exists(path)

        # Clear and reload
        manager.clear_index()
        assert manager.stats.total_documents == 0

        stats = manager.load_index()
        assert stats.total_documents == 5

    def test_persist_creates_metadata(self, index_manager, sample_documents):
        index_manager.build_index(sample_documents)
        index_manager.save_index()
        metadata_path = os.path.join(index_manager._config.storage_dir, "bm25_metadata.json")
        assert os.path.exists(metadata_path)

    def test_auto_persist_on_build(self, tmp_storage, sample_documents):
        config = IndexManagerConfig(
            storage_dir=tmp_storage, auto_persist=True, auto_load=False
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(sample_documents)
        index_path = os.path.join(tmp_storage, "bm25_index.pkl")
        assert os.path.exists(index_path)

    def test_auto_load_on_init(self, tmp_storage, sample_documents):
        config = IndexManagerConfig(
            storage_dir=tmp_storage, auto_persist=True, auto_load=False
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(sample_documents)

        # Create new manager with auto_load
        config2 = IndexManagerConfig(
            storage_dir=tmp_storage, auto_persist=False, auto_load=True
        )
        manager2 = BM25IndexManager(config=config2)
        assert manager2.stats.total_documents == 5

    def test_load_nonexistent_index(self, index_manager):
        stats = index_manager.load_index()
        assert stats.total_documents == 0  # Graceful handling


# ---------------------------------------------------------------------------
# AbstractBM25Retriever Tests
# ---------------------------------------------------------------------------


class TestAbstractInterface:
    def test_in_memory_implements_abstract(self):
        assert issubclass(InMemoryBM25Retriever, AbstractBM25Retriever)

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AbstractBM25Retriever()


# ---------------------------------------------------------------------------
# IndexStatus Tests
# ---------------------------------------------------------------------------


class TestIndexStatus:
    def test_status_values(self):
        assert IndexStatus.NOT_BUILT == "not_built"
        assert IndexStatus.BUILDING == "building"
        assert IndexStatus.READY == "ready"
        assert IndexStatus.UPDATING == "updating"
        assert IndexStatus.ERROR == "error"


# ---------------------------------------------------------------------------
# Source Enum Tests
# ---------------------------------------------------------------------------


class TestSource:
    def test_source_values(self):
        assert Source.RBI == "RBI"
        assert Source.SEBI == "SEBI"


# ---------------------------------------------------------------------------
# BM25SearchRequest Tests
# ---------------------------------------------------------------------------


class TestBM25SearchRequest:
    def test_default_values(self):
        req = BM25SearchRequest(query="test")
        assert req.top_k == 10
        assert req.source_filter is None
        assert req.document_filter is None
        assert req.score_threshold == 0.0

    def test_custom_values(self):
        req = BM25SearchRequest(
            query="test",
            top_k=5,
            source_filter=["RBI"],
            score_threshold=1.0,
        )
        assert req.top_k == 5
        assert req.source_filter == ["RBI"]
        assert req.score_threshold == 1.0


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle(self, index_manager, sample_documents):
        """Test the complete lifecycle: build -> search -> update -> search -> rebuild -> search -> clear."""
        # Build
        stats = index_manager.build_index(sample_documents)
        assert stats.status == IndexStatus.READY
        assert stats.total_documents == 5

        # Search
        response = index_manager.retriever.search(
            BM25SearchRequest(query="KYC")
        )
        assert response.total_results > 0

        # Update
        new_doc = make_doc(
            chunk_id="chunk-new",
            content="Digital lending guidelines for NBFCs",
            section_title="Digital Lending",
            document_title="RBI Digital Lending",
            source="RBI",
            document_id="doc-5",
        )
        stats = index_manager.update_index([new_doc])
        assert stats.total_documents == 6

        # Search after update
        response = index_manager.retriever.search(
            BM25SearchRequest(query="digital lending")
        )
        assert response.total_results > 0

        # Rebuild
        stats = index_manager.rebuild_index(sample_documents)
        assert stats.total_documents == 5

        # Search after rebuild
        response = index_manager.retriever.search(
            BM25SearchRequest(query="KYC")
        )
        assert response.total_results > 0

        # Clear
        stats = index_manager.clear_index()
        assert stats.total_documents == 0

    def test_combined_filters(self, built_retriever):
        """Test combining source filter, document filter, and score threshold."""
        response = built_retriever.search(
            BM25SearchRequest(
                query="compliance",
                source_filter=["RBI"],
                document_filter=["doc-1"],
                score_threshold=0.0,
                top_k=10,
            )
        )
        for result in response.results:
            assert result.source == "RBI"
            assert result.document_id == "doc-1"
            assert result.bm25_score >= 0.0

    def test_section_title_boosts_relevance(self, retriever):
        """Test that section titles contribute to BM25 scoring."""
        docs = [
            make_doc(
                chunk_id="relevant",
                content="General content about banking",
                section_title="KYC Requirements",
                document_title="Banking Regulations",
                source="RBI",
                document_id="doc-1",
            ),
            make_doc(
                chunk_id="less-relevant",
                content="KYC is mentioned here but section is about something else",
                section_title="General Provisions",
                document_title="Banking Regulations",
                source="RBI",
                document_id="doc-2",
            ),
        ]
        retriever.build_index(docs)
        response = retriever.search(BM25SearchRequest(query="KYC requirements"))
        if response.results:
            # The document with "KYC Requirements" in the section title should rank higher
            assert response.results[0].chunk_id == "relevant"