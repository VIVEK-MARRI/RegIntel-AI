import pytest
import time
import uuid
import numpy as np
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.chunk import DocumentChunk, ChunkEmbedding, EmbeddingStatusEnum
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding.retrieval import RetrievalService
from app.repositories.embedding import ChunkEmbeddingRepository


@pytest.mark.asyncio
async def test_retrieval_benchmarks(db_session):
    """Benchmark script to measure semantic retrieval speeds under different scenarios."""
    print("\n" + "=" * 50)
    print("STARTING RETRIEVAL BENCHMARKS")
    print("=" * 50)

    # 1. Setup services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)
    repo = ChunkEmbeddingRepository(db_session)

    # 2. Setup mock embedding provider
    class BenchmarkEmbeddingProvider:
        def get_model_name(self) -> str:
            return "benchmark-model"

        def get_dimension(self) -> int:
            return 384

        def encode_query(self, query: str) -> list[float]:
            # Mock query vector
            v = np.zeros(384)
            v[0] = 1.0
            return v.tolist()

        def encode_batch(self, texts: list[str]) -> list[list[float]]:
            res = []
            for _ in texts:
                v = np.zeros(384)
                v[0] = 1.0
                res.append(v.tolist())
            return res

    provider = BenchmarkEmbeddingProvider()
    retrieval_service = RetrievalService(db_session, provider)

    # 3. Create mock document and chunks
    doc = Document(
        title="Benchmark Doc",
        source=SourceEnum.RBI,
        file_name="benchmark.pdf",
        file_path="RBI/benchmark.pdf",
        checksum="z" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # Generate 50 chunks
    chunks_data = [
        {
            "content": f"Passage content number {i} for benchmarking retrieval speeds.",
            "section": f"Section {i // 10}",
            "subsection": "",
            "page_number": i // 5 + 1,
            "token_count": 15,
        }
        for i in range(50)
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)

    # Save mock embeddings for all 50 chunks
    embeddings_list = []
    for idx, c in enumerate(registered_chunks):
        # We vary vectors slightly so they don't all have the same distance
        vec = np.zeros(384)
        vec[0] = 1.0 - (idx * 0.01)
        vec[1] = idx * 0.01
        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        embeddings_list.append(
            {
                "chunk_id": c.id,
                "embedding": vec.tolist(),
                "embedding_model": "benchmark-model",
                "embedding_dimension": 384,
                "status": EmbeddingStatusEnum.COMPLETED,
                "error_message": None,
            }
        )
    await repo.save_embeddings_bulk(embeddings_list)
    await db_session.commit()

    # 4. Define benchmarking functions
    async def run_benchmark_set(
        name: str, metric: str, filters: dict, num_runs: int = 30
    ):
        latencies = []
        for i in range(num_runs):
            t_start = time.perf_counter()
            res = await retrieval_service.retrieve(
                query=f"benchmarking search query {i}",
                top_k=5,
                distance_metric=metric,
                **filters,
            )
            latencies.append((time.perf_counter() - t_start) * 1000)

        avg_lat = np.mean(latencies)
        p95_lat = np.percentile(latencies, 95)
        p99_lat = np.percentile(latencies, 99)
        qps = 1000.0 / avg_lat

        print(f"Scenario: {name}")
        print(f"  Metric: {metric} | Runs: {num_runs}")
        print(f"  Avg Latency: {avg_lat:.2f} ms")
        # Print P95 and P99
        print(f"  P95 Latency: {p95_lat:.2f} ms | P99 Latency: {p99_lat:.2f} ms")
        print(f"  Estimated QPS: {qps:.1f} queries/sec")
        print("-" * 40)
        return {
            "scenario": name,
            "metric": metric,
            "avg_ms": avg_lat,
            "p95_ms": p95_lat,
            "p99_ms": p99_lat,
            "qps": qps,
        }

    # 5. Execute benchmarks
    results = []

    # Scenario A: Cosine Similarity, No Filters
    results.append(await run_benchmark_set("Cosine Search (Unfiltered)", "cosine", {}))

    # Scenario B: Cosine Similarity, Document Filter
    results.append(
        await run_benchmark_set(
            "Cosine Search (Doc Filter)", "cosine", {"document_id": doc.id}
        )
    )

    # Scenario C: Inner Product, No Filters
    results.append(await run_benchmark_set("Dot Product (Unfiltered)", "ip", {}))

    # Scenario D: L2 Distance, No Filters
    results.append(await run_benchmark_set("L2 Euclidean (Unfiltered)", "l2", {}))

    # Print Markdown Summary
    print("\n" + "=" * 50)
    print("BENCHMARK SUMMARY")
    print("=" * 50)
    print("| Scenario | Metric | Avg Latency (ms) | P95 (ms) | P99 (ms) | Est. QPS |")
    print("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        print(
            f"| {r['scenario']} | {r['metric']} | {r['avg_ms']:.2f} | {r['p95_ms']:.2f} | {r['p99_ms']:.2f} | {r['qps']:.1f} |"
        )
    print("=" * 50 + "\n")

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
