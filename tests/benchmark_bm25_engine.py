"""
BM25 Retrieval Engine Benchmark Suite.

Benchmarks:
- Index build time vs corpus size
- Search latency vs corpus size
- Filter performance
- Memory usage
- Score distribution analysis

Run with: python -m pytest tests/benchmark_bm25_engine.py -v -s
"""

from __future__ import annotations

import random
import string
import statistics
import time
from typing import List, Dict, Tuple

import pytest

from app.services.bm25.retriever import (
    BM25Document,
    BM25SearchRequest,
    InMemoryBM25Retriever,
    BM25Tokenizer,
)
from app.services.bm25.index_manager import BM25IndexManager, IndexManagerConfig


# ---------------------------------------------------------------------------
# Benchmark Data Generators
# ---------------------------------------------------------------------------

REGULATORY_TERMS = [
    "KYC", "AML", "PEP", "CDD", "EDD", "risk", "compliance", "regulation",
    "banking", "securities", "mutual fund", "stock exchange", "disclosure",
    "surveillance", "enforcement", "penalty", "governance", "audit",
    "reporting", "monitoring", "assessment", "classification", "verification",
    "identification", "authentication", "authorization", "documentation",
    "due diligence", "customer", "investor", "financial institution",
    "non-banking", "NBFC", "housing finance", "credit", "lending",
    "borrowing", "capital", "liquidity", "solvency", "provision",
    "reserve", "ratio", "limit", "threshold", "exemption", "waiver",
]

SECTION_TEMPLATES = [
    "Section {num}: {title}",
    "Chapter {num}: {title}",
    "Part {num}: {title}",
    "Article {num}: {title}",
]

DOCUMENT_TITLES = [
    "RBI Master Direction on {topic}",
    "SEBI (Regulation) Act - {topic}",
    "RBI Guidelines for {topic}",
    "SEBI Circular on {topic}",
    "RBI Notification: {topic}",
    "SEBI Framework for {topic}",
]

TOPICS = [
    "KYC Compliance", "AML Standards", "Risk Management", "Governance",
    "Disclosure Requirements", "Investor Protection", "Market Surveillance",
    "Capital Adequacy", "Liquidity Management", "Credit Risk",
    "Operational Risk", "Cyber Security", "Data Protection",
    "Consumer Protection", "Fair Practices", "Transparency",
]


def _random_sentence(num_terms: int = 8) -> str:
    """Generate a random regulatory-sounding sentence."""
    terms = random.sample(REGULATORY_TERMS, min(num_terms, len(REGULATORY_TERMS)))
    # Add some filler words
    fillers = ["shall", "must", "should", "may", "will", "is required to", "needs to"]
    parts = []
    for i, term in enumerate(terms):
        if i == 0:
            parts.append(f"Financial institutions {random.choice(fillers)} {term.lower()}")
        else:
            parts.append(term.lower())
    return " ".join(parts) + "."


def _random_paragraph(num_sentences: int = 5) -> str:
    """Generate a random paragraph."""
    return " ".join(_random_sentence() for _ in range(num_sentences))


def generate_benchmark_documents(
    count: int,
    source_ratio: float = 0.5,
) -> List[BM25Document]:
    """Generate synthetic regulatory documents for benchmarking."""
    random.seed(42)  # Reproducible
    documents = []

    for i in range(count):
        source = "RBI" if random.random() < source_ratio else "SEBI"
        topic = random.choice(TOPICS)
        doc_title = random.choice(DOCUMENT_TITLES).format(topic=topic)
        section_title = random.choice(SECTION_TEMPLATES).format(
            num=random.randint(1, 20),
            title=topic,
        )
        subsection_title = f"Subsection {random.randint(1, 5)}: {random.choice(REGULATORY_TERMS)}"

        content = _random_paragraph(random.randint(3, 10))

        documents.append(
            BM25Document(
                chunk_id=f"chunk-{i:06d}",
                content=content,
                section_title=section_title,
                subsection_title=subsection_title,
                document_title=doc_title,
                source=source,
                document_id=f"doc-{i // 10:04d}",
                page_number=random.randint(1, 100),
            )
        )

    return documents


# ---------------------------------------------------------------------------
# Benchmark Queries
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES = [
    "KYC compliance requirements",
    "AML customer due diligence",
    "risk management framework",
    "mutual fund disclosure",
    "stock exchange surveillance",
    "capital adequacy ratio",
    "investor protection measures",
    "cyber security guidelines",
    "credit risk assessment",
    "governance standards",
]


# ---------------------------------------------------------------------------
# Benchmark: Index Build Performance
# ---------------------------------------------------------------------------


class TestBenchmarkIndexBuild:
    """Benchmark index build time for various corpus sizes."""

    @pytest.mark.parametrize("corpus_size", [100, 500, 1000, 5000])
    def test_build_time(self, corpus_size, tmp_path):
        """Measure index build time for different corpus sizes."""
        documents = generate_benchmark_documents(corpus_size)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / f"bench_{corpus_size}"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)

        start = time.monotonic()
        stats = manager.build_index(documents)
        elapsed_ms = (time.monotonic() - start) * 1000

        print(f"\n[BUILD] Corpus: {corpus_size:>6d} | "
              f"Time: {elapsed_ms:>10.1f} ms | "
              f"Tokens: {stats.total_tokens:>8d} | "
              f"Avg Doc Len: {stats.avg_doc_length:>8.1f}")

        assert stats.total_documents == corpus_size
        assert elapsed_ms < 60_000  # Should complete within 60 seconds


# ---------------------------------------------------------------------------
# Benchmark: Search Latency
# ---------------------------------------------------------------------------


class TestBenchmarkSearchLatency:
    """Benchmark search latency for various corpus sizes and query types."""

    @pytest.mark.parametrize("corpus_size", [100, 500, 1000, 5000])
    def test_search_latency_basic(self, corpus_size, tmp_path):
        """Measure basic search latency."""
        documents = generate_benchmark_documents(corpus_size)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / f"search_{corpus_size}"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        latencies = []
        for query in BENCHMARK_QUERIES:
            response = manager.retriever.search(
                BM25SearchRequest(query=query, top_k=10)
            )
            latencies.append(response.latency_ms)

        avg_latency = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0]
        max_latency = max(latencies)

        print(f"\n[SEARCH] Corpus: {corpus_size:>6d} | "
              f"Avg: {avg_latency:>8.2f} ms | "
              f"P50: {p50:>8.2f} ms | "
              f"P95: {p95:>8.2f} ms | "
              f"Max: {max_latency:>8.2f} ms")

        # Search should be fast even for large corpora
        assert avg_latency < 1000, f"Average search latency {avg_latency}ms exceeds 1000ms"

    @pytest.mark.parametrize("top_k", [1, 5, 10, 25, 50, 100])
    def test_search_latency_vs_top_k(self, top_k, tmp_path):
        """Measure search latency for different top_k values."""
        documents = generate_benchmark_documents(1000)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / f"topk_{top_k}"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        response = manager.retriever.search(
            BM25SearchRequest(query="KYC compliance", top_k=top_k)
        )

        print(f"\n[TOP-K] k: {top_k:>4d} | "
              f"Latency: {response.latency_ms:>8.2f} ms | "
              f"Results: {response.total_results:>4d}")

        assert response.total_results <= top_k


# ---------------------------------------------------------------------------
# Benchmark: Filter Performance
# ---------------------------------------------------------------------------


class TestBenchmarkFilters:
    """Benchmark filtering performance."""

    def test_source_filter_overhead(self, tmp_path):
        """Compare search with and without source filter."""
        documents = generate_benchmark_documents(5000)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / "filter_overhead"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        # Unfiltered
        start = time.monotonic()
        for _ in range(100):
            manager.retriever.search(
                BM25SearchRequest(query="KYC compliance", top_k=10)
            )
        unfiltered_ms = (time.monotonic() - start) * 1000 / 100

        # Filtered
        start = time.monotonic()
        for _ in range(100):
            manager.retriever.search(
                BM25SearchRequest(
                    query="KYC compliance",
                    top_k=10,
                    source_filter=["RBI"],
                )
            )
        filtered_ms = (time.monotonic() - start) * 1000 / 100

        overhead_pct = ((filtered_ms - unfiltered_ms) / unfiltered_ms) * 100

        print(f"\n[FILTER] Unfiltered: {unfiltered_ms:.2f} ms | "
              f"Filtered: {filtered_ms:.2f} ms | "
              f"Overhead: {overhead_pct:+.1f}%")

    def test_score_threshold_filter(self, tmp_path):
        """Measure impact of score threshold on result count."""
        documents = generate_benchmark_documents(1000)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / "threshold"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        thresholds = [0.0, 1.0, 5.0, 10.0, 20.0]
        for threshold in thresholds:
            response = manager.retriever.search(
                BM25SearchRequest(
                    query="KYC compliance",
                    top_k=100,
                    score_threshold=threshold,
                )
            )
            print(f"\n[THRESHOLD] threshold={threshold:>6.1f} | "
                  f"results={response.total_results:>4d} | "
                  f"filtered={response.filtered_count:>6d} | "
                  f"avg_score={response.average_score:.4f}")


# ---------------------------------------------------------------------------
# Benchmark: Score Distribution
# ---------------------------------------------------------------------------


class TestBenchmarkScoreDistribution:
    """Analyze BM25 score distributions."""

    def test_score_distribution(self, tmp_path):
        """Analyze score distribution for various queries."""
        documents = generate_benchmark_documents(1000)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / "scores"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        for query in BENCHMARK_QUERIES[:5]:
            response = manager.retriever.search(
                BM25SearchRequest(query=query, top_k=100)
            )
            if response.results:
                scores = [r.bm25_score for r in response.results]
                print(f"\n[SCORES] Query: {query!r}")
                print(f"  Count: {len(scores)}")
                print(f"  Min: {min(scores):.4f}")
                print(f"  Max: {max(scores):.4f}")
                print(f"  Mean: {statistics.mean(scores):.4f}")
                if len(scores) > 1:
                    print(f"  Stdev: {statistics.stdev(scores):.4f}")


# ---------------------------------------------------------------------------
# Benchmark: Update Performance
# ---------------------------------------------------------------------------


class TestBenchmarkUpdate:
    """Benchmark index update performance."""

    @pytest.mark.parametrize("update_size", [1, 10, 50, 100, 500])
    def test_update_latency(self, update_size, tmp_path):
        """Measure update latency for different batch sizes."""
        documents = generate_benchmark_documents(1000)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / f"update_{update_size}"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        new_docs = generate_benchmark_documents(update_size)
        # Make IDs unique
        for i, doc in enumerate(new_docs):
            doc.chunk_id = f"update-{update_size}-{i:06d}"

        start = time.monotonic()
        stats = manager.update_index(new_docs)
        elapsed_ms = (time.monotonic() - start) * 1000

        print(f"\n[UPDATE] Batch: {update_size:>5d} | "
              f"Time: {elapsed_ms:>10.1f} ms | "
              f"Total Docs: {stats.total_documents:>6d}")

        assert stats.total_documents == 1000 + update_size


# ---------------------------------------------------------------------------
# Benchmark: Persistence
# ---------------------------------------------------------------------------


class TestBenchmarkPersistence:
    """Benchmark save/load performance."""

    @pytest.mark.parametrize("corpus_size", [100, 1000, 5000])
    def test_save_load_performance(self, corpus_size, tmp_path):
        """Measure save and load times."""
        documents = generate_benchmark_documents(corpus_size)
        config = IndexManagerConfig(
            storage_dir=str(tmp_path / f"persist_{corpus_size}"),
            auto_persist=False,
            auto_load=False,
        )
        manager = BM25IndexManager(config=config)
        manager.build_index(documents)

        # Save
        start = time.monotonic()
        path = manager.save_index()
        save_ms = (time.monotonic() - start) * 1000

        # Clear
        manager.clear_index()

        # Load
        start = time.monotonic()
        stats = manager.load_index()
        load_ms = (time.monotonic() - start) * 1000

        print(f"\n[PERSIST] Corpus: {corpus_size:>6d} | "
              f"Save: {save_ms:>10.1f} ms | "
              f"Load: {load_ms:>10.1f} ms")

        assert stats.total_documents == corpus_size


# ---------------------------------------------------------------------------
# Benchmark: Tokenizer Performance
# ---------------------------------------------------------------------------


class TestBenchmarkTokenizer:
    """Benchmark tokenizer performance."""

    def test_tokenizer_throughput(self):
        """Measure tokenizer throughput."""
        texts = [_random_paragraph(10) for _ in range(1000)]

        start = time.monotonic()
        for text in texts:
            BM25Tokenizer.tokenize(text)
        elapsed_ms = (time.monotonic() - start) * 1000

        print(f"\n[TOKENIZER] 1000 texts in {elapsed_ms:.1f} ms "
              f"({1000 / (elapsed_ms / 1000):.0f} texts/sec)")

        assert elapsed_ms < 5000  # Should be fast


# ---------------------------------------------------------------------------
# Summary Report
# ---------------------------------------------------------------------------


class TestBenchmarkSummary:
    """Generate a comprehensive benchmark summary report."""

    def test_full_benchmark_report(self, tmp_path):
        """Run a comprehensive benchmark and print a summary report."""
        print("\n" + "=" * 80)
        print("  BM25 RETRIEVAL ENGINE - BENCHMARK REPORT")
        print("=" * 80)

        corpus_sizes = [100, 500, 1000, 2000, 5000]
        build_times = []
        search_latencies = []

        for size in corpus_sizes:
            documents = generate_benchmark_documents(size)
            config = IndexManagerConfig(
                storage_dir=str(tmp_path / f"report_{size}"),
                auto_persist=False,
                auto_load=False,
            )
            manager = BM25IndexManager(config=config)

            # Build benchmark
            start = time.monotonic()
            stats = manager.build_index(documents)
            build_ms = (time.monotonic() - start) * 1000
            build_times.append(build_ms)

            # Search benchmark
            query_latencies = []
            for query in BENCHMARK_QUERIES:
                response = manager.retriever.search(
                    BM25SearchRequest(query=query, top_k=10)
                )
                query_latencies.append(response.latency_ms)
            avg_search = statistics.mean(query_latencies)
            search_latencies.append(avg_search)

        # Print report
        print(f"\n{'Corpus Size':>12} | {'Build (ms)':>12} | {'Avg Search (ms)':>16} | {'Docs/ms':>10}")
        print("-" * 60)
        for i, size in enumerate(corpus_sizes):
            docs_per_ms = size / build_times[i] if build_times[i] > 0 else 0
            print(f"{size:>12,d} | {build_times[i]:>12.1f} | {search_latencies[i]:>16.2f} | {docs_per_ms:>10.2f}")

        print("\n" + "-" * 60)
        print("SCALABILITY ANALYSIS:")
        if len(build_times) >= 2:
            ratio_size = corpus_sizes[-1] / corpus_sizes[0]
            ratio_time = build_times[-1] / build_times[0] if build_times[0] > 0 else 0
            print(f"  Corpus size ratio (max/min): {ratio_size:.1f}x")
            print(f"  Build time ratio (max/min): {ratio_time:.1f}x")
            print(f"  Build scales roughly as O(n^{ratio_time / ratio_size:.2f})"
                  if ratio_size > 0 else "  N/A")

        print("\n" + "=" * 80)
        print("  END OF BENCHMARK REPORT")
        print("=" * 80 + "\n")