"""Comprehensive tests for the BGE Reranking Engine.

Uses a mock ``BGERerankerProvider`` that returns deterministic scores based
on keyword overlap to avoid loading the actual cross-encoder model during
CI/CD.  The mock scoring formula:

    score = number_of_overlapping_words / total_unique_words  (Jaccard-ish)

Covers:
 1. BGERerankerProvider API contract (model management, ScoringResult)
 2. RerankerService.score_candidates() – raw scoring
 3. RerankerService.rerank() – full pipeline with top-k, thresholds, sorting
 4. Batch reranking (rerank_batch)
 5. Score distribution tracking (RerankReport.score_distribution)
 6. Precision metrics (RerankReport.precision_metrics)
 7. Benchmark suite (RerankerService.benchmark)
 8. Edge cases (empty candidates, single candidate, all below threshold)
 9. rerank_fusion_results() convenience wrapper
10. API endpoint POST /api/v1/search/rerank (E2E)
"""

import pytest
from typing import Any, Dict, List, Tuple
from httpx import AsyncClient

from app.main import app
from app.api.dependencies import get_reranker_service
from app.schemas.reranker import (
    BenchmarkReport,
    PrecisionMetrics,
    RerankReport,
    RerankResponse,
    ScoreDistribution,
)
from app.services.reranker.model import BGERerankerProvider, ScoringResult
from app.services.reranker.service import RerankerService


# ======================================================================
# Mock reranker provider
# ======================================================================


class MockBGERerankerProvider(BGERerankerProvider):
    """Deterministic mock that scores based on word overlap (no model loading)."""

    def __init__(self):
        super().__init__(model_name="mock-reranker", device="cpu")

    def _get_model(self):
        """Skip actual model loading."""
        return None

    def score_pair(self, query: str, text: str) -> float:
        q_words = set(query.lower().split())
        t_words = set(text.lower().split())
        union = q_words | t_words
        if not union:
            return 0.0
        return len(q_words & t_words) / len(union)

    def score_pairs(self, pairs: List[Tuple[str, str]]) -> List[float]:
        return [self.score_pair(q, t) for q, t in pairs]

    def score_pairs_timed(self, pairs: List[Tuple[str, str]]) -> ScoringResult:
        """Score with simulated latency tracking. Returns 0 latency for empty input."""
        if not pairs:
            return ScoringResult(scores=[], scoring_latency_ms=0.0)
        import time

        start = time.perf_counter()
        scores = self.score_pairs(pairs)
        elapsed = (time.perf_counter() - start) * 1000
        return ScoringResult(scores=scores, scoring_latency_ms=elapsed)

    def get_model_name(self) -> str:
        return "mock-reranker"

    def health_check(self) -> bool:
        return True


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_provider():
    return MockBGERerankerProvider()


@pytest.fixture
def reranker(mock_provider):
    return RerankerService(
        provider=mock_provider,
        default_top_k=3,
        default_score_threshold=0.0,
    )


def _make_candidate(chunk_id: str, content: str, score: float = 0.5) -> Dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "score": score,
        "metadata": {"section": f"Section for {chunk_id}"},
    }


QUERY = "KYC customer due diligence requirements"

CANDIDATES = [
    _make_candidate(
        "c1", "KYC guidelines require customer due diligence procedures", 0.90
    ),
    _make_candidate("c2", "AML anti money laundering reporting obligations", 0.85),
    _make_candidate("c3", "Customer identification program for banks and NBFCs", 0.80),
    _make_candidate("c4", "Due diligence standards for high risk customers", 0.75),
    _make_candidate("c5", "Trade settlement procedures and custody services", 0.70),
]


# ======================================================================
# 1. Mock Provider Contract
# ======================================================================


class TestMockProvider:
    def test_score_pair_perfect_overlap(self, mock_provider):
        score = mock_provider.score_pair("hello world", "hello world")
        assert score == pytest.approx(1.0)

    def test_score_pair_no_overlap(self, mock_provider):
        score = mock_provider.score_pair("alpha beta", "gamma delta")
        assert score == pytest.approx(0.0)

    def test_score_pair_partial_overlap(self, mock_provider):
        score = mock_provider.score_pair("hello world", "hello there")
        # overlap=1 (hello), union=3 (hello, world, there)
        assert score == pytest.approx(1.0 / 3.0)

    def test_score_pairs_batch(self, mock_provider):
        pairs = [("a b", "a c"), ("x y", "x y")]
        scores = mock_provider.score_pairs(pairs)
        assert len(scores) == 2
        assert scores[1] == pytest.approx(1.0)

    def test_score_pairs_timed(self, mock_provider):
        pairs = [("hello world", "hello world"), ("alpha", "beta")]
        result = mock_provider.score_pairs_timed(pairs)
        assert isinstance(result, ScoringResult)
        assert len(result.scores) == 2
        assert result.scores[0] == pytest.approx(1.0)
        assert result.scoring_latency_ms >= 0.0

    def test_score_pairs_timed_empty(self, mock_provider):
        result = mock_provider.score_pairs_timed([])
        assert result.scores == []
        assert result.scoring_latency_ms == 0.0

    def test_health_check(self, mock_provider):
        assert mock_provider.health_check() is True

    def test_get_model_name(self, mock_provider):
        assert mock_provider.get_model_name() == "mock-reranker"


# ======================================================================
# 2. score_candidates()
# ======================================================================


class TestScoreCandidates:
    def test_all_candidates_scored(self, reranker):
        scored = reranker.score_candidates(QUERY, CANDIDATES)
        assert len(scored) == 5
        for s in scored:
            assert "rerank_score" in s
            assert "original_rank" in s
            assert "scoring_latency_ms" in s

    def test_original_rank_is_1_indexed(self, reranker):
        scored = reranker.score_candidates(QUERY, CANDIDATES)
        ranks = [s["original_rank"] for s in scored]
        assert ranks == [1, 2, 3, 4, 5]

    def test_empty_candidates(self, reranker):
        scored = reranker.score_candidates(QUERY, [])
        assert scored == []

    def test_kyc_chunk_scores_higher(self, reranker):
        """c1 has more word overlap with the query than c5."""
        scored = reranker.score_candidates(QUERY, CANDIDATES)
        score_map = {s["chunk_id"]: s["rerank_score"] for s in scored}
        assert score_map["c1"] > score_map["c5"]

    def test_scoring_latency_tracked(self, reranker):
        scored = reranker.score_candidates(QUERY, CANDIDATES)
        for s in scored:
            assert s["scoring_latency_ms"] >= 0.0


# ======================================================================
# 3. rerank() – Full Pipeline
# ======================================================================


class TestRerankPipeline:
    def test_returns_rerank_response(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES)
        assert isinstance(resp, RerankResponse)
        assert resp.query == QUERY

    def test_top_k_applied(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=2)
        assert len(resp.results) == 2

    def test_default_top_k_used(self, reranker):
        """Default top_k is 3 in fixture."""
        resp = reranker.rerank(QUERY, CANDIDATES)
        assert len(resp.results) <= 3

    def test_results_sorted_descending(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        scores = [r.rerank_score for r in resp.results]
        assert scores == sorted(scores, reverse=True)

    def test_score_threshold_filters(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=10, score_threshold=0.5)
        for r in resp.results:
            assert r.rerank_score >= 0.5

    def test_all_below_threshold_returns_empty(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=10, score_threshold=999.0)
        assert len(resp.results) == 0

    def test_original_score_preserved(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        for r in resp.results:
            assert r.original_score is not None

    def test_original_rank_preserved(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        for r in resp.results:
            assert r.original_rank is not None
            assert r.original_rank >= 1

    def test_new_rank_assigned(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        new_ranks = [r.new_rank for r in resp.results]
        assert new_ranks == [1, 2, 3, 4, 5]

    def test_metadata_preserved(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        for r in resp.results:
            assert "section" in r.metadata

    def test_deterministic_tiebreaker(self, reranker):
        """When scores are equal, chunk_id ascending should break ties."""
        tied = [
            _make_candidate("z1", "identical text here"),
            _make_candidate("a1", "identical text here"),
        ]
        resp = reranker.rerank("identical text here", tied, top_k=2)
        ids = [r.chunk_id for r in resp.results]
        assert ids == ["a1", "z1"]


# ======================================================================
# 4. Batch Reranking
# ======================================================================


class TestBatchReranking:
    def test_batch_rerank(self, reranker):
        queries = ["KYC requirements", "AML reporting"]
        candidates = [
            [
                _make_candidate("b1c1", "KYC customer due diligence", 0.9),
                _make_candidate("b1c2", "Trade settlement", 0.5),
            ],
            [
                _make_candidate("b2c1", "AML anti money laundering", 0.85),
                _make_candidate("b2c2", "KYC guidelines", 0.4),
            ],
        ]
        responses = reranker.rerank_batch(queries, candidates, top_k=1)
        assert len(responses) == 2
        assert responses[0].results[0].chunk_id == "b1c1"
        assert responses[1].results[0].chunk_id == "b2c1"

    def test_batch_rerank_mismatched_lengths(self, reranker):
        with pytest.raises(ValueError, match="same length"):
            reranker.rerank_batch(["q1", "q2"], [[{}]])

    def test_large_batch(self, reranker):
        """Score 100 candidates in a single call."""
        big_candidates = [
            _make_candidate(f"chunk-{i}", f"content with word-{i} and KYC", 0.5)
            for i in range(100)
        ]
        resp = reranker.rerank(QUERY, big_candidates, top_k=10)
        assert len(resp.results) == 10
        assert resp.report.candidates_received == 100

    def test_single_candidate(self, reranker):
        single = [_make_candidate("only", "KYC compliance", 0.99)]
        resp = reranker.rerank(QUERY, single, top_k=5)
        assert len(resp.results) == 1
        assert resp.results[0].chunk_id == "only"


# ======================================================================
# 5. RerankReport – Score Distribution & Precision Metrics
# ======================================================================


class TestRerankReport:
    def test_report_fields(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        report = resp.report
        assert isinstance(report, RerankReport)
        assert report.model_name == "mock-reranker"
        assert report.candidates_received == 5
        assert report.candidates_returned <= 5
        assert report.latency_ms >= 0.0
        assert report.scoring_latency_ms >= 0.0

    def test_candidates_filtered_count(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=10, score_threshold=0.5)
        assert resp.report.candidates_filtered == resp.report.candidates_received - len(
            [s for s in resp.results]
        )

    def test_score_distribution(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        dist = resp.report.score_distribution
        assert isinstance(dist, ScoreDistribution)
        assert len(dist.bins) == 11
        assert len(dist.counts) == 10
        assert dist.median is not None
        assert dist.std_dev is not None
        assert dist.p25 is not None
        assert dist.p75 is not None
        # Total counts should equal total candidates
        assert sum(dist.counts) == len(CANDIDATES)

    def test_score_distribution_percentiles_ordered(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        dist = resp.report.score_distribution
        assert dist.p25 <= dist.median <= dist.p75

    def test_precision_metrics_present(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        pm = resp.report.precision_metrics
        assert isinstance(pm, PrecisionMetrics)
        assert pm.avg_score_lift is not None
        assert pm.top1_improvement is not None
        assert "improved" in pm.rank_changes
        assert "declined" in pm.rank_changes
        assert "unchanged" in pm.rank_changes

    def test_precision_rank_changes_sum(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=3)
        pm = resp.report.precision_metrics
        total_changes = sum(pm.rank_changes.values())
        assert total_changes == 3  # top_k=3 results

    def test_score_distribution(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5)
        report = resp.report
        assert report.score_min is not None
        assert report.score_max is not None
        assert report.score_mean is not None
        assert report.score_min <= report.score_mean <= report.score_max

    def test_threshold_recorded(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=5, score_threshold=0.3)
        assert resp.report.score_threshold_applied == pytest.approx(0.3)

    def test_top_k_recorded(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=2)
        assert resp.report.top_k_applied == 2

    def test_empty_report(self, reranker):
        resp = reranker.rerank(QUERY, [], top_k=5)
        assert resp.report.candidates_received == 0
        assert resp.report.candidates_returned == 0
        assert resp.report.score_min is None
        assert resp.report.score_distribution is not None
        assert resp.report.score_distribution.counts == []


# ======================================================================
# 6. Benchmark Suite
# ======================================================================


class TestBenchmark:
    def test_benchmark_returns_report(self, reranker):
        queries = ["KYC requirements", "AML reporting", "customer due diligence"]
        candidates = [
            [
                _make_candidate("bm1c1", "KYC customer due diligence procedures", 0.9),
                _make_candidate("bm1c2", "Trade settlement", 0.5),
                _make_candidate("bm1c3", "AML reporting obligations", 0.7),
            ],
            [
                _make_candidate("bm2c1", "AML anti money laundering", 0.85),
                _make_candidate("bm2c2", "KYC guidelines", 0.4),
            ],
            [
                _make_candidate("bm3c1", "Customer due diligence standards", 0.8),
                _make_candidate("bm3c2", "Risk assessment procedures", 0.6),
                _make_candidate("bm3c3", "Trade clearing", 0.3),
                _make_candidate("bm3c4", "KYC identification program", 0.7),
            ],
        ]
        report = reranker.benchmark(queries, candidates, top_k=2)
        assert isinstance(report, BenchmarkReport)
        assert report.model_name == "mock-reranker"
        assert report.total_queries == 3
        assert report.total_candidates == 9
        assert len(report.results) == 3

    def test_benchmark_latency_stats(self, reranker):
        queries = ["KYC requirements", "AML reporting"]
        candidates = [
            [_make_candidate("bl1c1", "KYC due diligence", 0.9)],
            [_make_candidate("bl2c1", "AML money laundering", 0.85)],
        ]
        report = reranker.benchmark(queries, candidates, top_k=1)
        assert report.avg_latency_ms > 0
        assert report.p50_latency_ms > 0
        assert report.p95_latency_ms > 0
        assert report.p99_latency_ms > 0

    def test_benchmark_throughput(self, reranker):
        queries = ["KYC requirements", "AML reporting", "customer due diligence"]
        candidates = [
            [_make_candidate("bt1c1", "KYC due diligence", 0.9)],
            [_make_candidate("bt2c1", "AML money laundering", 0.85)],
            [_make_candidate("bt3c1", "Customer due diligence", 0.8)],
        ]
        report = reranker.benchmark(queries, candidates, top_k=1)
        assert report.throughput_qps > 0

    def test_benchmark_individual_results(self, reranker):
        queries = ["KYC requirements"]
        candidates = [
            [
                _make_candidate("bi1c1", "KYC due diligence procedures", 0.9),
                _make_candidate("bi1c2", "Trade settlement", 0.5),
            ],
        ]
        report = reranker.benchmark(queries, candidates, top_k=1)
        assert len(report.results) == 1
        result = report.results[0]
        assert result.query == "KYC requirements"
        assert result.num_candidates == 2
        assert result.top_k == 1
        assert result.candidates_returned == 1
        assert result.top_score > 0

    def test_benchmark_avg_candidates_per_query(self, reranker):
        queries = ["q1", "q2"]
        candidates = [
            [_make_candidate("a", "content", 0.5)],
            [
                _make_candidate("b", "content", 0.5),
                _make_candidate("c", "content", 0.5),
            ],
        ]
        report = reranker.benchmark(queries, candidates, top_k=5)
        assert report.avg_candidates_per_query == 1.5


# ======================================================================
# 7. Edge Cases
# ======================================================================


class TestEdgeCases:
    def test_empty_query(self, reranker):
        resp = reranker.rerank("", CANDIDATES, top_k=3)
        # Should still work — all scores will be low / zero
        assert isinstance(resp, RerankResponse)

    def test_whitespace_content(self, reranker):
        candidates = [_make_candidate("ws", "   ")]
        resp = reranker.rerank(QUERY, candidates, top_k=1)
        assert len(resp.results) <= 1

    def test_top_k_larger_than_candidates(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES[:2], top_k=100)
        assert len(resp.results) == 2

    def test_zero_threshold(self, reranker):
        resp = reranker.rerank(QUERY, CANDIDATES, top_k=10, score_threshold=0.0)
        assert len(resp.results) <= len(CANDIDATES)

    def test_all_candidates_same_score(self, reranker):
        same = [
            _make_candidate("s1", "same content"),
            _make_candidate("s2", "same content"),
            _make_candidate("s3", "same content"),
        ]
        resp = reranker.rerank("same content", same, top_k=3)
        assert len(resp.results) == 3
        # Deterministic ordering by chunk_id
        ids = [r.chunk_id for r in resp.results]
        assert ids == ["s1", "s2", "s3"]


# ======================================================================
# 8. rerank_fusion_results() – Convenience Wrapper
# ======================================================================


class TestRerankFusionResults:
    def test_from_fusion_output(self, reranker):
        fusion_results = [
            {
                "chunk_id": "f1",
                "score": 0.82,
                "content": "KYC customer due diligence",
                "metadata": {},
                "sources": ["dense", "bm25"],
            },
            {
                "chunk_id": "f2",
                "score": 0.65,
                "content": "Settlement clearing procedures",
                "metadata": {},
                "sources": ["dense"],
            },
        ]
        resp = reranker.rerank_fusion_results(QUERY, fusion_results, top_k=2)
        assert isinstance(resp, RerankResponse)
        assert len(resp.results) <= 2
        # f1 should score higher due to word overlap with query
        if len(resp.results) == 2:
            assert resp.results[0].chunk_id == "f1"


# ======================================================================
# 9. API Endpoint E2E
# ======================================================================


@pytest.fixture(autouse=True)
def override_reranker():
    """Override the reranker service with a mock for API tests."""
    mock = MockBGERerankerProvider()
    mock_service = RerankerService(
        provider=mock, default_top_k=5, default_score_threshold=0.0
    )
    app.dependency_overrides[get_reranker_service] = lambda: mock_service
    yield
    app.dependency_overrides.pop(get_reranker_service, None)


@pytest.mark.asyncio
async def test_rerank_api_endpoint(client: AsyncClient):
    payload = {
        "query": "KYC customer due diligence",
        "candidates": [
            {
                "chunk_id": "api-c1",
                "content": "KYC guidelines for customer due diligence",
            },
            {"chunk_id": "api-c2", "content": "Trade settlement and custody services"},
            {"chunk_id": "api-c3", "content": "Customer identification program"},
        ],
        "top_k": 2,
        "score_threshold": 0.0,
    }
    response = await client.post("/api/v1/search/rerank", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "KYC customer due diligence"
    assert len(data["results"]) == 2
    # First result should be the KYC chunk (highest word overlap)
    assert data["results"][0]["chunk_id"] == "api-c1"
    assert "rerank_score" in data["results"][0]
    # Report present
    assert "report" in data
    assert data["report"]["model_name"] == "mock-reranker"
    assert data["report"]["candidates_received"] == 3
    assert data["report"]["candidates_returned"] == 2


@pytest.mark.asyncio
async def test_rerank_api_empty_candidates(client: AsyncClient):
    payload = {
        "query": "KYC",
        "candidates": [],
        "top_k": 5,
    }
    response = await client.post("/api/v1/search/rerank", json=payload)
    # Pydantic validation should reject empty candidates (min_length=1)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rerank_api_with_threshold(client: AsyncClient):
    payload = {
        "query": "KYC customer due diligence",
        "candidates": [
            {"chunk_id": "t1", "content": "KYC guidelines for customer due diligence"},
            {"chunk_id": "t2", "content": "Completely unrelated zebra content"},
        ],
        "top_k": 10,
        "score_threshold": 0.1,
    }
    response = await client.post("/api/v1/search/rerank", json=payload)
    assert response.status_code == 200
    data = response.json()
    for r in data["results"]:
        assert r["rerank_score"] >= 0.1


@pytest.mark.asyncio
async def test_rerank_api_response_includes_distribution(client: AsyncClient):
    payload = {
        "query": "KYC customer due diligence",
        "candidates": [
            {"chunk_id": "d1", "content": "KYC guidelines for customer due diligence"},
            {"chunk_id": "d2", "content": "Trade settlement"},
        ],
        "top_k": 2,
        "score_threshold": 0.0,
    }
    response = await client.post("/api/v1/search/rerank", json=payload)
    assert response.status_code == 200
    data = response.json()
    report = data["report"]
    # Score distribution
    assert "score_distribution" in report
    assert "bins" in report["score_distribution"]
    assert "counts" in report["score_distribution"]
    # Precision metrics
    assert "precision_metrics" in report
    assert "rank_changes" in report["precision_metrics"]
    # Latency fields
    assert "scoring_latency_ms" in report
    assert "candidates_filtered" in report
