import pytest
import time
import os
import numpy as np
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.bm25.service import BM25IndexManager, BM25RetrieverService


@pytest.mark.asyncio
async def test_bm25_benchmarks(db_session, tmp_path):
    """Benchmark script to measure BM25 retrieval speeds under different scenarios."""
    print("\n" + "=" * 50)
    print("STARTING BM25 RETRIEVAL BENCHMARKS")
    print("=" * 50)

    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)

    # 2. Create mock document and chunks
    doc = Document(
        title="BM25 Performance Benchmark circular",
        source=SourceEnum.RBI,
        file_name="benchmark_bm25.pdf",
        file_path="RBI/benchmark_bm25.pdf",
        checksum="w" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # Generate 50 chunks with repeating keywords to score
    chunks_data = [
        {
            "content": f"Passage content number {i} for benchmarking keyword retrieval speeds. KYC guidelines diligence.",
            "section": f"Section {i // 10}",
            "subsection": "",
            "page_number": i // 5 + 1,
            "token_count": 15,
        }
        for i in range(50)
    ]
    await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    await db_session.commit()

    # 3. Build active BM25 index
    manager = BM25IndexManager(db_session, storage_dir=str(tmp_path))
    await manager.build_index("benchmark_bm25_run")

    retriever = BM25RetrieverService(db_session)

    # 4. Define benchmarking runner function
    async def run_benchmark_set(
        name: str, query: str, filters: dict, num_runs: int = 100
    ):
        latencies = []
        for i in range(num_runs):
            t_start = time.perf_counter()
            res = await retriever.retrieve(query=query, top_k=5, **filters)
            latencies.append((time.perf_counter() - t_start) * 1000)

        avg_lat = np.mean(latencies)
        p95_lat = np.percentile(latencies, 95)
        p99_lat = np.percentile(latencies, 99)
        qps = 1000.0 / avg_lat

        print(f"Scenario: {name}")
        print(f"  Query: '{query}' | Runs: {num_runs}")
        print(f"  Avg Latency: {avg_lat:.2f} ms")
        print(f"  P95 Latency: {p95_lat:.2f} ms | P99 Latency: {p99_lat:.2f} ms")
        print(f"  Estimated QPS: {qps:.1f} queries/sec")
        print("-" * 40)

        return {
            "scenario": name,
            "query": query,
            "avg_ms": avg_lat,
            "p95_ms": p95_lat,
            "p99_ms": p99_lat,
            "qps": qps,
        }

    # 5. Execute scenarios
    results = []

    # Scenario A: BM25 Query, No Filters
    results.append(
        await run_benchmark_set("BM25 Keyword Search (Unfiltered)", "KYC diligence", {})
    )

    # Scenario B: BM25 Query, Source Filter
    results.append(
        await run_benchmark_set(
            "BM25 Keyword Search (Source Filter)",
            "KYC guidelines",
            {"source": SourceEnum.RBI},
        )
    )

    # Scenario C: BM25 Query, Document Filter
    results.append(
        await run_benchmark_set(
            "BM25 Keyword Search (Doc Filter)",
            "speed benchmark",
            {"document_id": doc.id},
        )
    )

    # Scenario D: BM25 Query, Score Threshold Filter
    results.append(
        await run_benchmark_set(
            "BM25 Keyword Search (Threshold Filter)",
            "KYC diligence",
            {"score_threshold": 1.0},
        )
    )

    # Print Markdown Summary
    print("\n" + "=" * 50)
    print("BM25 RETRIEVAL BENCHMARK SUMMARY")
    print("=" * 50)
    print("| Scenario | Query | Avg Latency (ms) | P95 (ms) | P99 (ms) | Est. QPS |")
    print("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        print(
            f"| {r['scenario']} | {r['query']} | {r['avg_ms']:.2f} | {r['p95_ms']:.2f} | {r['p99_ms']:.2f} | {r['qps']:.1f} |"
        )
    print("=" * 50 + "\n")

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
