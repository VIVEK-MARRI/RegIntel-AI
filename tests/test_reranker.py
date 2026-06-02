"""Comprehensive tests for the BGE Reranking Engine.

Uses a mock ``BGERerankerProvider`` that returns deterministic scores based
on keyword overlap to avoid loading the actual cross-encoder model during
CI/CD.  The mock scoring formula:

    score = number_of_overlapping_words / total_unique_words  (Jaccard-ish)

Covers:
 1. BGERerankerProvider API contract (model management)
 2. RerankerService.score_candidates() – raw scoring
 3. RerankerService.rerank() – full pipeline with top-k, thresholds, sorting
 4. Batch reranking
 5. Score distribution tracking (RerankReport)
 6. Edge cases (empty candidates, single candidate, all below threshold)
 7. rerank_fusion_results() convenience wrapper
 8. API endpoint POST /api/v1/search/rerank (E2E)
"""

import pytest
from typing import Any, Dict, List, Tuple
from httpx import AsyncClient

from app.main import app
from app.api.dependencies import get_reranker_service
from app.schemas.reranker import RerankReport, RerankResponse, RerankResult
from app.services.reranker.model import BGERerankerProvider
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
    _make_candidate("c1", "KYC guidelines require customer due diligence procedures", 0.90),
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
# 5. RerankReport – Score Distribution
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


# ======================================================================
# 6. Edge Cases
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


# ======================================================================
# 7. rerank_fusion_results() – Convenience Wrapper
# ======================================================================

class TestRerankFusionResults:
    def test_from_fusion_output(self, reranker):
        fusion_results = [
            {"chunk_id": "f1", "score": 0.82, "content": "KYC customer due diligence", "metadata": {}, "sources": ["dense", "bm25"]},
            {"chunk_id": "f2", "score": 0.65, "content": "Settlement clearing procedures", "metadata": {}, "sources": ["dense"]},
        ]
        resp = reranker.rerank_fusion_results(QUERY, fusion_results, top_k=2)
        assert isinstance(resp, RerankResponse)
        assert len(resp.results) <= 2
        # f1 should score higher due to word overlap with query
        if len(resp.results) == 2:
            assert resp.results[0].chunk_id == "f1"


# ======================================================================
# 8. API Endpoint E2E
# ======================================================================

@pytest.fixture(autouse=True)
def override_reranker():
    """Override the reranker service with a mock for API tests."""
    mock = MockBGERerankerProvider()
    mock_service = RerankerService(provider=mock, default_top_k=5, default_score_threshold=0.0)
    app.dependency_overrides[get_reranker_service] = lambda: mock_service
    yield
    app.dependency_overrides.pop(get_reranker_service, None)


@pytest.mark.asyncio
async def test_rerank_api_endpoint(client: AsyncClient):
    payload = {
        "query": "KYC customer due diligence",
        "candidates": [
            {"chunk_id": "api-c1", "content": "KYC guidelines for customer due diligence"},
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
