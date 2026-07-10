"""Comprehensive tests for the Retrieval Fusion Engine.

Covers:
- ``calculate_rrf_score()`` correctness and edge-cases.
- RRF fusion with overlapping, disjoint, and single-source inputs.
- Weighted-sum fusion with normalisation.
- Score-fusion stub raises ``NotImplementedError``.
- Duplicate / overlap handling.
- Provenance preservation (``sources`` field).
- Evaluation hook invocation.
- Ranking utilities (sort, overlap, merge_metadata).
- Empty / single-element edge-cases.
- ``fuse_results_with_report()`` diagnostic reporting.
"""

import pytest
from typing import Any, Dict

from app.schemas.fusion import FusedCandidate, FusionConfig, FusionMethod, FusionReport
from app.services.fusion.engine import (
    BaseFusionStrategy,
    FusionEngine,
    LearningToRankStrategy,
    RRFStrategy,
)
from app.services.fusion.ranking import (
    break_ties,
    build_provenance,
    compute_multi_source_overlap,
    compute_overlap,
    merge_metadata,
    normalize_scores,
    resolve_rank_conflicts,
    sort_candidates,
    source_attribution_summary,
)


# ======================================================================
# Test fixtures / helpers
# ======================================================================


def _make_result(
    chunk_id: str, score: float, content: str = "", **extra
) -> Dict[str, Any]:
    """Build a minimal retrieval result dict."""
    r: Dict[str, Any] = {
        "chunk_id": chunk_id,
        "score": score,
        "content": content or f"content-{chunk_id}",
    }
    r.update(extra)
    return r


DENSE_RESULTS = [
    _make_result("c1", 0.95, "dense chunk 1", metadata={"section": "Sec A"}),
    _make_result("c2", 0.85, "dense chunk 2", metadata={"section": "Sec B"}),
    _make_result("c3", 0.70, "dense chunk 3"),
]

BM25_RESULTS = [
    _make_result(
        "c2", 12.4, "bm25 chunk 2", section="KYC Guidelines", subsection="Part A"
    ),
    _make_result("c4", 10.1, "bm25 chunk 4", section="AML Rules"),
    _make_result("c5", 8.0, "bm25 chunk 5"),
]


# ======================================================================
# 1. calculate_rrf_score()
# ======================================================================


class TestCalculateRRFScore:
    def test_rank_1_default_k(self):
        assert RRFStrategy.calculate_rrf_score(1) == pytest.approx(1.0 / 61)

    def test_rank_1_custom_k(self):
        assert RRFStrategy.calculate_rrf_score(1, k=10) == pytest.approx(1.0 / 11)

    def test_rank_0_returns_zero(self):
        assert RRFStrategy.calculate_rrf_score(0) == 0.0

    def test_negative_rank_returns_zero(self):
        assert RRFStrategy.calculate_rrf_score(-5) == 0.0

    def test_high_rank_diminishes(self):
        assert RRFStrategy.calculate_rrf_score(
            1000, k=60
        ) < RRFStrategy.calculate_rrf_score(1, k=60)

    def test_engine_convenience_accessor(self):
        """``FusionEngine.calculate_rrf_score`` should delegate correctly."""
        assert FusionEngine.calculate_rrf_score(1, 60) == pytest.approx(1.0 / 61)


# ======================================================================
# 2. RRF Fusion
# ======================================================================


class TestRRFFusion:
    """Tests for ``RRFStrategy`` and the ``FusionEngine`` using RRF."""

    def setup_method(self):
        self.engine = FusionEngine()

    def test_basic_rrf(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
            rrf_k=60,
            dense_weight=0.5,
            bm25_weight=0.5,
        )
        ids = [r["chunk_id"] for r in results]
        # Union should contain c1..c5
        assert set(ids) == {"c1", "c2", "c3", "c4", "c5"}

    def test_rrf_scores_are_positive(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        for r in results:
            assert r["score"] > 0

    def test_overlap_chunk_gets_higher_score(self):
        """Chunk c2 appears in both lists – should get contributions from both."""
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        scores = {r["chunk_id"]: r["score"] for r in results}
        # c2 is in both; it should score ≥ each single-source chunk
        assert scores["c2"] >= scores["c1"] or scores["c2"] >= scores["c4"]

    def test_deterministic_ordering(self):
        """Two calls with the same data should produce identical output."""
        a = self.engine.fuse_results(
            DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF
        )
        b = self.engine.fuse_results(
            DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF
        )
        assert [r["chunk_id"] for r in a] == [r["chunk_id"] for r in b]

    def test_disjoint_lists(self):
        dense = [_make_result("a1", 0.9)]
        bm25 = [_make_result("b1", 5.0)]
        results = self.engine.fuse_results(dense, bm25, method=FusionMethod.RRF)
        assert {r["chunk_id"] for r in results} == {"a1", "b1"}

    def test_single_source_dense_only(self):
        results = self.engine.fuse_results(DENSE_RESULTS, [], method=FusionMethod.RRF)
        assert len(results) == 3
        for r in results:
            assert r["sources"] == ["dense"]

    def test_single_source_bm25_only(self):
        results = self.engine.fuse_results([], BM25_RESULTS, method=FusionMethod.RRF)
        assert len(results) == 3
        for r in results:
            assert r["sources"] == ["bm25"]


# ======================================================================
# 3. Weighted Sum Fusion
# ======================================================================


class TestWeightedSumFusion:
    def setup_method(self):
        self.engine = FusionEngine()

    def test_basic_weighted_sum(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
        )
        assert len(results) == 5

    def test_weighted_sum_scores_non_negative(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
        )
        for r in results:
            assert r["score"] >= 0.0

    def test_weighted_sum_with_unequal_weights(self):
        results_dense = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
            dense_weight=0.9,
            bm25_weight=0.1,
        )
        results_bm25 = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
            dense_weight=0.1,
            bm25_weight=0.9,
        )
        # Different weight profiles should produce different score orderings
        ids_dense = [r["chunk_id"] for r in results_dense]
        ids_bm25 = [r["chunk_id"] for r in results_bm25]
        # We can't assert strict != because overlap could be same, but scores differ
        scores_dense = {r["chunk_id"]: r["score"] for r in results_dense}
        scores_bm25 = {r["chunk_id"]: r["score"] for r in results_bm25}
        # c1 is dense-only, so dense-heavy should score it higher
        assert scores_dense["c1"] > scores_bm25["c1"]

    def test_weighted_sum_empty_inputs(self):
        results = self.engine.fuse_results([], [], method=FusionMethod.WEIGHTED_SUM)
        assert results == []

    def test_weighted_sum_rrf_score_is_none(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
        )
        for r in results:
            assert r["rrf_score"] is None


# ======================================================================
# 4. Score Fusion
# ======================================================================


class TestScoreFusion:
    def setup_method(self):
        self.engine = FusionEngine()

    def test_score_fusion_produces_results(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        assert len(results) == 5

    def test_score_fusion_scores_non_negative(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        for r in results:
            assert r["score"] >= 0.0

    def test_score_fusion_rrf_score_is_none(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        for r in results:
            assert r["rrf_score"] is None

    def test_score_fusion_deterministic(self):
        a = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        b = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        assert [r["chunk_id"] for r in a] == [r["chunk_id"] for r in b]

    def test_score_fusion_preserves_provenance(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        assert set(c2["sources"]) == {"dense", "bm25"}

    def test_score_fusion_empty_inputs(self):
        results = self.engine.fuse_results([], [], method=FusionMethod.SCORE_FUSION)
        assert results == []

    def test_score_fusion_dense_only(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            [],
            method=FusionMethod.SCORE_FUSION,
        )
        assert len(results) == 3
        for r in results:
            assert r["sources"] == ["dense"]

    def test_score_fusion_bm25_only(self):
        results = self.engine.fuse_results(
            [],
            BM25_RESULTS,
            method=FusionMethod.SCORE_FUSION,
        )
        assert len(results) == 3
        for r in results:
            assert r["sources"] == ["bm25"]


# ======================================================================
# 5. Provenance Tracking
# ======================================================================


class TestProvenance:
    def setup_method(self):
        self.engine = FusionEngine()

    def test_overlap_chunk_has_both_sources(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        assert set(c2["sources"]) == {"dense", "bm25"}

    def test_dense_only_chunk_has_dense_source(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        c1 = next(r for r in results if r["chunk_id"] == "c1")
        assert c1["sources"] == ["dense"]

    def test_bm25_only_chunk_has_bm25_source(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        c4 = next(r for r in results if r["chunk_id"] == "c4")
        assert c4["sources"] == ["bm25"]

    def test_provenance_preserved_in_weighted_sum(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        assert set(c2["sources"]) == {"dense", "bm25"}


# ======================================================================
# 6. Duplicate / Overlap Handling
# ======================================================================


class TestDuplicateHandling:
    def test_overlapping_chunk_merged_once(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        chunk_ids = [r["chunk_id"] for r in results]
        # c2 appears in both inputs but should only be in the output once
        assert chunk_ids.count("c2") == 1

    def test_overlapping_metadata_merged(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        # Dense had section=Sec B; BM25 had section=KYC Guidelines (in metadata)
        # After merge the dense metadata is applied first, then BM25 metadata updates
        assert "section" in c2["metadata"]

    def test_duplicate_ranks_assigned_per_source(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        assert c2["dense_rank"] is not None
        assert c2["bm25_rank"] is not None
        assert c2["dense_score"] is not None
        assert c2["bm25_score"] is not None


# ======================================================================
# 7. Evaluation Hooks
# ======================================================================


class TestEvaluationHooks:
    def test_before_hook_fires(self):
        calls = []

        def before_hook(
            *, dense_results, bm25_results, config, fused=None, report=None
        ):
            calls.append(("before", len(dense_results), len(bm25_results)))

        engine = FusionEngine()
        engine.add_before_hook(before_hook)
        engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF)

        assert len(calls) == 1
        assert calls[0] == ("before", 3, 3)

    def test_after_hook_fires_with_fused_and_report(self):
        calls = []

        def after_hook(*, dense_results, bm25_results, config, fused=None, report=None):
            calls.append(
                {
                    "fused_count": len(fused) if fused else 0,
                    "report_method": report.method.value if report else None,
                }
            )

        engine = FusionEngine()
        engine.add_after_hook(after_hook)
        engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF)

        assert len(calls) == 1
        assert calls[0]["fused_count"] == 5
        assert calls[0]["report_method"] == "rrf"

    def test_multiple_hooks_all_fire(self):
        call_count = [0]

        def hook_a(*, dense_results, bm25_results, config, **kw):
            call_count[0] += 1

        def hook_b(*, dense_results, bm25_results, config, **kw):
            call_count[0] += 1

        engine = FusionEngine()
        engine.add_before_hook(hook_a)
        engine.add_before_hook(hook_b)
        engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF)

        assert call_count[0] == 2

    def test_hook_exception_does_not_break_fusion(self):
        """A misbehaving hook should be caught, not crash the pipeline."""

        def bad_hook(*, dense_results, bm25_results, config, **kw):
            raise RuntimeError("boom")

        engine = FusionEngine()
        engine.add_before_hook(bad_hook)
        # Should not raise
        results = engine.fuse_results(
            DENSE_RESULTS, BM25_RESULTS, method=FusionMethod.RRF
        )
        assert len(results) == 5


# ======================================================================
# 8. Ranking Utilities
# ======================================================================


class TestRankingUtilities:
    def test_sort_candidates_descending(self):
        candidates = [
            {"chunk_id": "a", "score": 1.0},
            {"chunk_id": "b", "score": 3.0},
            {"chunk_id": "c", "score": 2.0},
        ]
        sorted_c = sort_candidates(candidates, descending=True)
        assert [c["chunk_id"] for c in sorted_c] == ["b", "c", "a"]

    def test_sort_candidates_tiebreaker(self):
        candidates = [
            {"chunk_id": "z", "score": 1.0},
            {"chunk_id": "a", "score": 1.0},
            {"chunk_id": "m", "score": 1.0},
        ]
        sorted_c = sort_candidates(candidates)
        assert [c["chunk_id"] for c in sorted_c] == ["a", "m", "z"]

    def test_compute_overlap_disjoint(self):
        result = compute_overlap({"a", "b"}, {"c", "d"})
        assert result["overlap_count"] == 0
        assert result["overlap_percentage"] == 0.0

    def test_compute_overlap_full(self):
        result = compute_overlap({"a", "b"}, {"a", "b"})
        assert result["overlap_count"] == 2
        assert result["overlap_percentage"] == pytest.approx(100.0)

    def test_compute_overlap_partial(self):
        result = compute_overlap({"a", "b", "c"}, {"b", "c", "d"})
        assert result["overlap_count"] == 2
        assert result["union_count"] == 4
        assert result["overlap_percentage"] == pytest.approx(50.0)

    def test_compute_overlap_empty(self):
        result = compute_overlap(set(), set())
        assert result["overlap_count"] == 0
        assert result["overlap_percentage"] == 0.0

    def test_build_provenance_both(self):
        d = {"x": {}}
        b = {"x": {}}
        assert build_provenance("x", d, b) == ["dense", "bm25"]

    def test_build_provenance_dense_only(self):
        assert build_provenance("x", {"x": {}}, {}) == ["dense"]

    def test_build_provenance_bm25_only(self):
        assert build_provenance("x", {}, {"x": {}}) == ["bm25"]

    def test_build_provenance_neither(self):
        assert build_provenance("x", {}, {}) == []

    def test_merge_metadata_dense_priority(self):
        dense_map = {"c1": {"content": "dense text", "metadata": {"section": "A"}}}
        bm25_map = {"c1": {"content": "bm25 text", "metadata": {"section": "B"}}}
        content, meta = merge_metadata("c1", dense_map, bm25_map)
        # Dense content takes priority
        assert content == "dense text"
        # BM25 metadata updates (overwrites section)
        assert meta["section"] == "B"

    def test_merge_metadata_bm25_section_promotion(self):
        dense_map = {"c1": {"content": "dense text", "metadata": {}}}
        bm25_map = {
            "c1": {"content": "bm25 text", "section": "KYC", "subsection": "Part 1"}
        }
        content, meta = merge_metadata("c1", dense_map, bm25_map)
        assert meta["section"] == "KYC"
        assert meta["subsection"] == "Part 1"


# ======================================================================
# 9. Edge Cases
# ======================================================================


class TestEdgeCases:
    def setup_method(self):
        self.engine = FusionEngine()

    def test_both_empty(self):
        results = self.engine.fuse_results([], [], method=FusionMethod.RRF)
        assert results == []

    def test_single_dense_result(self):
        results = self.engine.fuse_results(
            [_make_result("only", 0.99)],
            [],
            method=FusionMethod.RRF,
        )
        assert len(results) == 1
        assert results[0]["chunk_id"] == "only"
        assert results[0]["sources"] == ["dense"]

    def test_single_bm25_result(self):
        results = self.engine.fuse_results(
            [],
            [_make_result("only", 7.5)],
            method=FusionMethod.RRF,
        )
        assert len(results) == 1
        assert results[0]["chunk_id"] == "only"
        assert results[0]["sources"] == ["bm25"]

    def test_identical_chunks_in_both(self):
        """When both lists contain the exact same chunk set."""
        shared = [
            _make_result("s1", 0.9),
            _make_result("s2", 0.8),
        ]
        results = self.engine.fuse_results(shared, shared, method=FusionMethod.RRF)
        assert len(results) == 2
        for r in results:
            assert set(r["sources"]) == {"dense", "bm25"}


# ======================================================================
# 10. FusionReport via fuse_results_with_report()
# ======================================================================


class TestFusionReport:
    def test_report_fields(self):
        engine = FusionEngine()
        fused, report = engine.fuse_results_with_report(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        assert isinstance(report, FusionReport)
        assert report.method == FusionMethod.RRF
        assert report.dense_count == 3
        assert report.bm25_count == 3
        assert report.fused_count == 5
        assert report.overlap_count == 1  # c2 overlaps
        assert report.overlap_percentage == pytest.approx(20.0)  # 1/5 * 100

    def test_report_config_matches(self):
        config = FusionConfig(
            method=FusionMethod.WEIGHTED_SUM, dense_weight=0.7, bm25_weight=0.3
        )
        engine = FusionEngine()
        _, report = engine.fuse_results_with_report(
            DENSE_RESULTS,
            BM25_RESULTS,
            config=config,
        )
        assert report.config.method == FusionMethod.WEIGHTED_SUM
        assert report.config.dense_weight == pytest.approx(0.7)


# ======================================================================
# 11. Strategy Registration
# ======================================================================


class TestStrategyRegistration:
    def teardown_method(self):
        """Restore default LTR strategy after each test."""
        FusionEngine.register_strategy(
            FusionMethod.LEARNING_TO_RANK, LearningToRankStrategy()
        )

    def test_register_custom_strategy(self):
        class CustomStrategy(BaseFusionStrategy):
            def fuse(self, dense_results, bm25_results, config):
                return [
                    {
                        "chunk_id": "custom",
                        "score": 99.0,
                        "sources": ["custom"],
                        "content": "",
                        "metadata": {},
                    }
                ]

        FusionEngine.register_strategy(FusionMethod.LEARNING_TO_RANK, CustomStrategy())
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        assert results[0]["chunk_id"] == "custom"
        assert results[0]["score"] == 99.0

    def test_unregistered_method_raises(self):
        """Requesting a method with no strategy should raise ``ValueError``."""
        # We test this by temporarily removing a known strategy
        saved = FusionEngine._strategy_registry.pop(FusionMethod.LEARNING_TO_RANK, None)
        try:
            with pytest.raises(ValueError, match="No fusion strategy registered"):
                FusionEngine.get_strategy(FusionMethod.LEARNING_TO_RANK)
        finally:
            if saved:
                FusionEngine._strategy_registry[FusionMethod.LEARNING_TO_RANK] = saved


# ======================================================================
# 12. FusionConfig via config kwarg
# ======================================================================


class TestFusionConfig:
    def test_config_object_overrides_kwargs(self):
        engine = FusionEngine()
        config = FusionConfig(
            method=FusionMethod.RRF, rrf_k=10, dense_weight=0.8, bm25_weight=0.2
        )
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            config=config,
            # These kwargs should be ignored when config is provided
            method=FusionMethod.WEIGHTED_SUM,
            rrf_k=60,
        )
        # If RRF was used (not weighted_sum), rrf_score should be set
        for r in results:
            assert r["rrf_score"] is not None

    def test_legacy_kwargs_work_without_config(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.WEIGHTED_SUM,
            dense_weight=0.6,
            bm25_weight=0.4,
        )
        # Weighted sum used → rrf_score should be None
        for r in results:
            assert r["rrf_score"] is None


# ======================================================================
# 13. Output shape matches spec
# ======================================================================


class TestOutputShape:
    """Verify the output matches the required schema shape."""

    def test_output_has_required_fields(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        for r in results:
            assert "chunk_id" in r
            assert "score" in r
            assert "rrf_score" in r
            assert "sources" in r
            assert isinstance(r["sources"], list)
            assert "content" in r
            assert "metadata" in r

    def test_can_create_fused_candidate_from_output(self):
        """Output dicts should be directly parseable into ``FusedCandidate``."""
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        for r in results:
            fc = FusedCandidate(**r)
            assert fc.chunk_id == r["chunk_id"]
            assert fc.score == r["score"]


# ======================================================================
# 14. Learning-to-Rank Strategy
# ======================================================================


class TestLearningToRank:
    def setup_method(self):
        self.engine = FusionEngine()
        # Ensure the default LTR strategy is registered (previous tests may have overridden it)
        FusionEngine.register_strategy(
            FusionMethod.LEARNING_TO_RANK, LearningToRankStrategy()
        )

    def test_ltr_produces_results(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        assert len(results) == 5

    def test_ltr_scores_non_negative(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        for r in results:
            assert r["score"] >= 0.0

    def test_ltr_rrf_score_is_none(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        for r in results:
            assert r["rrf_score"] is None

    def test_ltr_marks_fallback(self):
        """LTR fallback flag should be True when using default strategy."""
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        for r in results:
            assert r.get("ltr_fallback") is True

    def test_ltr_deterministic(self):
        a = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        b = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        assert [r["chunk_id"] for r in a] == [r["chunk_id"] for r in b]

    def test_ltr_preserves_provenance(self):
        results = self.engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.LEARNING_TO_RANK,
        )
        c2 = next(r for r in results if r["chunk_id"] == "c2")
        assert set(c2["sources"]) == {"dense", "bm25"}

    def test_ltr_empty_inputs(self):
        results = self.engine.fuse_results([], [], method=FusionMethod.LEARNING_TO_RANK)
        assert results == []

    def test_ltr_custom_override(self):
        """Register a custom LTR strategy that returns model scores."""

        class MockLTRStrategy(BaseFusionStrategy):
            def fuse(self, dense_results, bm25_results, config):
                merged = []
                for r in dense_results:
                    merged.append(
                        {
                            "chunk_id": r["chunk_id"],
                            "score": 0.99,
                            "rrf_score": None,
                            "dense_score": r["score"],
                            "bm25_score": None,
                            "dense_rank": 1,
                            "bm25_rank": None,
                            "sources": ["dense"],
                            "content": r["content"],
                            "metadata": {},
                            "ltr_fallback": False,
                        }
                    )
                return merged

        FusionEngine.register_strategy(FusionMethod.LEARNING_TO_RANK, MockLTRStrategy())
        try:
            results = self.engine.fuse_results(
                DENSE_RESULTS,
                BM25_RESULTS,
                method=FusionMethod.LEARNING_TO_RANK,
            )
            assert results[0]["score"] == 0.99
            assert results[0]["ltr_fallback"] is False
        finally:
            # Restore default
            FusionEngine.register_strategy(
                FusionMethod.LEARNING_TO_RANK, LearningToRankStrategy()
            )


# ======================================================================
# 15. Rank Conflict Resolution
# ======================================================================


class TestRankConflictResolution:
    def test_no_conflict_when_ranks_close(self):
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": 3, "bm25_rank": 5},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 2
        assert resolved[0]["conflict"] is False

    def test_conflict_when_ranks_far_apart(self):
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": 1, "bm25_rank": 50},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 49
        assert resolved[0]["conflict"] is True

    def test_no_conflict_when_single_source(self):
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": 1, "bm25_rank": None},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 0
        assert resolved[0]["conflict"] is False

    def test_no_conflict_when_both_none(self):
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": None, "bm25_rank": None},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 0
        assert resolved[0]["conflict"] is False

    def test_conflict_threshold_boundary(self):
        """Discrepancy exactly at threshold should NOT be a conflict."""
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": 1, "bm25_rank": 11},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 10
        assert resolved[0]["conflict"] is False

    def test_conflict_just_over_threshold(self):
        """Discrepancy of 11 should be a conflict."""
        candidates = [
            {"chunk_id": "a", "score": 0.5, "dense_rank": 1, "bm25_rank": 12},
        ]
        resolved = resolve_rank_conflicts(candidates)
        assert resolved[0]["rank_discrepancy"] == 11
        assert resolved[0]["conflict"] is True

    def test_rrf_output_has_conflict_fields(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        for r in results:
            assert "rank_discrepancy" in r
            assert "conflict" in r


# ======================================================================
# 16. Multi-Source Overlap
# ======================================================================


class TestMultiSourceOverlap:
    def test_two_sources_partial_overlap(self):
        result = compute_multi_source_overlap(
            {
                "dense": {"a", "b", "c"},
                "bm25": {"b", "c", "d"},
            }
        )
        assert result["overlap_count"] == 2
        assert result["overlap_ids"] == {"b", "c"}
        assert result["union_count"] == 4
        assert result["source_coverage"] == {"dense": 3, "bm25": 3}

    def test_three_sources(self):
        result = compute_multi_source_overlap(
            {
                "dense": {"a", "b"},
                "bm25": {"b", "c"},
                "reranker": {"b", "d"},
            }
        )
        # Only "b" appears in 2+ sources
        assert result["overlap_count"] == 1
        assert result["overlap_ids"] == {"b"}
        assert result["union_count"] == 4

    def test_no_overlap(self):
        result = compute_multi_source_overlap(
            {
                "dense": {"a"},
                "bm25": {"b"},
            }
        )
        assert result["overlap_count"] == 0
        assert result["overlap_ids"] == set()
        assert result["union_count"] == 2

    def test_empty_sources(self):
        result = compute_multi_source_overlap(
            {
                "dense": set(),
                "bm25": set(),
            }
        )
        assert result["overlap_count"] == 0
        assert result["union_count"] == 0

    def test_single_source(self):
        result = compute_multi_source_overlap(
            {
                "dense": {"a", "b"},
            }
        )
        assert result["overlap_count"] == 0
        assert result["union_count"] == 2

    def test_engine_helper(self):
        result = FusionEngine.get_multi_source_overlap(
            {
                "dense": {"a", "b", "c"},
                "bm25": {"b", "c", "d"},
            }
        )
        assert result["overlap_count"] == 2


# ======================================================================
# 17. Source Attribution Summary
# ======================================================================


class TestSourceAttribution:
    def test_counts_per_source(self):
        candidates = [
            {"chunk_id": "a", "sources": ["dense", "bm25"]},
            {"chunk_id": "b", "sources": ["dense"]},
            {"chunk_id": "c", "sources": ["bm25"]},
        ]
        summary = source_attribution_summary(candidates)
        assert summary == {"dense": 2, "bm25": 2}

    def test_empty_candidates(self):
        assert source_attribution_summary([]) == {}

    def test_no_sources_field(self):
        candidates = [{"chunk_id": "a"}]
        assert source_attribution_summary(candidates) == {}

    def test_engine_helper(self):
        engine = FusionEngine()
        results = engine.fuse_results(
            DENSE_RESULTS,
            BM25_RESULTS,
            method=FusionMethod.RRF,
        )
        summary = FusionEngine.get_source_attribution(results)
        assert "dense" in summary
        assert "bm25" in summary
        assert summary["dense"] == 3
        assert summary["bm25"] == 3


# ======================================================================
# 18. Score Normalisation
# ======================================================================


class TestScoreNormalization:
    def test_basic_normalisation(self):
        result = normalize_scores([10.0, 20.0, 30.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])

    def test_identical_scores(self):
        result = normalize_scores([5.0, 5.0, 5.0])
        assert result == pytest.approx([1.0, 1.0, 1.0])

    def test_empty_list(self):
        assert normalize_scores([]) == []

    def test_single_element(self):
        result = normalize_scores([42.0])
        assert result == pytest.approx([1.0])

    def test_already_normalised(self):
        result = normalize_scores([0.0, 0.5, 1.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])


# ======================================================================
# 19. Tie-Breaking
# ======================================================================


class TestTieBreaking:
    def test_break_ties_by_chunk_id(self):
        candidates = [
            {"chunk_id": "z", "score": 1.0},
            {"chunk_id": "a", "score": 1.0},
            {"chunk_id": "m", "score": 1.0},
        ]
        result = break_ties(candidates)
        assert [c["chunk_id"] for c in result] == ["a", "m", "z"]

    def test_break_ties_preserves_score_order(self):
        candidates = [
            {"chunk_id": "a", "score": 2.0},
            {"chunk_id": "b", "score": 1.0},
            {"chunk_id": "c", "score": 2.0},
        ]
        result = break_ties(candidates)
        assert [c["chunk_id"] for c in result] == ["a", "c", "b"]

    def test_break_ties_descending(self):
        candidates = [
            {"chunk_id": "a", "score": 1.0},
            {"chunk_id": "b", "score": 3.0},
            {"chunk_id": "c", "score": 2.0},
        ]
        result = break_ties(candidates, descending=True)
        assert [c["chunk_id"] for c in result] == ["b", "c", "a"]

    def test_break_ties_ascending(self):
        candidates = [
            {"chunk_id": "a", "score": 1.0},
            {"chunk_id": "b", "score": 3.0},
            {"chunk_id": "c", "score": 2.0},
        ]
        result = break_ties(candidates, descending=False)
        assert [c["chunk_id"] for c in result] == ["a", "c", "b"]


# ======================================================================
# 20. Deterministic Rankings Across All Methods
# ======================================================================


class TestCrossMethodDeterminism:
    """Every fusion method must produce deterministic output."""

    def setup_method(self):
        self.engine = FusionEngine()

    @pytest.mark.parametrize(
        "method",
        [
            FusionMethod.RRF,
            FusionMethod.WEIGHTED_SUM,
            FusionMethod.SCORE_FUSION,
            FusionMethod.LEARNING_TO_RANK,
        ],
    )
    def test_deterministic(self, method):
        a = self.engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=method)
        b = self.engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=method)
        assert [r["chunk_id"] for r in a] == [r["chunk_id"] for r in b]
        assert [r["score"] for r in a] == [r["score"] for r in b]

    @pytest.mark.parametrize(
        "method",
        [
            FusionMethod.RRF,
            FusionMethod.WEIGHTED_SUM,
            FusionMethod.SCORE_FUSION,
            FusionMethod.LEARNING_TO_RANK,
        ],
    )
    def test_sorted_descending(self, method):
        results = self.engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=method)
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    @pytest.mark.parametrize(
        "method",
        [
            FusionMethod.RRF,
            FusionMethod.WEIGHTED_SUM,
            FusionMethod.SCORE_FUSION,
            FusionMethod.LEARNING_TO_RANK,
        ],
    )
    def test_all_candidates_present(self, method):
        results = self.engine.fuse_results(DENSE_RESULTS, BM25_RESULTS, method=method)
        ids = {r["chunk_id"] for r in results}
        assert ids == {"c1", "c2", "c3", "c4", "c5"}


# ======================================================================
# 21. Score Fusion vs Weighted Sum Differences
# ======================================================================


class TestScoreFusionVsWeightedSum:
    """Verify that ScoreFusion and WeightedSum produce different results."""

    def setup_method(self):
        self.engine = FusionEngine()

    def test_different_score_distributions(self):
        """With non-uniform scores, the two methods should differ."""
        dense = [
            _make_result("x1", 0.2),
            _make_result("x2", 0.8),
        ]
        bm25 = [
            _make_result("x1", 100.0),
            _make_result("x2", 10.0),
        ]
        score_results = self.engine.fuse_results(
            dense,
            bm25,
            method=FusionMethod.SCORE_FUSION,
            dense_weight=0.5,
            bm25_weight=0.5,
        )
        weighted_results = self.engine.fuse_results(
            dense,
            bm25,
            method=FusionMethod.WEIGHTED_SUM,
            dense_weight=0.5,
            bm25_weight=0.5,
        )
        score_scores = {r["chunk_id"]: r["score"] for r in score_results}
        weighted_scores = {r["chunk_id"]: r["score"] for r in weighted_results}
        # Score fusion uses raw scores; weighted sum normalises first.
        # With these extreme BM25 scores, the ranking may differ.
        # At minimum, the score values should differ.
        assert (
            score_scores["x1"] != weighted_scores["x1"]
            or score_scores["x2"] != weighted_scores["x2"]
        )

    def test_score_fusion_respects_magnitude(self):
        """Score fusion should preserve score magnitude differences."""
        dense = [_make_result("d1", 0.9)]
        bm25 = [_make_result("b1", 1000.0)]
        results = self.engine.fuse_results(
            dense,
            bm25,
            method=FusionMethod.SCORE_FUSION,
            dense_weight=0.5,
            bm25_weight=0.5,
        )
        scores = {r["chunk_id"]: r["score"] for r in results}
        # BM25 score is much larger, so b1 should score higher
        assert scores["b1"] > scores["d1"]
