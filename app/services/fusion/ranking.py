"""Ranking utilities used by the Fusion Engine.

Pure functions for deterministic sorting, overlap diagnostics, metadata
merging, and provenance tracking.  Kept separate from the engine itself
so they can be unit-tested and reused independently.
"""

from typing import Any, Dict, List, Tuple

from app.services.hybrid.strategy import min_max_normalize as _min_max_normalize


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def sort_candidates(
    candidates: List[Dict[str, Any]],
    *,
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Sort fused candidates deterministically.

    Primary key   : ``score`` (descending by default).
    Tiebreaker   : ``chunk_id`` (ascending, lexicographic) for reproducibility.
    """
    return sorted(
        candidates,
        key=lambda c: (-c["score"] if descending else c["score"], c["chunk_id"]),
    )


# ---------------------------------------------------------------------------
# Overlap / Diagnostics
# ---------------------------------------------------------------------------

def compute_overlap(
    dense_ids: set[str],
    bm25_ids: set[str],
) -> Dict[str, Any]:
    """Return overlap statistics between two ID sets.

    Returns a dict with ``overlap_ids``, ``overlap_count``, ``union_count``,
    and ``overlap_percentage``.
    """
    overlap = dense_ids & bm25_ids
    union = dense_ids | bm25_ids
    pct = (len(overlap) / len(union) * 100.0) if union else 0.0
    return {
        "overlap_ids": overlap,
        "overlap_count": len(overlap),
        "union_count": len(union),
        "overlap_percentage": pct,
    }


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def build_provenance(
    chunk_id: str,
    dense_map: Dict[str, Any],
    bm25_map: Dict[str, Any],
) -> List[str]:
    """Return a list of source names that contributed ``chunk_id``."""
    sources: List[str] = []
    if chunk_id in dense_map:
        sources.append("dense")
    if chunk_id in bm25_map:
        sources.append("bm25")
    return sources


# ---------------------------------------------------------------------------
# Metadata merging
# ---------------------------------------------------------------------------

def merge_metadata(
    chunk_id: str,
    dense_map: Dict[str, Dict[str, Any]],
    bm25_map: Dict[str, Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Merge content and metadata from dense and BM25 maps for a chunk.

    Dense content takes priority.  BM25-specific keys (``section``,
    ``subsection``) are preserved when not already present.

    Returns:
        ``(content, metadata)`` tuple.
    """
    content = ""
    meta: Dict[str, Any] = {}

    if chunk_id in dense_map:
        content = dense_map[chunk_id]["content"]
        meta.update(dense_map[chunk_id].get("metadata") or {})

    if chunk_id in bm25_map:
        if not content:
            content = bm25_map[chunk_id]["content"]
        bm25_meta = bm25_map[chunk_id].get("metadata") or {}
        meta.update(bm25_meta)
        # Promote top-level BM25 keys into metadata when absent
        for key in ("section", "subsection"):
            if key not in meta and key in bm25_map[chunk_id]:
                meta[key] = bm25_map[chunk_id][key]

    return content, meta


# ---------------------------------------------------------------------------
# Rank conflict resolution
# ---------------------------------------------------------------------------

def resolve_rank_conflicts(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect and annotate rank conflicts.

    A rank *conflict* occurs when a chunk appears at very different positions
    in two source lists (e.g. rank 1 in dense but rank 50 in BM25).  Such
    chunks get a ``rank_discrepancy`` field and a ``conflict`` flag so
    downstream consumers can decide how to handle them.

    Parameters
    ----------
    candidates : list[dict]
        Fused candidate dicts that must contain ``dense_rank`` and ``bm25_rank``.

    Returns
    -------
    list[dict]
        The same list with ``rank_discrepancy`` and ``conflict`` keys added.
    """
    for c in candidates:
        dr = c.get("dense_rank")
        br = c.get("bm25_rank")
        if dr is not None and br is not None:
            discrepancy = abs(dr - br)
            c["rank_discrepancy"] = discrepancy
            c["conflict"] = discrepancy > _RANK_CONFLICT_THRESHOLD
        else:
            c["rank_discrepancy"] = 0
            c["conflict"] = False
    return candidates


_RANK_CONFLICT_THRESHOLD = 10  # positions


# ---------------------------------------------------------------------------
# Multi-source rank lookup helper
# ---------------------------------------------------------------------------

def _rank_of(chunk_id: str, result_map: Dict[str, Any], ordered_ids: List[str]) -> int | None:
    """Return the 1-based rank of *chunk_id* in *ordered_ids*, or ``None``."""
    if chunk_id not in result_map:
        return None
    try:
        return ordered_ids.index(chunk_id) + 1
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Score normalisation re-export
# ---------------------------------------------------------------------------

def normalize_scores(scores: List[float]) -> List[float]:
    """Min-max normalise a list of scores to [0, 1].

    Delegates to :func:`app.services.hybrid.strategy.min_max_normalize`.
    """
    return _min_max_normalize(scores)


# ---------------------------------------------------------------------------
# Multi-source overlap (N sources)
# ---------------------------------------------------------------------------

def compute_multi_source_overlap(
    source_ids: Dict[str, set[str]],
) -> Dict[str, Any]:
    """Compute overlap statistics across *N* source ID sets.

    Parameters
    ----------
    source_ids : dict[str, set[str]]
        Mapping of source name → set of chunk IDs.

    Returns
    -------
    dict
        ``overlap_count``  – IDs present in ≥ 2 sources.
        ``overlap_ids``    – the actual IDs.
        ``union_count``    – total unique IDs.
        ``source_coverage`` – dict mapping each source to its ID count.
    """
    all_ids: set[str] = set()
    for ids in source_ids.values():
        all_ids |= ids

    # IDs that appear in 2+ sources
    id_counts: Dict[str, int] = {}
    for ids in source_ids.values():
        for cid in ids:
            id_counts[cid] = id_counts.get(cid, 0) + 1
    overlap_ids = {cid for cid, cnt in id_counts.items() if cnt >= 2}

    return {
        "overlap_count": len(overlap_ids),
        "overlap_ids": overlap_ids,
        "union_count": len(all_ids),
        "source_coverage": {name: len(ids) for name, ids in source_ids.items() },
    }


# ---------------------------------------------------------------------------
# Deterministic tie-breaking
# ---------------------------------------------------------------------------

def break_ties(
    candidates: List[Dict[str, Any]],
    *,
    secondary_key: str = "chunk_id",
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Break score ties deterministically.

    When two candidates have the same ``score``, the *secondary_key* is used
    as a tiebreaker.  By default this is ``chunk_id`` (lexicographic ascending).

    Parameters
    ----------
    candidates : list[dict]
        Fused candidates.
    secondary_key : str
        Field name to use for tie-breaking.
    descending : bool
        Whether the primary sort is descending.

    Returns
    -------
    list[dict]
        Re-sorted candidates.
    """
    return sorted(
        candidates,
        key=lambda c: (
            -c["score"] if descending else c["score"],
            c.get(secondary_key, ""),
        ),
    )


# ---------------------------------------------------------------------------
# Source attribution summary
# ---------------------------------------------------------------------------

def source_attribution_summary(
    candidates: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Count how many fused candidates came from each source.

    Parameters
    ----------
    candidates : list[dict]
        Each must have a ``sources`` field (list[str]).

    Returns
    -------
    dict[str, int]
        Mapping of source name → count.
    """
    counts: Dict[str, int] = {}
    for c in candidates:
        for src in c.get("sources", []):
            counts[src] = counts.get(src, 0) + 1
    return counts
