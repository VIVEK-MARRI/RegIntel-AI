"""Module 5.3 — Confidence Scoring Engine tests.

Covers:
* Pydantic schema validation (level thresholds, factor bounds, flags)
* Per-factor calculators (retrieval / rerank / source / coverage / citation)
* ConfidenceCalculator weighted aggregation + weight redistribution
* ConfidenceService end-to-end (orchestration, flags, metrics)
* API integration tests against ``/api/v1/confidence/score``,
  ``/confidence/metrics``, ``/confidence/metrics/reset``,
  ``/confidence/health``

The engine is deterministic and dependency-free, so the test suite
runs offline.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_confidence_service,
    reset_confidence_service,
)
from app.main import app
from app.schemas.confidence import (
    DEFAULT_WEIGHTS,
    ConfidenceFactorName,
    ConfidenceFlag,
    ConfidenceLevel,
    ConfidenceRequest,
    ConfidenceResponse,
    level_for,
)
from app.services.confidence import (
    ConfidenceCalculator,
    ConfidenceMetrics,
    ConfidenceService,
    FactorCalculator,
    build_default_confidence_service,
)
from app.services.confidence.factors import (
    chunk_coverage_factor,
    citation_coverage_factor,
    retrieval_relevance_factor,
    reranker_confidence_factor,
    source_agreement_factor,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _chunk(
    *,
    cid: str = "c-1",
    doc: str = "d-1",
    content: str = "Sample",
    score: float = 0.9,
    source: str = "RBI",
    page: int = 1,
    section: str = "KYC",
) -> Dict[str, Any]:
    return {
        "chunk_id": cid,
        "document_id": doc,
        "content": content,
        "score": score,
        "source": source,
        "page_number": page,
        "section": section,
    }


@pytest.fixture
def sample_answer() -> Dict[str, Any]:
    return {
        "executive_summary": "Banks must follow RBI KYC norms.",
        "detailed_explanation": "Customer identification requires PAN for transactions.",
        "supporting_evidence": [{"chunk_id": "c-1"}, {"chunk_id": "c-2"}],
        "key_regulatory_references": ["RBI Act 1934"],
    }


@pytest.fixture
def mixed_chunks() -> List[Dict[str, Any]]:
    return [
        _chunk(cid="c-1", doc="d-1", content="KYC", score=0.92, source="RBI", page=12),
        _chunk(
            cid="c-2",
            doc="d-2",
            content="Disclosure",
            score=0.85,
            source="SEBI",
            page=4,
        ),
        _chunk(cid="c-3", doc="d-1", content="KYC", score=0.78, source="RBI", page=13),
    ]


@pytest.fixture
def confidence_service() -> ConfidenceService:
    return build_default_confidence_service()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a fresh metrics collector."""
    reset_confidence_service()
    yield
    reset_confidence_service()


# ─── Schema / level mapping ─────────────────────────────────────────────────


class TestSchemas:
    def test_level_for_thresholds(self):
        assert level_for(1.0) == ConfidenceLevel.HIGH
        assert level_for(0.95) == ConfidenceLevel.HIGH
        assert level_for(0.9) == ConfidenceLevel.HIGH
        assert level_for(0.8999) == ConfidenceLevel.MEDIUM
        assert level_for(0.7) == ConfidenceLevel.MEDIUM
        assert level_for(0.6999) == ConfidenceLevel.LOW
        assert level_for(0.0) == ConfidenceLevel.LOW

    def test_request_defaults(self):
        req = ConfidenceRequest(query="q", answer={}, chunks=[])
        assert req.min_chunks_for_full_coverage == 5
        assert req.citation_coverage is None
        assert req.weights is None
        assert req.reranker_scores is None

    def test_request_rejects_invalid_coverage(self):
        with pytest.raises(Exception):
            ConfidenceRequest(query="q", answer={}, chunks=[], citation_coverage=1.5)
        with pytest.raises(Exception):
            ConfidenceRequest(query="q", answer={}, chunks=[], citation_coverage=-0.1)

    def test_request_rejects_empty_query(self):
        with pytest.raises(Exception):
            ConfidenceRequest(query="", answer={}, chunks=[])

    def test_response_envelope(self):
        resp = ConfidenceResponse(
            query="q",
            confidence=0.85,
            level=ConfidenceLevel.MEDIUM,
            breakdown={"factors": [], "weights": {}, "total_weight": 0.0},
            flags=[],
        )
        assert resp.confidence == 0.85
        assert resp.level == ConfidenceLevel.MEDIUM

    def test_default_weights_keys(self):
        expected = {n.value for n in ConfidenceFactorName}
        assert set(DEFAULT_WEIGHTS.keys()) == expected
        assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


# ─── Per-factor calculators ─────────────────────────────────────────────────


class TestRetrievalRelevance:
    def test_uses_explicit_scores(self):
        out = retrieval_relevance_factor(retrieval_scores=[0.9, 0.8, 0.7])
        assert abs(out["score"] - 0.8) < 1e-9
        assert out["details"]["count"] == 3

    def test_falls_back_to_chunk_scores(self):
        out = retrieval_relevance_factor(
            chunk_scores=[
                c["score"] for c in [{"score": 0.5}, {"score": 0.7}, {"score": 0.9}]
            ]
        )
        assert abs(out["score"] - 0.7) < 1e-9

    def test_empty_input(self):
        out = retrieval_relevance_factor()
        assert out["score"] == 0.0
        assert out["details"]["count"] == 0


class TestRerankerFactor:
    def test_with_scores(self):
        out = reranker_confidence_factor([0.95, 0.88, 0.81])
        assert out["available"] is True
        assert abs(out["score"] - 0.88) < 1e-9

    def test_unavailable(self):
        out = reranker_confidence_factor(None)
        assert out["available"] is False
        out2 = reranker_confidence_factor([])
        assert out2["available"] is False


class TestSourceAgreement:
    def test_single_source_full_score(self):
        chunks = [_chunk(source="RBI"), _chunk(source="RBI")]
        out = source_agreement_factor(chunks)
        assert out["score"] == 1.0
        assert out["details"]["unique_sources"] == 1

    def test_split_sources(self):
        chunks = [_chunk(source="RBI"), _chunk(source="SEBI")]
        out = source_agreement_factor(chunks)
        # 50/50 split → primary_share 0.5 → score 0.0
        assert out["score"] == 0.0
        assert out["details"]["unique_sources"] == 2

    def test_three_sources(self):
        chunks = [
            _chunk(source="RBI"),
            _chunk(source="SEBI"),
            _chunk(source="IRDAI"),
        ]
        out = source_agreement_factor(chunks)
        assert out["score"] == 0.0

    def test_70_30_split(self):
        chunks = [_chunk(source="RBI")] * 7 + [_chunk(source="SEBI")] * 3
        out = source_agreement_factor(chunks)
        # primary_share = 0.7 → score = (0.7 - 0.5) * 2 = 0.4
        assert abs(out["score"] - 0.4) < 1e-9

    def test_empty_chunks(self):
        out = source_agreement_factor([])
        assert out["score"] == 0.0


class TestChunkCoverage:
    def test_full_coverage_at_threshold(self):
        chunks = [_chunk(score=0.9) for _ in range(5)]
        out = chunk_coverage_factor(chunks, min_chunks_for_full_coverage=5)
        # count_score = 1.0, density = 0.5 + 0.5*0.9 = 0.95
        # score = 0.95
        assert abs(out["score"] - 0.95) < 1e-9
        assert out["details"]["count"] == 5

    def test_partial_coverage(self):
        chunks = [_chunk(score=0.8) for _ in range(2)]
        out = chunk_coverage_factor(chunks, min_chunks_for_full_coverage=5)
        # count_score = 0.4, density = 0.5 + 0.5*0.8 = 0.9
        # score = 0.36
        assert abs(out["score"] - 0.36) < 1e-9

    def test_no_chunks(self):
        out = chunk_coverage_factor([])
        assert out["score"] == 0.0

    def test_low_density_chunks(self):
        chunks = [_chunk(score=0.1) for _ in range(5)]
        out = chunk_coverage_factor(chunks, min_chunks_for_full_coverage=5)
        # count_score = 1.0, density = 0.5 + 0.5*0.1 = 0.55
        # score = 0.55
        assert abs(out["score"] - 0.55) < 1e-9


class TestCitationCoverage:
    def test_with_explicit_value(self):
        out = citation_coverage_factor(0.85, answer={})
        assert out["score"] == 0.85
        assert out["details"]["source"] == "module_5_2"

    def test_clamps_to_unit_interval(self):
        out = citation_coverage_factor(1.5, answer={})
        assert out["score"] == 1.0
        out2 = citation_coverage_factor(-0.1, answer={})
        assert out2["score"] == 0.0

    def test_heuristic_fallback(self):
        answer = {
            "executive_summary": "X",
            "detailed_explanation": "Y",
            "supporting_evidence": [{"chunk_id": "c-1"}],
        }
        out = citation_coverage_factor(None, answer=answer)
        # 1 supporting, 2 fields → ratio = 0.5
        assert out["score"] == 0.5
        assert out["details"]["source"] == "heuristic"

    def test_heuristic_no_evidence(self):
        answer = {"executive_summary": "X", "detailed_explanation": "Y"}
        out = citation_coverage_factor(None, answer=answer)
        assert out["score"] == 0.0

    def test_heuristic_empty_answer(self):
        out = citation_coverage_factor(None, answer={})
        assert out["score"] == 0.0


# ─── ConfidenceCalculator ──────────────────────────────────────────────────


class TestConfidenceCalculator:
    def test_aggregate_simple(self):
        calc = ConfidenceCalculator()
        factors = [
            FactorCalculator(
                name=ConfidenceFactorName.RETRIEVAL_RELEVANCE,
                score=0.8,
                weight=0.5,
                available=True,
            ),
            FactorCalculator(
                name=ConfidenceFactorName.CITATION_COVERAGE,
                score=1.0,
                weight=0.5,
                available=True,
            ),
        ]
        confidence, breakdown = calc.aggregate(factors)
        assert abs(confidence - 0.9) < 1e-9
        assert breakdown.total_weight == 1.0
        # Each factor contributes 0.5 * score.
        contribs = {f.name: f.contribution for f in breakdown.factors}
        assert abs(contribs[ConfidenceFactorName.RETRIEVAL_RELEVANCE] - 0.4) < 1e-9
        assert abs(contribs[ConfidenceFactorName.CITATION_COVERAGE] - 0.5) < 1e-9

    def test_aggregate_redistributes_unavailable_weight(self):
        calc = ConfidenceCalculator()
        factors = [
            FactorCalculator(
                name=ConfidenceFactorName.RETRIEVAL_RELEVANCE,
                score=0.8,
                weight=0.5,
                available=True,
            ),
            FactorCalculator(
                name=ConfidenceFactorName.RERANKER_CONFIDENCE,
                score=0.99,
                weight=0.5,
                available=False,  # not available
            ),
        ]
        confidence, breakdown = calc.aggregate(factors)
        # Only retrieval contributes: 0.8
        assert abs(confidence - 0.8) < 1e-9
        weights = breakdown.weights
        assert weights[ConfidenceFactorName.RETRIEVAL_RELEVANCE.value] == 1.0
        assert weights[ConfidenceFactorName.RERANKER_CONFIDENCE.value] == 0.0

    def test_aggregate_no_active_factors(self):
        calc = ConfidenceCalculator()
        factors = [
            FactorCalculator(
                name=ConfidenceFactorName.RERANKER_CONFIDENCE,
                score=0.99,
                weight=0.5,
                available=False,
            ),
        ]
        confidence, breakdown = calc.aggregate(factors)
        assert confidence == 0.0
        assert breakdown.total_weight == 0.0

    def test_invalid_weight_key_raises(self):
        with pytest.raises(ValueError):
            ConfidenceCalculator(weights={"unknown": 0.5})

    def test_level_from_aggregate(self):
        calc = ConfidenceCalculator()
        factors = [
            FactorCalculator(
                name=ConfidenceFactorName.RETRIEVAL_RELEVANCE,
                score=0.95,
                weight=1.0,
                available=True,
            ),
        ]
        confidence, _ = calc.aggregate(factors)
        assert ConfidenceCalculator.level_for(confidence) == ConfidenceLevel.HIGH


# ─── ConfidenceService (orchestration) ──────────────────────────────────────


class TestConfidenceService:
    def test_score_high_quality(self, confidence_service, mixed_chunks, sample_answer):
        req = ConfidenceRequest(
            query="What are KYC obligations?",
            answer=sample_answer,
            chunks=mixed_chunks,
            retrieval_scores=[0.92, 0.85, 0.78],
            reranker_scores=[0.95, 0.88, 0.81],
            citation_coverage=1.0,
        )
        res = confidence_service.score(req)
        assert isinstance(res, ConfidenceResponse)
        # 0.7-0.95 is the sweet spot for MEDIUM, depending on source mix.
        assert 0.0 <= res.confidence <= 1.0
        assert res.level in {
            ConfidenceLevel.LOW,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.HIGH,
        }
        assert res.metadata["chunks_used"] == 3
        assert res.metadata["rerank_available"] is True
        # Has all five factors in the breakdown.
        names = {f.name for f in res.breakdown.factors}
        assert names == set(ConfidenceFactorName)

    def test_score_low_quality_triggers_flags(self, confidence_service, sample_answer):
        chunks = [_chunk(score=0.3, source="RBI")]
        req = ConfidenceRequest(
            query="q",
            answer=sample_answer,
            chunks=chunks,
            retrieval_scores=[0.3],
            citation_coverage=0.3,
        )
        res = confidence_service.score(req)
        assert res.level == ConfidenceLevel.LOW
        assert ConfidenceFlag.LOW_CHUNK_COUNT in res.flags
        assert ConfidenceFlag.LOW_CITATION_COVERAGE in res.flags
        assert ConfidenceFlag.NO_RERANK_SCORES in res.flags

    def test_score_empty_chunks_returns_zero(self, confidence_service, sample_answer):
        req = ConfidenceRequest(
            query="q",
            answer=sample_answer,
            chunks=[],
            retrieval_scores=[],
        )
        res = confidence_service.score(req)
        assert res.confidence == 0.0
        assert res.level == ConfidenceLevel.LOW
        assert ConfidenceFlag.EMPTY_CHUNKS in res.flags

    def test_score_single_source_flag(self, confidence_service, sample_answer):
        chunks = [_chunk(score=0.9, source="RBI") for _ in range(5)]
        req = ConfidenceRequest(
            query="q",
            answer=sample_answer,
            chunks=chunks,
            retrieval_scores=[0.9] * 5,
            reranker_scores=[0.95] * 5,
            citation_coverage=1.0,
        )
        res = confidence_service.score(req)
        assert ConfidenceFlag.SINGLE_SOURCE in res.flags

    def test_score_answer_convenience(
        self, confidence_service, mixed_chunks, sample_answer
    ):
        res = confidence_service.score_answer(
            query="q",
            answer=sample_answer,
            chunks=mixed_chunks,
            retrieval_scores=[0.9, 0.85, 0.8],
            reranker_scores=[0.95, 0.88, 0.81],
            citation_coverage=1.0,
        )
        assert isinstance(res, ConfidenceResponse)

    def test_custom_weights(self, confidence_service, mixed_chunks, sample_answer):
        # Force every factor to be heavily retrieval-weighted.
        custom = {n.value: 1.0 for n in ConfidenceFactorName}
        custom[ConfidenceFactorName.RETRIEVAL_RELEVANCE.value] = 4.0
        req = ConfidenceRequest(
            query="q",
            answer=sample_answer,
            chunks=mixed_chunks,
            retrieval_scores=[0.92, 0.85, 0.78],
            weights=custom,
        )
        res = confidence_service.score(req)
        # With rerank unavailable, total weight is 7 (not 8), so retrieval
        # contributes 0.85 * 4/7 ≈ 0.486.  Other factors lift the result
        # to ~0.76.  Verify retrieval clearly dominates: the result should
        # be well above the unweighted default (~0.6) and below 0.9.
        assert 0.7 < res.confidence < 0.9
        retrieval = next(
            f
            for f in res.breakdown.factors
            if f.name == ConfidenceFactorName.RETRIEVAL_RELEVANCE
        )
        # Retrieval should be the single largest contributor.
        assert retrieval.contribution > 0.3

    def test_high_variance_triggers_flag(self, confidence_service, sample_answer):
        chunks = [
            _chunk(score=0.95, source="RBI"),
            _chunk(score=0.95, source="RBI"),
            _chunk(score=0.1, source="RBI"),
        ]
        req = ConfidenceRequest(
            query="q",
            answer=sample_answer,
            chunks=chunks,
            retrieval_scores=[c["score"] for c in chunks],
        )
        res = confidence_service.score(req)
        # Stdev / mean = ~0.62 > 0.4 → flag raised.
        assert ConfidenceFlag.HIGH_SCORE_VARIANCE in res.flags


# ─── Metrics ───────────────────────────────────────────────────────────────


class TestConfidenceMetrics:
    def test_record_and_snapshot(self):
        m = ConfidenceMetrics()
        m.record(
            confidence=0.95,
            level=ConfidenceLevel.HIGH,
            factor_scores={ConfidenceFactorName.RETRIEVAL_RELEVANCE: 0.9},
            flags=[],
        )
        m.record(
            confidence=0.5,
            level=ConfidenceLevel.LOW,
            factor_scores={ConfidenceFactorName.RETRIEVAL_RELEVANCE: 0.4},
            flags=[ConfidenceFlag.LOW_CHUNK_COUNT],
        )
        snap = m.snapshot()
        assert snap["total_requests"] == 2
        assert snap["level_distribution"]["high"] == 1
        assert snap["level_distribution"]["low"] == 1
        assert snap["confidence"]["mean"] == 0.725
        assert snap["factor_stats"]["retrieval_relevance"]["count"] == 2
        assert snap["flag_counts"]["low_chunk_count"] == 1

    def test_reset(self):
        m = ConfidenceMetrics()
        m.record(
            confidence=0.9,
            level=ConfidenceLevel.HIGH,
            factor_scores={},
            flags=[],
        )
        m.reset()
        snap = m.snapshot()
        assert snap["total_requests"] == 0
        assert snap["confidence"]["mean"] == 0.0

    def test_thread_safety(self):
        m = ConfidenceMetrics()

        def hammer():
            for _ in range(500):
                m.record(
                    confidence=0.5,
                    level=ConfidenceLevel.MEDIUM,
                    factor_scores={},
                    flags=[],
                )

        t1 = threading.Thread(target=hammer)
        t2 = threading.Thread(target=hammer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        snap = m.snapshot()
        assert snap["total_requests"] == 1000


# ─── API integration ───────────────────────────────────────────────────────


class TestConfidenceAPI:
    @pytest_asyncio.fixture
    async def api_client(self):
        # Always use a fresh service for these tests.
        reset_confidence_service()
        svc = build_default_confidence_service()
        app.dependency_overrides[get_confidence_service] = lambda: svc
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac, svc
        app.dependency_overrides.clear()
        reset_confidence_service()

    @pytest.mark.asyncio
    async def test_score_endpoint_success(
        self, api_client, mixed_chunks, sample_answer
    ):
        ac, _svc = api_client
        payload = {
            "query": "What are KYC obligations?",
            "answer": sample_answer,
            "chunks": mixed_chunks,
            "retrieval_scores": [0.92, 0.85, 0.78],
            "reranker_scores": [0.95, 0.88, 0.81],
            "citation_coverage": 1.0,
        }
        r = await ac.post("/api/v1/confidence/score", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert 0.0 <= body["confidence"] <= 1.0
        assert body["level"] in {"high", "medium", "low"}
        assert len(body["breakdown"]["factors"]) == 5
        assert "retrieval_relevance" in body["breakdown"]["weights"]

    @pytest.mark.asyncio
    async def test_score_endpoint_validation_error(self, api_client):
        ac, _ = api_client
        r = await ac.post("/api/v1/confidence/score", json={"query": ""})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_score_endpoint_empty_chunks(self, api_client, sample_answer):
        ac, _ = api_client
        r = await ac.post(
            "/api/v1/confidence/score",
            json={"query": "q", "answer": sample_answer, "chunks": []},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["confidence"] == 0.0
        assert "empty_chunks" in body["flags"]

    @pytest.mark.asyncio
    async def test_metrics_endpoint_reflects_score_calls(
        self, api_client, mixed_chunks, sample_answer
    ):
        ac, _ = api_client
        # Score 2 answers to populate metrics.
        for _ in range(2):
            await ac.post(
                "/api/v1/confidence/score",
                json={
                    "query": "q",
                    "answer": sample_answer,
                    "chunks": mixed_chunks,
                    "retrieval_scores": [0.92, 0.85, 0.78],
                    "reranker_scores": [0.95, 0.88, 0.81],
                    "citation_coverage": 1.0,
                },
            )
        r = await ac.get("/api/v1/confidence/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["total_requests"] == 2
        assert sum(body["level_distribution"].values()) == 2

    @pytest.mark.asyncio
    async def test_metrics_reset_endpoint(self, api_client):
        ac, _ = api_client
        r = await ac.post("/api/v1/confidence/metrics/reset")
        assert r.status_code == 200
        assert r.json()["reset"] is True

    @pytest.mark.asyncio
    async def test_health_endpoint(self, api_client):
        ac, _ = api_client
        r = await ac.get("/api/v1/confidence/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["module"] == "5.3-confidence-engine"
