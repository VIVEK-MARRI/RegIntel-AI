"""Per-factor confidence calculators.

Each function returns a raw factor score in ``[0.0, 1.0]`` plus a
small diagnostics dict.  These are pure functions — the
:class:`ConfidenceCalculator` is responsible for the weighting and
aggregation.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _clamp01(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _safe_mean(values: Sequence[float]) -> float:
    values = [v for v in values if v is not None and not math.isnan(v) and not math.isinf(v)]
    if not values:
        return 0.0
    return _clamp01(statistics.fmean(values))


def _weighted_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return _safe_mean(values)


# ─── Retrieval relevance ────────────────────────────────────────────────────


def retrieval_relevance_factor(
    *,
    retrieval_scores: Optional[Sequence[float]] = None,
    chunk_scores: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Mean of retrieval scores.

    Uses ``retrieval_scores`` when supplied, otherwise falls back to
    each chunk's ``score`` field.  Empty input returns 0.0.
    """
    if retrieval_scores is not None and len(retrieval_scores) > 0:
        values = list(retrieval_scores)
    elif chunk_scores is not None and len(chunk_scores) > 0:
        values = list(chunk_scores)
    else:
        return {"score": 0.0, "details": {"count": 0, "mean": 0.0, "max": 0.0, "min": 0.0}}

    score = _safe_mean(values)
    return {
        "score": score,
        "details": {
            "count": len(values),
            "mean": score,
            "max": max(values) if values else 0.0,
            "min": min(values) if values else 0.0,
        },
    }


# ─── Reranker confidence ────────────────────────────────────────────────────


def reranker_confidence_factor(
    reranker_scores: Optional[Sequence[float]],
) -> Dict[str, Any]:
    """Mean of cross-encoder scores.  ``None`` ⇒ unavailable."""
    if reranker_scores is None or len(reranker_scores) == 0:
        return {"score": 0.0, "available": False, "details": {"count": 0}}
    values = list(reranker_scores)
    score = _safe_mean(values)
    return {
        "score": score,
        "available": True,
        "details": {
            "count": len(values),
            "mean": score,
            "max": max(values) if values else 0.0,
            "min": min(values) if values else 0.0,
        },
    }


# ─── Source agreement ───────────────────────────────────────────────────────


def source_agreement_factor(chunks: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """How consistently the chunks agree on the source regulator.

    Heuristic: if all chunks come from a single source, the answer is
    grounded in a single corpus (good).  If they come from multiple
    sources and the answer makes a single-source claim, that's a
    weaker signal.

    Score = 1.0 when all chunks share a source, decays to ~0.5 when
    the corpus is split 50/50 across two sources, and bottoms out
    around 0.0 for many-source dilutions.
    """
    sources: List[str] = []
    for c in chunks:
        s = c.get("source")
        if isinstance(s, str):
            sources.append(s)
        elif s is not None:
            sources.append(str(s))

    if not sources:
        return {"score": 0.0, "details": {"unique_sources": 0, "primary_share": 0.0}}

    counts: Dict[str, int] = {}
    for s in sources:
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    primary_share = max(counts.values()) / total if total else 0.0
    # Map primary share (0.5..1.0] to [0.0..1.0] linearly.
    score = max(0.0, min(1.0, (primary_share - 0.5) * 2.0))
    return {
        "score": score,
        "details": {
            "unique_sources": len(counts),
            "primary_share": primary_share,
            "sources": sorted(counts.keys()),
        },
    }


# ─── Chunk coverage ────────────────────────────────────────────────────────


def chunk_coverage_factor(
    chunks: Sequence[Mapping[str, Any]],
    *,
    min_chunks_for_full_coverage: int = 5,
) -> Dict[str, Any]:
    """Score the count + density of supporting chunks.

    ``min_chunks_for_full_coverage`` chunks ⇒ 1.0; 0 chunks ⇒ 0.0;
    in between, linear in count, but also penalised slightly when
    scores are very low (the corpus is "wide but thin").
    """
    n = len(chunks)
    if n == 0:
        return {"score": 0.0, "details": {"count": 0}}

    count_score = min(1.0, n / float(max(1, min_chunks_for_full_coverage)))

    scores = [float(c.get("score", 0.0) or 0.0) for c in chunks]
    mean_score = _safe_mean(scores) if scores else 0.0
    # Density factor: if the average score is low, we trust the
    # coverage less.  Scale to [0.5, 1.0] so it never fully cancels.
    density = 0.5 + 0.5 * mean_score

    score = _clamp01(count_score * density)
    return {
        "score": score,
        "details": {
            "count": n,
            "count_score": count_score,
            "density": density,
            "mean_chunk_score": mean_score,
        },
    }


# ─── Citation coverage ─────────────────────────────────────────────────────


def citation_coverage_factor(
    coverage: Optional[float],
    answer: Mapping[str, Any],
) -> Dict[str, Any]:
    """Citation coverage score.

    Prefers a precomputed ``coverage`` ratio (from Module 5.2); falls
    back to a heuristic that counts ``supporting_evidence`` items vs.
    the number of non-empty answer fields.
    """
    if coverage is not None:
        score = _clamp01(float(coverage))
        return {
            "score": score,
            "details": {"source": "module_5_2", "ratio": score},
        }

    # Heuristic fallback.
    supporting = answer.get("supporting_evidence") or []
    fields_filled = sum(
        1
        for k in ("executive_summary", "detailed_explanation")
        if isinstance(answer.get(k), str) and answer[k].strip()
    )
    if fields_filled == 0:
        return {"score": 0.0, "details": {"source": "heuristic", "supporting": len(supporting), "fields_filled": 0}}

    # Each supporting evidence roughly corresponds to one answer field.
    ratio = min(1.0, len(supporting) / float(fields_filled))
    return {
        "score": ratio,
        "details": {"source": "heuristic", "supporting": len(supporting), "fields_filled": fields_filled, "ratio": ratio},
    }


__all__ = [
    "retrieval_relevance_factor",
    "reranker_confidence_factor",
    "source_agreement_factor",
    "chunk_coverage_factor",
    "citation_coverage_factor",
]
