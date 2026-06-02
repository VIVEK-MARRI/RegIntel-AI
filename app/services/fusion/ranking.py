"""Ranking utilities used by the Fusion Engine.

Pure functions for deterministic sorting, overlap diagnostics, metadata
merging, and provenance tracking.  Kept separate from the engine itself
so they can be unit-tested and reused independently.
"""

from typing import List, Dict, Any, Set, Tuple


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def sort_candidates(
    candidates: List[Dict[str, Any]],
    *,
    descending: bool = True,
) -> List[Dict[str, Any]]:
    """Sort fused candidates deterministically.

    Primary key:   ``score`` (descending by default).
    Tiebreaker:    ``chunk_id`` (ascending, lexicographic) for reproducibility.
    """
    return sorted(
        candidates,
        key=lambda c: (-c["score"] if descending else c["score"], c["chunk_id"]),
    )


# ---------------------------------------------------------------------------
# Overlap / Diagnostics
# ---------------------------------------------------------------------------

def compute_overlap(
    dense_ids: Set[str],
    bm25_ids: Set[str],
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
