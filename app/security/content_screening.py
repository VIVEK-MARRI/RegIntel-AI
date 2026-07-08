"""Content screening for AI-specific threats (P0.3).

This module provides two lightweight, dependency-free screeners used to
defend against threats that classic API security does not cover:

* :class:`PIIDetector`        — heuristic detection of Indian-regulatory
  PII shapes (PAN, Aadhaar, email, phone, labelled account numbers) so the
  governance layer can block/flag documents and answers that leak them.
* :class:`PromptInjectionScreen` — heuristic detection of instruction-like
  phrases ("ignore previous instructions", role reassignment, delimiter
  breaking) embedded in ingested text or user queries.

Both raise their findings through the existing :class:`ThreatDetector`
infrastructure (never a parallel system).  The screeners are intentionally
regex/keyword based (room to upgrade to a classifier later) and are safe to
run on every chunk and every query.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.security.threat_detection import (
    ThreatDetector,
    ThreatLevel,
    ThreatType,
    get_threat_detector,
)

logger = logging.getLogger(__name__)


# ─── PII detection ────────────────────────────────────────────────────────

# Shapes relevant to Indian regulatory documents.  Tuned to minimise false
# positives while still catching synthetic test strings.
_PII_PATTERNS: List[re.Pattern[str]] = [
    # PAN: 5 letters + 4 digits + 1 letter, e.g. ABCDE1234F
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    # Aadhaar: 12 digits, first digit 2-9 (optionally space/dash separated)
    re.compile(r"\b[2-9][0-9]{3}[\s-]?[0-9]{4}[\s-]?[0-9]{4}\b"),
    # Email
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    # Indian phone: +91 or 10-digit starting 6-9
    re.compile(r"\b(?:\+91[\s-]?)?[6-9][0-9]{9}\b"),
    # Labelled account number, e.g. "Account No: 123456789012"
    re.compile(
        r"\b(?:account|acct|a/c|account\s*no|account\s*number)[\s:.\-]*[0-9]{9,18}\b",
        re.IGNORECASE,
    ),
]


@dataclass
class ScreenHit:
    kind: str
    pattern: str
    snippet: str


@dataclass
class ScreeningResult:
    flagged: bool
    hits: List[ScreenHit] = field(default_factory=list)

    @property
    def matched(self) -> List[str]:
        return [h.kind for h in self.hits]


class PIIDetector:
    """Heuristic detector for PII shapes in free text."""

    def detect(self, text: str) -> ScreeningResult:
        if not text:
            return ScreeningResult(flagged=False)
        hits: List[ScreenHit] = []
        for pat in _PII_PATTERNS:
            for m in pat.finditer(text):
                hits.append(
                    ScreenHit(
                        kind="pii",
                        pattern=pat.pattern,
                        snippet=text[max(0, m.start() - 10):m.end() + 10],
                    )
                )
        return ScreeningResult(flagged=bool(hits), hits=hits)


def flatten_text(values) -> str:  # type: ignore[no-untyped-def]
    """Flatten arbitrary nested inputs/outputs into a single string."""
    parts: List[str] = []
    if values is None:
        return ""
    if isinstance(values, str):
        return values
    if isinstance(values, (int, float, bool)):
        return str(values)
    if isinstance(values, dict):
        for v in values.values():
            parts.append(flatten_text(v))
    elif isinstance(values, (list, tuple, set)):
        for v in values:  # type: ignore[assignment]
            parts.append(flatten_text(v))
    else:
        parts.append(str(values))
    return "\n".join(p for p in parts if p)


def detect_pii(*texts: Any) -> bool:
    """Return True if any of ``texts`` (strings or nested structures)
    contains a PII shape."""
    detector = PIIDetector()
    return any(detector.detect(flatten_text(t)).flagged for t in texts if t)


# ─── Prompt-injection detection ──────────────────────────────────────────

_INJECTION_PATTERNS: List[tuple] = [
    (re.compile(r"ignore\s+(?:previous|prior|above|all|earlier)\s+(?:instructions|prompts|context)", re.IGNORECASE), "ignore_instructions"),
    (re.compile(r"disregard\s+(?:previous|prior|above|all|earlier)\s+(?:instructions|prompts|context)", re.IGNORECASE), "disregard_instructions"),
    (re.compile(r"forget\s+(?:everything|all|previous|prior)", re.IGNORECASE), "forget_context"),
    (re.compile(r"you\s+are\s+now\b", re.IGNORECASE), "role_reassignment"),
    (re.compile(r"(?:act|pretend|behave)\s+as\s+(?:if\s+you\s+are|though\s+you\s+are|a|an)\b", re.IGNORECASE), "role_reassignment"),
    (re.compile(r"reveal\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)", re.IGNORECASE), "extract_system_prompt"),
    (re.compile(r"<\s*/?(?:system|assistant|user)\s*>", re.IGNORECASE), "delimiter_break"),
    (re.compile(r"(?:new\s+instructions|override\s+(?:all|previous)|system\s*:\s)", re.IGNORECASE), "delimiter_break"),
]


class PromptInjectionScreen:
    """Heuristic detector for embedded adversarial instructions."""

    def scan(self, text: str) -> ScreeningResult:
        if not text:
            return ScreeningResult(flagged=False)
        hits: List[ScreenHit] = []
        for pat, kind in _INJECTION_PATTERNS:
            for m in pat.finditer(text):
                hits.append(
                    ScreenHit(
                        kind=kind,
                        pattern=pat.pattern,
                        snippet=text[max(0, m.start() - 10):m.end() + 10],
                    )
                )
        return ScreeningResult(flagged=bool(hits), hits=hits)


def screen_injection(text: str) -> ScreeningResult:
    return PromptInjectionScreen().scan(text)


def screen_text(text: str) -> ScreeningResult:
    """Run both PII and prompt-injection screening on a single text blob."""
    result = screen_injection(text)
    pii = PIIDetector().detect(text)
    if pii.flagged:
        result.hits.extend(pii.hits)
        result = ScreeningResult(flagged=True, hits=result.hits)
    return result


def record_screening_threat(
    identity: str,
    text: str,
    *,
    detector: Optional[ThreatDetector] = None,
    source: str = "content_screening",
) -> List[ScreenHit]:
    """Screen ``text`` and record any prompt-injection hits as ThreatEvents.

    PII hits are logged as warnings (they are handled by the governance
    layer via ``contains_pii``), while injection hits raise a
    ``PROMPT_INJECTION`` threat event so operators can see cross-user
    poisoning attempts.
    """
    result = screen_text(text)
    if not result.flagged:
        return []
    det = detector or get_threat_detector()
    for hit in result.hits:
        if hit.kind == "pii":
            logger.warning(
                "PII shape detected in %s (snippet=%r)", source, hit.snippet
            )
        else:
            det.record_event(
                ThreatType.PROMPT_INJECTION,
                ThreatLevel.HIGH,
                identity,
                f"prompt-injection pattern '{hit.kind}' detected in {source}",
                {"pattern": hit.kind, "snippet": hit.snippet[:120]},
            )
    return result.hits
