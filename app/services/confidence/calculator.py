"""ConfidenceCalculator — weighted aggregation of factor scores.

Takes the per-factor :class:`ConfidenceFactor` outputs, normalises the
weights, and produces the final confidence in ``[0.0, 1.0]``.

Weight redistribution
---------------------

If a factor is unavailable (e.g. reranker scores were not provided),
its weight is removed and the remaining weights are normalised so
they still sum to 1.0.  This means an answer with no rerank signal
isn't automatically penalised — the engine just relies more on the
other factors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.schemas.confidence import (
    DEFAULT_WEIGHTS,
    ConfidenceBreakdown,
    ConfidenceFactor,
    ConfidenceFactorName,
    level_for,
)

logger = logging.getLogger(__name__)


class FactorCalculator:
    """Computes a single :class:`ConfidenceFactor`."""

    def __init__(
        self,
        *,
        name: ConfidenceFactorName,
        score: float,
        weight: float,
        available: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.raw_score = max(0.0, min(1.0, float(score)))
        self.weight = max(0.0, float(weight))
        self.available = bool(available)
        self.details = details or {}

    def to_factor(self, contribution: float) -> ConfidenceFactor:
        return ConfidenceFactor(
            name=self.name,
            score=self.raw_score if self.available else 0.0,
            weight=self.weight,
            contribution=contribution,
            available=self.available,
            details=self.details,
        )


class ConfidenceCalculator:
    """Weighted aggregation of factor scores."""

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self.weights: Dict[str, float] = dict(weights or DEFAULT_WEIGHTS)
        # Validate keys.
        for key in self.weights:
            if key not in {n.value for n in ConfidenceFactorName}:
                raise ValueError(f"unknown factor name in weights: {key!r}")

    # ── Public API ─────────────────────────────────────────────────────────

    def aggregate(
        self, factors: List[FactorCalculator]
    ) -> Tuple[float, ConfidenceBreakdown]:
        """Aggregate factors into a final confidence score and breakdown.

        Returns
        -------
        (confidence, breakdown)
        """
        active = [f for f in factors if f.available and f.weight > 0]
        total_weight = sum(f.weight for f in active)
        if total_weight <= 0:
            # Nothing to aggregate — neutral 0.0 with full breakdown.
            breakdown = self._empty_breakdown(factors)
            return 0.0, breakdown

        # Compute each factor's contribution (its share of the final
        # confidence).  Sum of contributions = confidence in [0, 1].
        confidence = 0.0
        factor_models: List[ConfidenceFactor] = []
        for f in factors:
            if f.available and f.weight > 0:
                normalised_weight = f.weight / total_weight
                contribution = f.raw_score * normalised_weight
                confidence += contribution
                factor_models.append(f.to_factor(contribution))
            else:
                # Unavailable factor — still record with weight 0.
                factor_models.append(f.to_factor(0.0))

        # Effective (normalised) weights for the response.
        effective_weights = {
            f.name.value: (f.weight / total_weight if (f.available and f.weight > 0) else 0.0)
            for f in factors
        }
        breakdown = ConfidenceBreakdown(
            factors=factor_models,
            weights=effective_weights,
            total_weight=total_weight,
        )
        return max(0.0, min(1.0, confidence)), breakdown

    @staticmethod
    def level_for(confidence: float):
        return level_for(confidence)

    # ── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _empty_breakdown(factors: List[FactorCalculator]) -> ConfidenceBreakdown:
        return ConfidenceBreakdown(
            factors=[
                f.to_factor(0.0) for f in factors
            ],
            weights={f.name.value: 0.0 for f in factors},
            total_weight=0.0,
        )


__all__ = ["ConfidenceCalculator", "FactorCalculator"]
