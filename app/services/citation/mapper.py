"""Citation Mapper — match claims to chunks.

The mapper scores each claim against each chunk and returns the best
match (or top-K matches) per claim.  The default scorer is
:func:`token_overlap` — a token-Jaccard / cosine hybrid that is:

* deterministic
* cheap (no LLM, no embedding model)
* robust to paraphrasing when the answer and chunks share key terms

If a future module wants semantic scoring, swap in an embedding-based
scorer that implements the same interface.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.schemas.answer_generation import RetrievedChunk
from app.schemas.citation import Claim

logger = logging.getLogger(__name__)


# ─── Stopwords ───────────────────────────────────────────────────────────────


_STOPWORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "of", "for", "to", "in",
    "on", "at", "by", "with", "is", "are", "was", "were", "be", "been",
    "being", "as", "from", "this", "that", "these", "those", "it", "its",
    "i", "you", "we", "they", "he", "she", "him", "her", "them", "our",
    "your", "their", "my", "me", "us", "do", "does", "did", "done",
    "have", "has", "had", "having", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must", "not", "no", "nor", "so",
    "than", "too", "very", "such", "also", "into", "out", "up", "down",
    "over", "under", "again", "further", "once", "any", "all", "each",
    "some", "most", "other", "more", "less", "many", "few", "both",
    "either", "neither", "own", "same", "what", "which", "who", "whom",
    "whose", "where", "when", "why", "how", "here", "there", "now",
    "then", "because", "while", "although", "though", "since", "until",
    "against", "between", "through", "before", "after", "above", "below",
}


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")


def _tokenise(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _content_keywords(text: str) -> List[str]:
    return [t for t in _tokenise(text) if t not in _STOPWORDS and len(t) > 2]


# ─── Scoring ────────────────────────────────────────────────────────────────


def token_overlap(claim_text: str, chunk_text: str) -> float:
    """Score a (claim, chunk) pair in ``[0.0, 1.0]``.

    Uses a weighted blend:

      * 0.6 × cosine similarity over content-keyword term frequencies
      * 0.4 × Jaccard overlap of unique content keywords

    Empty / stopword-only inputs return 0.0.
    """
    a = _content_keywords(claim_text)
    b = _content_keywords(chunk_text)
    if not a or not b:
        return 0.0

    ca, cb = Counter(a), Counter(b)
    dot = sum(ca[t] * cb.get(t, 0) for t in ca)
    norm_a = math.sqrt(sum(v * v for v in ca.values()))
    norm_b = math.sqrt(sum(v * v for v in cb.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    cosine = dot / (norm_a * norm_b)

    set_a, set_b = set(ca), set(cb)
    inter = set_a & set_b
    union = set_a | set_b
    jaccard = (len(inter) / len(union)) if union else 0.0

    return 0.6 * cosine + 0.4 * jaccard


def section_boost(claim: Claim, chunk: RetrievedChunk) -> float:
    """Small additive boost when a claim text references the chunk section."""
    if not claim.text or not chunk.section:
        return 0.0
    section_lower = chunk.section.lower().strip()
    if not section_lower:
        return 0.0
    if section_lower in claim.text.lower():
        return 0.1
    # Word-level fuzzy match.
    claim_tokens = set(_tokenise(claim.text))
    section_tokens = set(_tokenise(chunk.section))
    if not claim_tokens or not section_tokens:
        return 0.0
    overlap = claim_tokens & section_tokens
    if len(overlap) >= 1:
        return 0.05
    return 0.0


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class ClaimChunkMatch:
    """Result of mapping one claim to one chunk."""

    claim: Claim
    chunk: RetrievedChunk
    similarity: float
    section_boost: float
    final_score: float


# ─── Scorer Protocol ─────────────────────────────────────────────────────────


class TokenOverlapScorer:
    """Default lexical scorer (token overlap + section boost)."""

    def __init__(self, *, section_boost_weight: float = 0.1) -> None:
        self.section_boost_weight = section_boost_weight

    def score(self, claim: Claim, chunk: RetrievedChunk) -> float:
        base = token_overlap(claim.text, chunk.content)
        boost = section_boost(claim, chunk) * self.section_boost_weight
        return min(1.0, base + boost)


# ─── Mapper ──────────────────────────────────────────────────────────────────


class CitationMapper:
    """Map claims to chunks.

    For each claim, return the top-K matching chunks (default 1) with
    similarity above ``min_similarity``.
    """

    def __init__(
        self,
        *,
        scorer: Optional[TokenOverlapScorer] = None,
        top_k: int = 1,
        min_similarity: float = 0.05,
    ) -> None:
        self.scorer = scorer or TokenOverlapScorer()
        self.top_k = max(1, int(top_k))
        self.min_similarity = float(min_similarity)

    def map_claim(
        self, claim: Claim, chunks: Sequence[RetrievedChunk]
    ) -> List[ClaimChunkMatch]:
        scored: List[ClaimChunkMatch] = []
        for chunk in chunks:
            base = token_overlap(claim.text, chunk.content)
            boost = section_boost(claim, chunk) * self.scorer.section_boost_weight
            final = min(1.0, base + boost)
            if final < self.min_similarity:
                continue
            scored.append(
                ClaimChunkMatch(
                    claim=claim,
                    chunk=chunk,
                    similarity=base,
                    section_boost=boost,
                    final_score=final,
                )
            )
        scored.sort(key=lambda m: m.final_score, reverse=True)
        return scored[: self.top_k]

    def map_claims(
        self,
        claims: Iterable[Claim],
        chunks: Sequence[RetrievedChunk],
    ) -> List[Tuple[Claim, List[ClaimChunkMatch]]]:
        return [(claim, self.map_claim(claim, chunks)) for claim in claims]

    def best_match(
        self, claim: Claim, chunks: Sequence[RetrievedChunk]
    ) -> Optional[ClaimChunkMatch]:
        matches = self.map_claim(claim, chunks)
        return matches[0] if matches else None


__all__ = [
    "CitationMapper",
    "TokenOverlapScorer",
    "ClaimChunkMatch",
    "token_overlap",
    "section_boost",
]
