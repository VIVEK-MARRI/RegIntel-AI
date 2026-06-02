"""Retrieval Fusion Engine.

Combines rankings from multiple retrieval systems (dense, BM25) into a single
ranked candidate list.  Designed around a *strategy pattern* so new fusion
algorithms (Score Fusion, Learning-to-Rank) can be plugged in without touching
the orchestrator.

Public API
----------
* ``FusionEngine.fuse_results()``  – main entry point.
* ``FusionEngine.calculate_rrf_score()``  – standalone helper.
* ``FusionEngine.register_strategy()``  – extend with new algorithms.
"""

from __future__ import annotations

import abc
import logging
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from app.schemas.fusion import FusedCandidate, FusionConfig, FusionMethod, FusionReport
from app.services.fusion.ranking import (
    build_provenance,
    compute_overlap,
    merge_metadata,
    sort_candidates,
)
from app.services.hybrid.strategy import min_max_normalize

logger = logging.getLogger(__name__)


# ======================================================================
# Evaluation hook type
# ======================================================================

@runtime_checkable
class FusionHook(Protocol):
    """Callable invoked before/after fusion for evaluation & monitoring."""

    def __call__(
        self,
        *,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
        fused: Optional[List[Dict[str, Any]]] = None,
        report: Optional[FusionReport] = None,
    ) -> None: ...


# ======================================================================
# Strategy ABC
# ======================================================================

class BaseFusionStrategy(abc.ABC):
    """Abstract base class for fusion strategies."""

    @abc.abstractmethod
    def fuse(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
    ) -> List[Dict[str, Any]]:
        """Fuse two ranked result lists and return merged candidates."""
        ...


# ======================================================================
# RRF Strategy
# ======================================================================

class RRFStrategy(BaseFusionStrategy):
    """Reciprocal Rank Fusion (RRF).

    score(d) = Σ_r  weight_r / (k + rank_r(d))
    """

    @staticmethod
    def calculate_rrf_score(rank: int, k: int = 60) -> float:
        """Calculate the RRF contribution for a given 1-based rank."""
        if rank <= 0:
            return 0.0
        return 1.0 / (k + rank)

    def fuse(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
    ) -> List[Dict[str, Any]]:
        dense_map = {r["chunk_id"]: r for r in dense_results}
        bm25_map = {r["chunk_id"]: r for r in bm25_results}
        all_ids = set(dense_map) | set(bm25_map)

        merged: List[Dict[str, Any]] = []
        for cid in all_ids:
            score = 0.0
            dense_rank: Optional[int] = None
            bm25_rank: Optional[int] = None
            dense_score: Optional[float] = None
            bm25_score: Optional[float] = None

            if cid in dense_map:
                dense_rank = list(dense_map).index(cid) + 1
                dense_score = dense_map[cid]["score"]
                rrf_contrib = self.calculate_rrf_score(dense_rank, config.rrf_k)
                score += config.dense_weight * rrf_contrib

            if cid in bm25_map:
                bm25_rank = list(bm25_map).index(cid) + 1
                bm25_score = bm25_map[cid]["score"]
                rrf_contrib = self.calculate_rrf_score(bm25_rank, config.rrf_k)
                score += config.bm25_weight * rrf_contrib

            content, meta = merge_metadata(cid, dense_map, bm25_map)
            sources = build_provenance(cid, dense_map, bm25_map)

            merged.append({
                "chunk_id": cid,
                "score": score,
                "rrf_score": score,
                "dense_score": dense_score,
                "bm25_score": bm25_score,
                "dense_rank": dense_rank,
                "bm25_rank": bm25_rank,
                "sources": sources,
                "content": content,
                "metadata": meta,
            })

        return sort_candidates(merged)


# ======================================================================
# Weighted Sum Strategy
# ======================================================================

class WeightedSumStrategy(BaseFusionStrategy):
    """Min-Max Normalized Weighted Sum.

    Scores from each source are min-max normalised to [0, 1] then combined
    as: ``dense_weight * norm_dense + bm25_weight * norm_bm25``.
    """

    def fuse(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
    ) -> List[Dict[str, Any]]:
        dense_map = {r["chunk_id"]: r for r in dense_results}
        bm25_map = {r["chunk_id"]: r for r in bm25_results}

        dense_ids = list(dense_map)
        bm25_ids = list(bm25_map)

        raw_dense = [dense_map[c]["score"] for c in dense_ids]
        raw_bm25 = [bm25_map[c]["score"] for c in bm25_ids]

        norm_dense = min_max_normalize(raw_dense)
        norm_bm25 = min_max_normalize(raw_bm25)

        dense_norm_map = dict(zip(dense_ids, norm_dense))
        bm25_norm_map = dict(zip(bm25_ids, norm_bm25))

        all_ids = set(dense_ids) | set(bm25_ids)
        merged: List[Dict[str, Any]] = []

        for cid in all_ids:
            dense_score: Optional[float] = None
            bm25_score: Optional[float] = None
            dense_rank: Optional[int] = None
            bm25_rank: Optional[int] = None
            nd = 0.0
            nb = 0.0

            if cid in dense_map:
                dense_rank = dense_ids.index(cid) + 1
                dense_score = dense_map[cid]["score"]
                nd = dense_norm_map[cid]

            if cid in bm25_map:
                bm25_rank = bm25_ids.index(cid) + 1
                bm25_score = bm25_map[cid]["score"]
                nb = bm25_norm_map[cid]

            score = config.dense_weight * nd + config.bm25_weight * nb
            content, meta = merge_metadata(cid, dense_map, bm25_map)
            sources = build_provenance(cid, dense_map, bm25_map)

            merged.append({
                "chunk_id": cid,
                "score": score,
                "rrf_score": None,
                "dense_score": dense_score,
                "bm25_score": bm25_score,
                "dense_rank": dense_rank,
                "bm25_rank": bm25_rank,
                "sources": sources,
                "content": content,
                "metadata": meta,
            })

        return sort_candidates(merged)


# ======================================================================
# Score Fusion Strategy  (stub – ready for implementation)
# ======================================================================

class ScoreFusionStrategy(BaseFusionStrategy):
    """Direct score averaging / interpolation.

    Placeholder for a future implementation that uses raw calibrated scores
    rather than rank positions.
    """

    def fuse(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "ScoreFusionStrategy is not yet implemented.  "
            "Use RRF or WEIGHTED_SUM for production workloads."
        )


# ======================================================================
# FusionEngine – orchestrator
# ======================================================================

class FusionEngine:
    """Orchestrates retrieval fusion using pluggable strategies.

    Usage::

        engine = FusionEngine()
        results = engine.fuse_results(dense, bm25, config=FusionConfig(method=FusionMethod.RRF))

    The engine supports evaluation hooks that fire before and after fusion
    to enable monitoring, logging, or A/B evaluation without modifying the
    core algorithm.
    """

    # Class-level strategy registry shared across all instances
    _strategy_registry: Dict[FusionMethod, BaseFusionStrategy] = {
        FusionMethod.RRF: RRFStrategy(),
        FusionMethod.WEIGHTED_SUM: WeightedSumStrategy(),
        FusionMethod.SCORE_FUSION: ScoreFusionStrategy(),
    }

    def __init__(self) -> None:
        self._before_hooks: List[FusionHook] = []
        self._after_hooks: List[FusionHook] = []

    # ------------------------------------------------------------------
    # Strategy management
    # ------------------------------------------------------------------

    @classmethod
    def register_strategy(cls, method: FusionMethod, strategy: BaseFusionStrategy) -> None:
        """Register (or replace) a strategy for the given ``FusionMethod``."""
        cls._strategy_registry[method] = strategy
        logger.info("Registered fusion strategy %s → %s", method.value, type(strategy).__name__)

    @classmethod
    def get_strategy(cls, method: FusionMethod) -> BaseFusionStrategy:
        """Look up the strategy for *method*, raising if not registered."""
        strategy = cls._strategy_registry.get(method)
        if strategy is None:
            raise ValueError(f"No fusion strategy registered for method '{method.value}'.")
        return strategy

    # ------------------------------------------------------------------
    # Evaluation hooks
    # ------------------------------------------------------------------

    def add_before_hook(self, hook: FusionHook) -> None:
        """Register a hook that fires *before* fusion."""
        self._before_hooks.append(hook)

    def add_after_hook(self, hook: FusionHook) -> None:
        """Register a hook that fires *after* fusion."""
        self._after_hooks.append(hook)

    def _fire_before(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
    ) -> None:
        for hook in self._before_hooks:
            try:
                hook(dense_results=dense_results, bm25_results=bm25_results, config=config)
            except Exception:
                logger.exception("Before-fusion hook %s raised an error", hook)

    def _fire_after(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        config: FusionConfig,
        fused: List[Dict[str, Any]],
        report: FusionReport,
    ) -> None:
        for hook in self._after_hooks:
            try:
                hook(
                    dense_results=dense_results,
                    bm25_results=bm25_results,
                    config=config,
                    fused=fused,
                    report=report,
                )
            except Exception:
                logger.exception("After-fusion hook %s raised an error", hook)

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_rrf_score(rank: int, k: int = 60) -> float:
        """Convenience accessor – delegates to ``RRFStrategy``."""
        return RRFStrategy.calculate_rrf_score(rank, k)

    def fuse_results(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        *,
        config: Optional[FusionConfig] = None,
        # Legacy positional overrides kept for backward compatibility
        method: Optional[FusionMethod] = None,
        rrf_k: int = 60,
        dense_weight: float = 0.5,
        bm25_weight: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Combine dense and BM25 candidate lists.

        Parameters
        ----------
        dense_results : list[dict]
            Ranked dicts from the dense retrieval service.
        bm25_results : list[dict]
            Ranked dicts from the BM25 retriever.
        config : FusionConfig, optional
            Full configuration object.  Overrides the individual kwargs.
        method, rrf_k, dense_weight, bm25_weight
            Legacy kwargs – used only when *config* is ``None``.

        Returns
        -------
        list[dict]
            Merged candidates sorted by score descending, ready to be
            wrapped in ``FusedCandidate`` or ``RetrievalResult`` objects.
        """
        if config is None:
            config = FusionConfig(
                method=method or FusionMethod.RRF,
                rrf_k=rrf_k,
                dense_weight=dense_weight,
                bm25_weight=bm25_weight,
            )

        # --- before hooks ---
        self._fire_before(dense_results, bm25_results, config)

        # --- delegate to strategy ---
        strategy = self.get_strategy(config.method)
        fused = strategy.fuse(dense_results, bm25_results, config)

        # --- build diagnostic report ---
        dense_ids = {r["chunk_id"] for r in dense_results}
        bm25_ids = {r["chunk_id"] for r in bm25_results}
        overlap = compute_overlap(dense_ids, bm25_ids)

        report = FusionReport(
            method=config.method,
            dense_count=len(dense_results),
            bm25_count=len(bm25_results),
            fused_count=len(fused),
            overlap_count=overlap["overlap_count"],
            overlap_percentage=overlap["overlap_percentage"],
            config=config,
        )

        logger.info(
            "Fusion complete (%s). Dense=%d, BM25=%d → Fused=%d. Overlap=%d (%.1f%%).",
            config.method.value,
            report.dense_count,
            report.bm25_count,
            report.fused_count,
            report.overlap_count,
            report.overlap_percentage,
        )

        # --- after hooks ---
        self._fire_after(dense_results, bm25_results, config, fused, report)

        return fused

    def fuse_results_with_report(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        *,
        config: Optional[FusionConfig] = None,
        method: Optional[FusionMethod] = None,
        rrf_k: int = 60,
        dense_weight: float = 0.5,
        bm25_weight: float = 0.5,
    ) -> tuple[List[Dict[str, Any]], FusionReport]:
        """Same as ``fuse_results`` but also returns the ``FusionReport``."""
        if config is None:
            config = FusionConfig(
                method=method or FusionMethod.RRF,
                rrf_k=rrf_k,
                dense_weight=dense_weight,
                bm25_weight=bm25_weight,
            )

        fused = self.fuse_results(dense_results, bm25_results, config=config)

        dense_ids = {r["chunk_id"] for r in dense_results}
        bm25_ids = {r["chunk_id"] for r in bm25_results}
        overlap = compute_overlap(dense_ids, bm25_ids)

        report = FusionReport(
            method=config.method,
            dense_count=len(dense_results),
            bm25_count=len(bm25_results),
            fused_count=len(fused),
            overlap_count=overlap["overlap_count"],
            overlap_percentage=overlap["overlap_percentage"],
            config=config,
        )
        return fused, report
