"""Sentence-level claim extraction for the citation engine.

Splits free-form text into individual factual claims.  The extractor
is intentionally rule-based and deterministic — no LLM call — so the
citation engine can run in CI / offline benchmarks and produce stable
results.

Rules
-----
* Split on ``.``, ``?``, ``!``, ``\n``, and paragraph boundaries
  (``\n\n``).
* Discard fragments shorter than ``min_chars`` (default 12).
* Discard fragments that are pure questions (end with ``?``).
* Discard fragments that are pure punctuation.
* Strip enclosing quotes / parentheses.
* Skip duplicate fragments within a single block.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable, List

from app.schemas.citation import Claim

logger = logging.getLogger(__name__)


_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[\.\?\!\n])\s+(?=[A-Z(])"  # sentence boundary followed by capital
    r"|"
    r"\n\s*\n"  # paragraph break
)


_TRIM_RE = re.compile(
    r"^[\s\-\u2013\u2014\*\u2022\"'`\(\)\[\]]+"
    r"|"
    r"[\s\u2013\u2014\"'`\(\)\[\]]+$"
)


def _is_question(text: str) -> bool:
    return text.rstrip().endswith("?")


def _is_pure_punct(text: str) -> bool:
    return all(not ch.isalnum() for ch in text)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """Split ``text`` into a list of non-empty claim strings.

    Public helper (also exported) — useful for unit tests and any
    caller that needs the raw splits without the claim wrapper.
    """
    if not text:
        return []
    text = _normalise(text)
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    cleaned: List[str] = []
    for raw in parts:
        s = _TRIM_RE.sub("", raw).strip()
        if s and not _is_pure_punct(s):
            cleaned.append(s)
    return cleaned


class ClaimExtractor:
    """Convert answer-section text into :class:`Claim` objects."""

    def __init__(
        self,
        *,
        min_chars: int = 12,
        max_claims_per_section: int = 50,
        drop_questions: bool = True,
    ) -> None:
        self.min_chars = max(4, int(min_chars))
        self.max_claims_per_section = max(1, int(max_claims_per_section))
        self.drop_questions = drop_questions

    def extract(self, text: str, section: str) -> List[Claim]:
        """Return a list of :class:`Claim` for ``text``."""
        sentences = split_into_sentences(text)
        seen: set[str] = set()
        claims: List[Claim] = []
        for sentence in sentences:
            if len(sentence) < self.min_chars:
                continue
            if self.drop_questions and _is_question(sentence):
                continue
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append(Claim(text=sentence, section=section))
            if len(claims) >= self.max_claims_per_section:
                break
        return claims

    def extract_all(
        self, sections: Iterable[tuple[str, str]]
    ) -> List[Claim]:
        """Extract from an iterable of ``(section_name, text)`` tuples."""
        out: List[Claim] = []
        for section_name, text in sections:
            out.extend(self.extract(text, section_name))
        return out


__all__ = ["ClaimExtractor", "split_into_sentences"]
