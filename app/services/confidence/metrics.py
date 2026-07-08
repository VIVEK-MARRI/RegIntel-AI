"""In-process metrics for the confidence engine.

Tracks:

* per-factor score distribution (count, mean, p50, p95)
* per-level distribution (HIGH / MEDIUM / LOW)
* per-flag frequency
* total request count

The collector is thread-safe (uses a simple lock).  In production
this would forward to Prometheus / OpenTelemetry; for now it's a
fast in-memory store that the API can expose for observability.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable

from app.schemas.confidence import ConfidenceFactorName, ConfidenceFlag, ConfidenceLevel

logger = logging.getLogger(__name__)


@dataclass
class _FactorStats:
    count: int = 0
    sum: float = 0.0
    sum_sq: float = 0.0
    min: float = math.inf
    max: float = -math.inf

    def record(self, value: float) -> None:
        self.count += 1
        self.sum += value
        self.sum_sq += value * value
        if value < self.min:
            self.min = value
        if value > self.max:
            self.max = value

    def mean(self) -> float:
        return (self.sum / self.count) if self.count else 0.0

    def stdev(self) -> float:
        if self.count < 2:
            return 0.0
        mean = self.mean()
        var = (self.sum_sq / self.count) - (mean * mean)
        return math.sqrt(max(0.0, var))

    def to_dict(self) -> Dict[str, float]:
        return {
            "count": self.count,
            "mean": self.mean(),
            "min": self.min if self.count else 0.0,
            "max": self.max if self.count else 0.0,
            "stdev": self.stdev(),
        }


@dataclass
class ConfidenceMetrics:
    """Thread-safe in-process metrics collector."""

    total_requests: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    confidence_sum: float = 0.0
    confidence_min: float = math.inf
    confidence_max: float = -math.inf
    factor_stats: Dict[str, _FactorStats] = field(
        default_factory=lambda: defaultdict(_FactorStats)
    )
    flag_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── Public API ─────────────────────────────────────────────────────────

    def record(
        self,
        *,
        confidence: float,
        level: ConfidenceLevel,
        factor_scores: Dict[ConfidenceFactorName, float],
        flags: Iterable[ConfidenceFlag] = (),
    ) -> None:
        with self._lock:
            self.total_requests += 1
            self.confidence_sum += confidence
            if confidence < self.confidence_min:
                self.confidence_min = confidence
            if confidence > self.confidence_max:
                self.confidence_max = confidence

            if level == ConfidenceLevel.HIGH:
                self.high_count += 1
            elif level == ConfidenceLevel.MEDIUM:
                self.medium_count += 1
            else:
                self.low_count += 1

            for name, score in factor_scores.items():
                self.factor_stats[name.value].record(score)
            for flag in flags:
                self.flag_counts[flag.value] += 1

    def reset(self) -> None:
        with self._lock:
            self.total_requests = 0
            self.high_count = 0
            self.medium_count = 0
            self.low_count = 0
            self.confidence_sum = 0.0
            self.confidence_min = math.inf
            self.confidence_max = -math.inf
            self.factor_stats = defaultdict(_FactorStats)
            self.flag_counts = defaultdict(int)

    def snapshot(self) -> Dict[str, object]:
        """Return a JSON-serialisable snapshot of current metrics."""
        with self._lock:
            mean_conf = (
                self.confidence_sum / self.total_requests
                if self.total_requests
                else 0.0
            )
            return {
                "total_requests": self.total_requests,
                "level_distribution": {
                    "high": self.high_count,
                    "medium": self.medium_count,
                    "low": self.low_count,
                },
                "confidence": {
                    "mean": mean_conf,
                    "min": self.confidence_min if self.total_requests else 0.0,
                    "max": self.confidence_max if self.total_requests else 0.0,
                },
                "factor_stats": {
                    name: stats.to_dict() for name, stats in self.factor_stats.items()
                },
                "flag_counts": dict(self.flag_counts),
            }


__all__ = ["ConfidenceMetrics"]
