"""Module 4.8 — End-to-end API tests for the Hybrid Search API Layer.

Covers:

* ``POST /api/v1/search/dense``
* ``POST /api/v1/search/bm25``
* ``POST /api/v1/search/hybrid``
* ``GET  /api/v1/retrieval/metrics``
* ``GET  /api/v1/retrieval/health``

The test suite reuses the production service layer; it never duplicates
business logic.  ``EmbeddingProvider``, ``BM25Service``, ``RerankerService``
and ``AnalyticsService`` are exercised through real DI overrides, with
mock classes standing in only where external resources (real BGE model,
real embedding model) would otherwise be required.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.dependencies import (
    get_bm25_service,
    get_reranker_service,
    reset_bm25_service,
)
from app.main import app
from app.api.dependencies import get_embedding_provider
from app.models.chunk import DocumentChunk
from app.models.document import Document, SourceEnum, StatusEnum
from app.repositories.embedding import ChunkEmbeddingRepository
from app.schemas.analytics import RetrievalMetricsCreate
from app.services.analytics.service import AnalyticsService
from app.services.bm25.bm25_service import BM25Service
from app.services.bm25.retriever import (
    BM25Document,
    IndexStatus,
)


# ─── Mock Embedding Provider ──────────────────────────────────────────────────


class MockEmbeddingProvider:
    """Deterministic 3-D embedding provider used across the suite."""

    def get_model_name(self) -> str:
        return "module48-mock"

    def get_dimension(self) -> int:
        return 3

    def encode_query(self, query: str) -> List[float]:
        if "kyc" in query.lower():
            return [1.0, 0.0, 0.0]
        if "mutual" in query.lower() or "fund" in query.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode_query(t) for t in texts]


# ─── Mock Reranker Service ────────────────────────────────────────────────────


class MockRerankerService:
    """Stub reranker used when we want to control rerank output deterministically."""

    def __init__(self) -> None:
        self.default_top_k = 5
        self.default_score_threshold = 0.0
        self.calls: List[str] = []

    def rerank(self, query, candidates, *, top_k=None, score_threshold=None):
        from app.schemas.reranker import (
            PrecisionMetrics,
            RerankReport,
            RerankResponse,
            RerankResult,
            ScoreDistribution,
        )

        self.calls.append(query)
        effective_top_k = top_k or self.default_top_k
        scored = []
        for idx, cand in enumerate(candidates):
            scored.append(
                {
                    **cand,
                    "rerank_score": max(0.0, 1.0 - 0.05 * idx),
                    "original_rank": idx + 1,
                }
            )
        scored.sort(key=lambda c: (-c["rerank_score"], c["chunk_id"]))
        top = scored[:effective_top_k]
        results = [
            RerankResult(
                chunk_id=c["chunk_id"],
                rerank_score=c["rerank_score"],
                original_score=c.get("score"),
                original_rank=c.get("original_rank"),
                new_rank=idx + 1,
                content=c.get("content", ""),
                metadata=c.get("metadata") or {},
            )
            for idx, c in enumerate(top)
        ]
        report = RerankReport(
            model_name="mock-reranker",
            candidates_received=len(candidates),
            candidates_returned=len(results),
            candidates_filtered=0,
            latency_ms=1.0,
            scoring_latency_ms=1.0,
            score_distribution=ScoreDistribution(),
            precision_metrics=PrecisionMetrics(),
        )
        return RerankResponse(query=query, results=results, report=report)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_embedding_provider():
    app.dependency_overrides[get_embedding_provider] = lambda: MockEmbeddingProvider()
    yield
    app.dependency_overrides.pop(get_embedding_provider, None)


@pytest.fixture(autouse=True)
def reset_bm25_singleton():
    reset_bm25_service()
    yield
    reset_bm25_service()
    app.dependency_overrides.pop(get_bm25_service, None)
    app.dependency_overrides.pop(get_reranker_service, None)


@pytest_asyncio.fixture
async def seeded_corpus(db_session, tmp_path):
    """Create documents + chunks + embeddings, and populate the BM25 in-memory index.

    Yields a dict containing the created objects so individual tests can
    assert against specific chunk / document ids.  A unique checksum suffix
    is used so multiple test invocations do not collide with prior data
    left in the test database.
    """
    suffix = uuid.uuid4().hex[:8]
    doc_rbi = Document(
        title="RBI KYC Master Circular",
        source=SourceEnum.RBI,
        file_name=f"rbi_kyc_{suffix}.pdf",
        file_path=f"RBI/rbi_kyc_{suffix}.pdf",
        checksum=("a" * 55) + suffix,
        status=StatusEnum.UPLOADED,
    )
    doc_sebi = Document(
        title="SEBI Mutual Fund Guidelines",
        source=SourceEnum.SEBI,
        file_name=f"sebi_mf_{suffix}.pdf",
        file_path=f"SEBI/sebi_mf_{suffix}.pdf",
        checksum=("b" * 55) + suffix,
        status=StatusEnum.UPLOADED,
    )
    db_session.add_all([doc_rbi, doc_sebi])
    await db_session.commit()

    chunks = [
        DocumentChunk(
            document_id=doc_rbi.id,
            page_number=1,
            section="KYC",
            subsection="Customer Identification",
            content="KYC verification requires Aadhaar card and PAN card details for diligence.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_rbi.id,
            page_number=2,
            section="KYC",
            subsection="Customer Due Diligence",
            content="Customer due diligence process should be completed within ten working days.",
            token_count=20,
        ),
        DocumentChunk(
            document_id=doc_sebi.id,
            page_number=1,
            section="Mutual Funds",
            subsection="Asset Allocation",
            content="Mutual fund investment schemes must clearly disclose equity allocation details.",
            token_count=20,
        ),
    ]
    db_session.add_all(chunks)
    await db_session.commit()

    repo = ChunkEmbeddingRepository(db_session)
    embeddings = [
        (chunks[0], [1.0, 0.0, 0.0]),
        (chunks[1], [1.0, 0.0, 0.0]),
        (chunks[2], [0.0, 1.0, 0.0]),
    ]
    for chunk, emb in embeddings:
        await repo.save_embedding(
            chunk_id=chunk.id,
            embedding=emb,
            embedding_model="module48-mock",
            embedding_dimension=3,
        )
    await db_session.commit()

    # Build BM25 in-memory index directly (skip disk persistence for tests).
    bm25_service: BM25Service = get_bm25_service()
    bm25_service.clear_index()
    bm25_docs = [
        BM25Document(
            chunk_id=str(c.id),
            content=c.content,
            section_title=c.section or "",
            subsection_title=c.subsection or "",
            document_title=(
                doc_rbi.title if c.document_id == doc_rbi.id else doc_sebi.title
            ),
            source=(
                SourceEnum.RBI.value
                if c.document_id == doc_rbi.id
                else SourceEnum.SEBI.value
            ),
            document_id=str(c.document_id),
            page_number=c.page_number or 0,
        )
        for c in chunks
    ]
    bm25_service._retriever.build_index(bm25_docs)  # noqa: SLF001

    yield {
        "db": db_session,
        "doc_rbi": doc_rbi,
        "doc_sebi": doc_sebi,
        "chunks": chunks,
    }


# ─── Dense Search ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dense_search_success(client: AsyncClient, seeded_corpus) -> None:
    response = await client.post(
        "/api/v1/search/dense",
        json={"query": "KYC diligence", "top_k": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "KYC diligence"
    assert data["strategy"] == "dense"
    assert data["latency_ms"] >= 0.0
    assert data["total_results"] >= 1
    assert len(data["results"]) == data["total_results"]
    # Each result should expose the canonical fields per spec.
    first = data["results"][0]
    assert {"chunk_id", "document_id", "score", "page_number"}.issubset(first.keys())
    assert first["rank"] == 1
    assert data["request_id"] is not None


@pytest.mark.asyncio
async def test_dense_search_validation_errors(client: AsyncClient) -> None:
    # Empty query
    response = await client.post("/api/v1/search/dense", json={"query": "", "top_k": 5})
    assert response.status_code == 422

    # top_k out of range
    response = await client.post(
        "/api/v1/search/dense", json={"query": "kyc", "top_k": 0}
    )
    assert response.status_code == 422

    response = await client.post(
        "/api/v1/search/dense", json={"query": "kyc", "top_k": 1000}
    )
    assert response.status_code == 422

    # extra forbidden field
    response = await client.post(
        "/api/v1/search/dense",
        json={"query": "kyc", "top_k": 5, "unknown": "x"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dense_search_empty_results(client: AsyncClient, seeded_corpus) -> None:
    # "completely unrelated search string" → [0.0, 0.0, 1.0] via the mock.
    # No seeded chunk shares this vector, so the max similarity is 0.0
    # and a min_score of 0.5 filters out everything.
    response = await client.post(
        "/api/v1/search/dense",
        json={
            "query": "completely unrelated search string",
            "top_k": 5,
            "filters": {"min_score": 0.5},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_dense_search_pagination_top_k(
    client: AsyncClient, seeded_corpus
) -> None:
    # top_k=1 must return exactly one row, even if more matches exist.
    response = await client.post(
        "/api/v1/search/dense", json={"query": "kyc diligence", "top_k": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 1
    assert len(data["results"]) == 1
    # Bumping top_k should yield at least as many results.
    response = await client.post(
        "/api/v1/search/dense", json={"query": "kyc diligence", "top_k": 5}
    )
    data2 = response.json()
    assert data2["total_results"] >= data["total_results"]


@pytest.mark.asyncio
async def test_dense_search_source_filter(client: AsyncClient, seeded_corpus) -> None:
    response = await client.post(
        "/api/v1/search/dense",
        json={"query": "kyc", "top_k": 5, "filters": {"source": "RBI"}},
    )
    assert response.status_code == 200
    data = response.json()
    for item in data["results"]:
        assert (item.get("metadata") or {}).get("document_id") is not None


# ─── BM25 Search ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bm25_search_success(client: AsyncClient, seeded_corpus) -> None:
    response = await client.post(
        "/api/v1/search/bm25", json={"query": "diligence Aadhaar", "top_k": 5}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "diligence Aadhaar"
    assert data["strategy"] == "bm25"
    assert data["total_results"] >= 1
    assert data["latency_ms"] >= 0.0
    assert data["request_id"] is not None


@pytest.mark.asyncio
async def test_bm25_search_threshold_filtering(
    client: AsyncClient, seeded_corpus
) -> None:
    # Threshold = 0.0 (default) — should return matches.
    response = await client.post(
        "/api/v1/search/bm25",
        json={"query": "diligence", "top_k": 10, "score_threshold": 0.0},
    )
    baseline = response.json()["total_results"]
    assert baseline >= 1

    # High threshold — should return no results.
    response = await client.post(
        "/api/v1/search/bm25",
        json={"query": "diligence", "top_k": 10, "score_threshold": 1000.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 0


@pytest.mark.asyncio
async def test_bm25_search_source_filters(client: AsyncClient, seeded_corpus) -> None:
    # Query that matches both sources; restrict to RBI only.
    response = await client.post(
        "/api/v1/search/bm25",
        json={
            "query": "diligence mutual fund details",
            "top_k": 10,
            "filters": {"source": "RBI"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    for item in data["results"]:
        # All returned chunks must be sourced from the RBI document.
        assert (item.get("metadata") or {}).get("source") == "RBI"


@pytest.mark.asyncio
async def test_bm25_search_pagination_top_k(client: AsyncClient, seeded_corpus) -> None:
    response = await client.post(
        "/api/v1/search/bm25", json={"query": "diligence", "top_k": 1}
    )
    data_one = response.json()
    assert data_one["total_results"] == 1

    response = await client.post(
        "/api/v1/search/bm25", json={"query": "diligence", "top_k": 5}
    )
    data_many = response.json()
    assert data_many["total_results"] >= data_one["total_results"]


@pytest.mark.asyncio
async def test_bm25_search_validation(client: AsyncClient) -> None:
    response = await client.post("/api/v1/search/bm25", json={"query": "", "top_k": 5})
    assert response.status_code == 422

    response = await client.post(
        "/api/v1/search/bm25",
        json={"query": "x", "top_k": 5, "filters": {"min_score": 2.0}},
    )
    assert response.status_code == 422


# ─── Hybrid Search ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mock_reranker():
    """Override the reranker DI provider with the deterministic mock."""
    mock = MockRerankerService()
    app.dependency_overrides[get_reranker_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_reranker_service, None)


@pytest.mark.asyncio
async def test_hybrid_search_query_classification(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    response = await client.post(
        "/api/v1/search/hybrid",
        json={"query": "KYC mutual fund guidelines", "top_k": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert "query_type" in data
    assert data["query_type"] != ""
    assert data["strategy"] in {"hybrid", "hybrid_rerank"}


@pytest.mark.asyncio
async def test_hybrid_search_retrieval(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    response = await client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "KYC mutual fund diligence",
            "top_k": 3,
            "dense_top_k": 5,
            "bm25_top_k": 5,
            "fusion_candidate_k": 5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] >= 1
    assert data["latency_ms"] >= 0.0
    for item in data["results"]:
        assert "chunk_id" in item
        assert "score" in item
        assert item["rank"] is not None and item["rank"] >= 1


@pytest.mark.asyncio
async def test_hybrid_search_reranking_enabled(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    response = await client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "KYC mutual fund",
            "top_k": 3,
            "enable_reranking": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy"] == "hybrid_rerank"
    diagnostics = data["diagnostics"]
    assert diagnostics["rerank_used"] is True
    assert diagnostics["rerank_model"] == "mock-reranker"
    assert mock_reranker.calls, "Reranker service should have been invoked"


@pytest.mark.asyncio
async def test_hybrid_search_reranking_disabled(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    response = await client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "KYC mutual fund",
            "top_k": 3,
            "enable_reranking": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["strategy"] == "hybrid"
    diagnostics = data["diagnostics"]
    assert diagnostics["rerank_used"] is False
    assert not mock_reranker.calls, "Reranker must not be invoked when disabled"


@pytest.mark.asyncio
async def test_hybrid_search_diagnostics_payload(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    response = await client.post(
        "/api/v1/search/hybrid",
        json={"query": "KYC diligence", "top_k": 3, "enable_reranking": True},
    )
    assert response.status_code == 200
    data = response.json()
    diagnostics = data["diagnostics"]
    expected_keys = {
        "query_type",
        "query_confidence",
        "recommended_strategy",
        "dense_count",
        "bm25_count",
        "fused_count",
        "overlap_count",
        "overlap_pct",
        "dense_latency_ms",
        "bm25_latency_ms",
        "fusion_latency_ms",
        "rerank_latency_ms",
        "rerank_used",
        "rerank_model",
        "fusion_method",
    }
    assert expected_keys.issubset(diagnostics.keys())
    # fusion_method should be a non-empty string
    assert isinstance(diagnostics["fusion_method"], str)
    assert diagnostics["fusion_method"] != ""


@pytest.mark.asyncio
async def test_hybrid_search_validation(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/search/hybrid", json={"query": "", "top_k": 5}
    )
    assert response.status_code == 422

    # Out-of-range weights
    response = await client.post(
        "/api/v1/search/hybrid",
        json={"query": "kyc", "top_k": 5, "dense_weight": 1.5},
    )
    assert response.status_code == 422


# ─── Metrics ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_metrics(db_session):
    """Seed RetrievalMetricsRecord rows spanning the four strategies.

    Uses a unique dataset name per invocation so the records don't leak
    across tests that read from the same shared analytics table.
    """
    analytics = AnalyticsService(db_session)
    dataset_name = f"module48_test_{uuid.uuid4().hex[:8]}"
    samples = [
        ("dense", 0.85, 0.92, 30.0, 0.0),
        ("bm25", 0.60, 0.75, 25.0, 0.0),
        ("hybrid", 0.90, 0.95, 40.0, 0.0),
        ("hybrid_rerank", 0.93, 0.97, 150.0, 0.10),
    ]
    for idx, (strategy, recall5, recall10, latency, gain) in enumerate(samples):
        await analytics.record_metrics(
            RetrievalMetricsCreate(
                query_id=f"test-q-{idx}-{uuid.uuid4().hex[:6]}",
                query_text=f"sample query {idx}",
                query_category="factual",
                strategy=strategy,
                dataset_name=dataset_name,
                dense_recall_at_5=recall5,
                dense_recall_at_10=recall10,
                bm25_recall_at_5=0.5,
                bm25_recall_at_10=0.6,
                hybrid_recall_at_5=recall5,
                hybrid_recall_at_10=recall10,
                precision_at_5=0.7,
                precision_at_10=0.6,
                mrr=0.8,
                hit_rate=1.0,
                retrieval_latency_ms=latency,
                reranker_latency_ms=80.0 if "rerank" in strategy else 0.0,
                total_latency_ms=latency + (80.0 if "rerank" in strategy else 0.0),
                reranker_gain=gain,
                results_returned=5,
                relevant_count=4,
            )
        )
    await db_session.commit()
    return {"db": db_session, "dataset_name": dataset_name}


@pytest.mark.asyncio
async def test_metrics_analytics_integration(
    client: AsyncClient, seeded_metrics
) -> None:
    dataset_name = seeded_metrics["dataset_name"]
    response = await client.get(
        "/api/v1/retrieval/metrics",
        params={"window": "daily", "dataset_name": dataset_name},
    )
    assert response.status_code == 200
    data = response.json()
    # The dense/bm25/hybrid recall values must surface from the analytics layer.
    assert data["dense_recall"] is not None and data["dense_recall"] > 0
    assert data["bm25_recall"] is not None and data["bm25_recall"] > 0
    assert data["hybrid_recall"] is not None and data["hybrid_recall"] > 0
    assert data["average_latency"] is not None
    assert data["retrieval_success_rate"] is not None
    assert data["total_queries"] >= 4
    assert data["window_start"] is not None
    assert data["window_end"] is not None


@pytest.mark.asyncio
async def test_metrics_empty(client: AsyncClient) -> None:
    # Use a dataset name that will never have data.
    response = await client.get(
        "/api/v1/retrieval/metrics",
        params={"dataset_name": f"empty_{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_queries"] == 0
    assert data["dense_recall"] is None
    assert data["bm25_recall"] is None
    assert data["hybrid_recall"] is None
    assert data["reranker_gain"] is None
    assert data["average_latency"] is None
    assert data["retrieval_success_rate"] is None


@pytest.mark.asyncio
async def test_metrics_window_selection(client: AsyncClient, seeded_metrics) -> None:
    dataset_name = seeded_metrics["dataset_name"]
    for window in ("hourly", "daily", "weekly", "monthly"):
        response = await client.get(
            "/api/v1/retrieval/metrics",
            params={"window": window, "dataset_name": dataset_name},
        )
        assert response.status_code == 200, f"window={window}"
        data = response.json()
        assert data["window_start"] is not None
        assert data["window_end"] is not None
        # Sanity: each window returns the seeded metrics.
        assert data["total_queries"] >= 4

    # Invalid window value → 422 (pattern validation).
    response = await client.get(
        "/api/v1/retrieval/metrics", params={"window": "yearly"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_metrics_response_contract(client: AsyncClient, seeded_metrics) -> None:
    dataset_name = seeded_metrics["dataset_name"]
    response = await client.get(
        "/api/v1/retrieval/metrics",
        params={"window": "daily", "dataset_name": dataset_name},
    )
    assert response.status_code == 200
    data = response.json()
    expected_keys = {
        "dense_recall",
        "bm25_recall",
        "hybrid_recall",
        "reranker_gain",
        "retrieval_success_rate",
        "average_latency",
        "total_queries",
        "window_start",
        "window_end",
    }
    assert expected_keys.issubset(data.keys())


# ─── Health ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_healthy_state(client: AsyncClient, seeded_corpus) -> None:
    response = await client.get("/api/v1/retrieval/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"healthy", "degraded"}
    assert "checks" in data and isinstance(data["checks"], dict)
    assert data["checks"]["database"] is True
    # Each component is reported
    component_names = {c["name"] for c in data["components"]}
    assert {
        "database",
        "bm25_service",
        "hybrid_retriever",
        "analytics_layer",
        "reranker",
    }.issubset(component_names)


@pytest.mark.asyncio
async def test_health_degraded_state_bm25_not_ready(
    client: AsyncClient, seeded_corpus
) -> None:
    # Force the BM25 index into a NOT_BUILT state.
    bm25_service: BM25Service = get_bm25_service()
    bm25_service._retriever._stats.status = IndexStatus.NOT_BUILT  # noqa: SLF001

    response = await client.get("/api/v1/retrieval/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"degraded", "unhealthy"}
    assert data["checks"]["bm25_service"] is False
    # DB must still be healthy.
    assert data["checks"]["database"] is True


@pytest.mark.asyncio
async def test_health_unhealthy_state_db_down(client: AsyncClient) -> None:
    # Patch the database session to raise on execute.
    class _BrokenSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("simulated db outage")

    async def _override():
        yield _BrokenSession()

    app.dependency_overrides[
        __import__("app.core.database", fromlist=["get_db_session"]).get_db_session
    ] = _override
    try:
        response = await client.get("/api/v1/retrieval/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["database"] is False
    finally:
        app.dependency_overrides.pop(
            __import__("app.core.database", fromlist=["get_db_session"]).get_db_session,
            None,
        )


# ─── Observability & OpenAPI ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observability_counters_increment(
    client: AsyncClient, seeded_corpus, mock_reranker
) -> None:
    # Snapshot the counters before the test.
    from app.services.observability import get_metrics

    metrics = get_metrics()
    metrics.reset()

    r1 = await client.post("/api/v1/search/dense", json={"query": "KYC", "top_k": 3})
    r2 = await client.post(
        "/api/v1/search/bm25", json={"query": "diligence", "top_k": 3}
    )
    r3 = await client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "KYC mutual fund guidelines",
            "top_k": 3,
            "enable_reranking": True,
            "use_query_analysis": False,
        },
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 200, r3.text
    body3 = r3.json()
    # The hybrid endpoint should have produced candidates (dense matches) and
    # therefore applied the reranker.
    assert body3["diagnostics"]["rerank_used"] is True, body3

    snapshot = metrics.snapshot()
    assert snapshot["total_requests"] == 3, snapshot
    assert snapshot["successful_requests"] == 3
    assert snapshot["failed_requests"] == 0
    assert snapshot["strategy_counts"].get("dense", 0) >= 1
    assert snapshot["strategy_counts"].get("bm25", 0) >= 1
    assert snapshot["strategy_counts"].get("hybrid_rerank", 0) >= 1
    assert snapshot["reranker_used"] >= 1, snapshot


def test_openapi_schema_generation() -> None:
    schema = app.openapi()
    assert "paths" in schema
    paths = schema["paths"]
    assert "/api/v1/search/dense" in paths
    assert "/api/v1/search/bm25" in paths
    assert "/api/v1/search/hybrid" in paths
    assert "/api/v1/retrieval/metrics" in paths
    assert "/api/v1/retrieval/health" in paths

    # Confirm the response model references the Pydantic contracts.
    dense_resp_ref = paths["/api/v1/search/dense"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert "SearchResponse" in dense_resp_ref

    hybrid_resp_ref = paths["/api/v1/search/hybrid"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert "HybridSearchResponse" in hybrid_resp_ref

    health_resp_ref = paths["/api/v1/retrieval/health"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert "RetrievalHealthResponse" in health_resp_ref
