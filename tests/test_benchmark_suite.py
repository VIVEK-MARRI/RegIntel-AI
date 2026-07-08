import pytest
import os
import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.core.config import settings
from app.schemas.evaluation import GoldenEvaluationItem, BenchmarkReport
from app.services.embedding.benchmark_suite import RetrievalBenchmarkRunner
from app.services.embedding.retrieval import RetrievalService
from app.models.document import Document, SourceEnum, StatusEnum
from app.services.document import DocumentService
from app.services.chunk_registry import ChunkRegistryService
from app.repositories.embedding import ChunkEmbeddingRepository

# 1. Mocking retrieval service for unit-level metric testing


class MockEmbeddingProvider:
    def get_model_name(self) -> str:
        return "mock-model"

    def get_dimension(self) -> int:
        return 3

    def encode_query(self, query: str) -> List[float]:
        return [1.0, 0.0, 0.0]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [[1.0, 0.0, 0.0]] * len(texts)


class MockRetrievalService:
    def __init__(self, responses: Dict[str, List[Dict[str, Any]]]):
        self.responses = responses
        self.embedding_provider = MockEmbeddingProvider()

    async def retrieve(
        self, query: str, top_k: int = 10, distance_metric: str = "cosine"
    ) -> Dict[str, Any]:
        results = self.responses.get(query, [])
        # Return sliced list based on top_k
        sliced_results = results[:top_k]
        return {
            "results": sliced_results,
            "trace": {
                "query": query,
                "metric": distance_metric,
                "top_k": top_k,
                "duration_ms": 12.5,
                "candidates_scanned": len(results),
            },
        }


@pytest.mark.asyncio
async def test_benchmark_metrics_math(tmp_path):
    # Prepare mock responses for two queries
    # Query 1 expects chunk1, chunk2
    # Retrieved results has:
    # - Rank 1: chunk1 (match)
    # - Rank 2: chunk3 (no match)
    # - Rank 3: chunk4 (no match)
    # - Rank 4: chunk5 (no match)
    # - Rank 5: chunk6 (no match)
    # - Rank 6: chunk2 (match)
    # - Rank 7-10: non-matching chunks
    query1_results = [
        {"chunk_id": "chunk1", "metadata": {"section": "Sec A"}},
        {"chunk_id": "chunk3", "metadata": {"section": "Sec B"}},
        {"chunk_id": "chunk4", "metadata": {"section": "Sec C"}},
        {"chunk_id": "chunk5", "metadata": {"section": "Sec D"}},
        {"chunk_id": "chunk6", "metadata": {"section": "Sec E"}},
        {"chunk_id": "chunk2", "metadata": {"section": "Sec F"}},
        {"chunk_id": "chunk7", "metadata": {"section": "Sec G"}},
        {"chunk_id": "chunk8", "metadata": {"section": "Sec H"}},
        {"chunk_id": "chunk9", "metadata": {"section": "Sec I"}},
        {"chunk_id": "chunk10", "metadata": {"section": "Sec J"}},
    ]

    # Query 2 expects chunk_xyz
    # Retrieved results has:
    # - Rank 1-5: non-matching chunks
    # - Rank 6: chunk_xyz (match)
    # - Rank 7-10: non-matching chunks
    query2_results = [
        {"chunk_id": "chunk_abc", "metadata": {"section": "Sec A"}},
        {"chunk_id": "chunk_def", "metadata": {"section": "Sec B"}},
        {"chunk_id": "chunk_ghi", "metadata": {"section": "Sec C"}},
        {"chunk_id": "chunk_jkl", "metadata": {"section": "Sec D"}},
        {"chunk_id": "chunk_mno", "metadata": {"section": "Sec E"}},
        {"chunk_id": "chunk_xyz", "metadata": {"section": "Sec F"}},
        {"chunk_id": "chunk_pqr", "metadata": {"section": "Sec G"}},
        {"chunk_id": "chunk_stu", "metadata": {"section": "Sec H"}},
        {"chunk_id": "chunk_vwx", "metadata": {"section": "Sec I"}},
        {"chunk_id": "chunk_yza", "metadata": {"section": "Sec J"}},
    ]

    responses = {"query 1": query1_results, "query 2": query2_results}

    mock_retrieval = MockRetrievalService(responses)
    runner = RetrievalBenchmarkRunner(
        retrieval_service=mock_retrieval, history_dir=str(tmp_path)
    )

    golden_dataset = [
        GoldenEvaluationItem(
            query="query 1",
            expected_chunk_ids=["chunk1", "chunk2"],
            expected_sections=[],
        ),
        GoldenEvaluationItem(
            query="query 2", expected_chunk_ids=["chunk_xyz"], expected_sections=[]
        ),
    ]

    report = await runner.run_benchmark(golden_dataset, top_k=10)

    # Assert individual query metrics
    # Query 1
    q1 = next(q for q in report.query_results if q.query == "query 1")
    assert q1.precision_at_5 == 0.2  # 1 match in top 5
    assert q1.precision_at_10 == 0.2  # 2 matches in top 10
    assert q1.recall_at_5 == 0.5  # 1 out of 2 expected
    assert q1.recall_at_10 == 1.0  # 2 out of 2 expected
    assert q1.hit_at_5 is True
    assert q1.hit_at_10 is True
    assert q1.mrr == 1.0  # First match is Rank 1

    # Query 2
    q2 = next(q for q in report.query_results if q.query == "query 2")
    assert q2.precision_at_5 == 0.0  # 0 matches in top 5
    assert q2.precision_at_10 == 0.1  # 1 match in top 10
    assert q2.recall_at_5 == 0.0  # 0 out of 1 expected
    assert q2.recall_at_10 == 1.0  # 1 out of 1 expected
    assert q2.hit_at_5 is False
    assert q2.hit_at_10 is True
    assert q2.mrr == 1.0 / 6.0  # First match is Rank 6

    # Assert aggregated metrics
    # Mean Precision@5: (0.2 + 0.0) / 2 = 0.1
    # Mean Precision@10: (0.2 + 0.1) / 2 = 0.15
    # Mean Recall@5: (0.5 + 0.0) / 2 = 0.25
    # Mean Recall@10: (1.0 + 1.0) / 2 = 1.0
    # Hit Rate@5: (1.0 + 0.0) / 2 = 0.5
    # Hit Rate@10: (1.0 + 1.0) / 2 = 1.0
    # MRR: (1.0 + 1.0/6.0) / 2 = 7/12 = 0.5833333...
    assert pytest.approx(report.metrics.mean_precision_at_5, abs=1e-5) == 0.1
    assert pytest.approx(report.metrics.mean_precision_at_10, abs=1e-5) == 0.15
    assert pytest.approx(report.metrics.mean_recall_at_5, abs=1e-5) == 0.25
    assert pytest.approx(report.metrics.mean_recall_at_10, abs=1e-5) == 1.0
    assert pytest.approx(report.metrics.hit_rate_at_5, abs=1e-5) == 0.5
    assert pytest.approx(report.metrics.hit_rate_at_10, abs=1e-5) == 1.0
    assert pytest.approx(report.metrics.mrr, abs=1e-5) == 7.0 / 12.0

    # Check that report is saved in history
    files = os.listdir(tmp_path)
    assert len(files) == 1
    assert files[0].endswith(".json")
    with open(os.path.join(tmp_path, files[0]), "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["benchmark_id"] == report.benchmark_id
        assert data["embedding_model"] == "mock-model"


@pytest.mark.asyncio
async def test_benchmark_section_fallback(tmp_path):
    # Test matching by section title fallback (case-insensitive)
    query_results = [
        {"chunk_id": "chunk_other", "metadata": {"section": "Introduction to AML/CFT"}},
        {
            "chunk_id": "chunk_target",
            "metadata": {"section": "Detailed KYC Guidelines Part II"},
        },
    ]
    responses = {"aml and kyc": query_results}
    mock_retrieval = MockRetrievalService(responses)
    runner = RetrievalBenchmarkRunner(
        retrieval_service=mock_retrieval, history_dir=str(tmp_path)
    )

    golden_dataset = [
        GoldenEvaluationItem(
            query="aml and kyc",
            expected_chunk_ids=["chunk_not_returned"],
            expected_sections=[
                "KYC Guidelines"
            ],  # case-insensitive substring of "Detailed KYC Guidelines Part II"
        )
    ]

    report = await runner.run_benchmark(golden_dataset, top_k=2)
    q_res = report.query_results[0]

    # "Detailed KYC Guidelines Part II" matches "KYC Guidelines" -> Rank 2 (index 1)
    assert q_res.hit_at_5 is True
    assert q_res.mrr == 0.5
    assert q_res.precision_at_5 == 0.2  # 1 match in top 5
    assert (
        q_res.recall_at_5 == 1.0
    )  # 1 out of 1 expected (max(len(expected_chunk_ids), len(expected_sections)) = 1)


@pytest.mark.asyncio
async def test_benchmark_history_and_comparison(tmp_path):
    # Verify get_history and comparison markdown report generation
    responses = {"q": []}
    mock_retrieval = MockRetrievalService(responses)
    runner = RetrievalBenchmarkRunner(
        retrieval_service=mock_retrieval, history_dir=str(tmp_path)
    )

    golden_dataset = [
        GoldenEvaluationItem(
            query="q", expected_chunk_ids=["chunk_none"], expected_sections=[]
        )
    ]

    report1 = await runner.run_benchmark(golden_dataset, top_k=5)

    import asyncio

    await asyncio.sleep(1.1)

    report2 = await runner.run_benchmark(golden_dataset, top_k=5)

    history = runner.get_history()
    assert len(history) == 2
    assert any(h.benchmark_id == report1.benchmark_id for h in history)
    assert any(h.benchmark_id == report2.benchmark_id for h in history)

    comparison_md = runner.generate_comparison_report(history)
    assert "# Retrieval Benchmark Comparison Report" in comparison_md
    assert "mock-model" in comparison_md
    assert "MRR" in comparison_md


# 2. Integration Test using real DB Session + actual RetrievalService


@pytest.mark.asyncio
async def test_integration_benchmark_flow(db_session, tmp_path):
    # Setup standard database services
    doc_service = DocumentService(db_session)
    chunk_service = ChunkRegistryService(db_session, doc_service)

    # Use a custom 3d model embedding provider
    class CustomMockEmbeddingProvider:
        def get_model_name(self) -> str:
            return "integration-3d-model"

        def get_dimension(self) -> int:
            return 3

        def encode_query(self, query: str) -> list[float]:
            # Simple query-to-vector routing for test
            if "KYC" in query:
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0]

        def encode_batch(self, texts: list[str]) -> list[list[float]]:
            # Mock implementation
            results = []
            for t in texts:
                if "KYC" in t:
                    results.append([1.0, 0.0, 0.0])
                else:
                    results.append([0.0, 1.0, 0.0])
            return results

    mock_provider = CustomMockEmbeddingProvider()
    retrieval_service = RetrievalService(db_session, mock_provider)
    runner = RetrievalBenchmarkRunner(retrieval_service, history_dir=str(tmp_path))

    # Add test documents
    doc = Document(
        title="RBI Circular",
        source=SourceEnum.RBI,
        file_name="circular.pdf",
        file_path="RBI/circular.pdf",
        checksum="c" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # Add test chunks
    chunks_data = [
        {
            "content": "This is KYC Guidelines details",
            "section": "KYC Sect",
            "subsection": "",
            "page_number": 1,
            "token_count": 10,
        },
        {
            "content": "This is General Information details",
            "section": "Gen Sect",
            "subsection": "",
            "page_number": 2,
            "token_count": 12,
        },
    ]
    registered_chunks = await chunk_service.register_chunks_bulk(doc.id, chunks_data)
    chunk_kyc = registered_chunks[0]
    chunk_gen = registered_chunks[1]

    # Save embeddings
    repo = ChunkEmbeddingRepository(db_session)
    await repo.save_embedding(
        chunk_id=chunk_kyc.id,
        embedding=[1.0, 0.0, 0.0],
        embedding_model="integration-3d-model",
        embedding_dimension=3,
    )
    await repo.save_embedding(
        chunk_id=chunk_gen.id,
        embedding=[0.0, 1.0, 0.0],
        embedding_model="integration-3d-model",
        embedding_dimension=3,
    )
    await db_session.commit()

    # Define golden dataset
    golden_dataset = [
        GoldenEvaluationItem(
            query="Tell me about KYC",
            expected_chunk_ids=[str(chunk_kyc.id)],
            expected_sections=[],
        ),
        GoldenEvaluationItem(
            query="Give me General section details",
            expected_chunk_ids=[str(chunk_gen.id)],
            expected_sections=[],
        ),
    ]

    # Run Benchmark
    report = await runner.run_benchmark(golden_dataset, top_k=5)

    # Verify report results
    assert len(report.query_results) == 2
    assert report.embedding_model == "integration-3d-model"
    assert report.embedding_dimension == 3

    # Mean Recall should be 1.0 because both queries retrieve their exact target at rank 1
    assert report.metrics.mean_recall_at_5 == 1.0
    assert report.metrics.mrr == 1.0
    assert report.metrics.hit_rate_at_5 == 1.0

    # Cleanup
    await doc_service.repository.delete(doc)
    await db_session.commit()
