"""Module 6.5 — Multi-Document Reasoning service.

Public surface
--------------
* :class:`DocumentComparator` — pairwise chunk/document diffs.
* :class:`TimelineAnalyzer` — chronological event extraction.
* :class:`ChangeDetector` — regulatory change detection.
* :class:`ContradictionDetector` — finding conflicting claims.
* :class:`ReasoningCoordinator` — orchestrates the above based on the
  requested :class:`ReasoningMode`.
* :class:`MultiDocumentReasoner` — top-level DI service.

All algorithms are deterministic and offline (no LLM calls).  They
are designed to be replaced by an LLM-backed implementation in
production; the public contract is the same.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.citation.mapper import token_overlap
from app.schemas.reasoning import (
    ChangeReport,
    ChangeType,
    Contradiction,
    ContradictionReport,
    ContradictionSeverity,
    CrossDocumentSummary,
    DiffItem,
    DiffType,
    DocumentDiff,
    ReasoningMode,
    ReasoningRequest,
    ReasoningResponse,
    RegulatoryChange,
    Timeline,
    TimelineEvent,
)

logger = logging.getLogger(__name__)


# ─── Helpers ───────────────────────────────────────────────────────────────


_DATE_RE = re.compile(
    r"\b("
    r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{4})"
    r"|"
    r"(?P<month_name>"
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
    r")\s+(?P<day2>\d{1,2}),?\s+(?P<year2>\d{4})"
    r"|"
    r"(?P<year_only>\d{4})"
    r")\b",
    re.IGNORECASE,
)

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# Polarising words used to detect contradictions.
_NEGATIVE_HINTS = {
    "not",
    "no",
    "prohibited",
    "shall not",
    "must not",
    "cannot",
    "may not",
    "forbidden",
}
_AFFIRMATIVE_HINTS = {"shall", "must", "required", "may", "permitted", "allowed"}


def _extract_date(text: str) -> Tuple[Optional[date], Optional[int]]:
    """Return (date, year) from the first parseable date in ``text``."""
    m = _DATE_RE.search(text)
    if not m:
        return None, None
    gd = m.groupdict()
    if gd.get("year_only"):
        year = int(gd["year_only"])
        return None, year
    if gd.get("year2"):
        month = _MONTH_MAP[gd["month_name"].lower()]
        day = int(gd["day2"])
        year = int(gd["year2"])
        try:
            return date(year, month, day), year
        except ValueError:
            return None, year
    if gd.get("year"):
        try:
            return date(int(gd["year"]), int(gd["month"]), int(gd["day"])), int(
                gd["year"]
            )
        except ValueError:
            return None, int(gd["year"])
    return None, None


def _normalise_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a chunk dict into a stable shape."""
    return {
        "chunk_id": str(chunk.get("chunk_id", "")),
        "document_id": str(chunk.get("document_id", "")),
        "document_title": str(chunk.get("document_title", chunk.get("title", ""))),
        "content": str(chunk.get("content", "")),
        "section": str(chunk.get("section", "")),
        "score": float(chunk.get("score", 0.0) or 0.0),
        "page_number": chunk.get("page_number"),
    }


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ─── Document comparator ───────────────────────────────────────────────────


class DocumentComparator:
    """Compute pairwise diffs between two chunk sets."""

    def __init__(self, *, similarity_threshold: float = 0.7) -> None:
        self.similarity_threshold = similarity_threshold

    def compare(
        self,
        chunks_a: List[Dict[str, Any]],
        chunks_b: List[Dict[str, Any]],
        *,
        document_a_id: str = "A",
        document_b_id: str = "B",
        document_a_title: str = "",
        document_b_title: str = "",
    ) -> DocumentDiff:
        a = [_normalise_chunk(c) for c in chunks_a]
        b = [_normalise_chunk(c) for c in chunks_b]
        differences: List[DiffItem] = []
        # Greedy matching: for each chunk in A, find best match in B.
        matched_b: set = set()
        total_similarity = 0.0
        comparisons = 0
        for ca in a:
            best_idx = -1
            best_score = 0.0
            for j, cb in enumerate(b):
                if j in matched_b:
                    continue
                sim = token_overlap(ca["content"], cb["content"])
                if sim > best_score:
                    best_score = sim
                    best_idx = j
            comparisons += 1
            total_similarity += best_score
            if best_idx < 0:
                # No remaining chunks in B.
                differences.append(
                    DiffItem(
                        diff_type=DiffType.REMOVED,
                        section=ca["section"],
                        before=ca["content"],
                        after=None,
                        similarity=0.0,
                        severity=ContradictionSeverity.MEDIUM,
                        citation_a=ca["chunk_id"],
                        citation_b=None,
                        explanation="Content present in document A only.",
                    )
                )
            elif best_score >= self.similarity_threshold:
                # Unchanged / very similar.
                differences.append(
                    DiffItem(
                        diff_type=DiffType.UNCHANGED,
                        section=ca["section"],
                        before=ca["content"],
                        after=b[best_idx]["content"],
                        similarity=best_score,
                        severity=ContradictionSeverity.LOW,
                        citation_a=ca["chunk_id"],
                        citation_b=b[best_idx]["chunk_id"],
                        explanation="Content is materially the same.",
                    )
                )
                matched_b.add(best_idx)
            else:
                # Changed or contradicts.
                dtype = (
                    DiffType.CONTRADICTS
                    if _looks_contradictory(ca["content"], b[best_idx]["content"])
                    else DiffType.CHANGED
                )
                differences.append(
                    DiffItem(
                        diff_type=dtype,
                        section=ca["section"],
                        before=ca["content"],
                        after=b[best_idx]["content"],
                        similarity=best_score,
                        severity=(
                            ContradictionSeverity.HIGH
                            if dtype == DiffType.CONTRADICTS
                            else ContradictionSeverity.MEDIUM
                        ),
                        citation_a=ca["chunk_id"],
                        citation_b=b[best_idx]["chunk_id"],
                        explanation=(
                            "The two chunks disagree."
                            if dtype == DiffType.CONTRADICTS
                            else "The two chunks differ in detail."
                        ),
                    )
                )
                matched_b.add(best_idx)
        # Anything in B that wasn't matched → ADDED.
        for j, cb in enumerate(b):
            if j in matched_b:
                continue
            differences.append(
                DiffItem(
                    diff_type=DiffType.ADDED,
                    section=cb["section"],
                    before=None,
                    after=cb["content"],
                    similarity=0.0,
                    severity=ContradictionSeverity.MEDIUM,
                    citation_a=None,
                    citation_b=cb["chunk_id"],
                    explanation="Content present in document B only.",
                )
            )
        similarity_score = (total_similarity / comparisons) if comparisons else 0.0
        summary = self._summarise(differences)
        return DocumentDiff(
            document_a_id=document_a_id,
            document_a_title=document_a_title,
            document_b_id=document_b_id,
            document_b_title=document_b_title,
            similarity_score=similarity_score,
            differences=differences,
            summary=summary,
        )

    def _summarise(self, diffs: List[DiffItem]) -> str:
        counts = Counter(d.diff_type for d in diffs)
        return (
            f"Compared {len(diffs)} chunk-pair(s): "
            f"{counts.get(DiffType.ADDED, 0)} added, "
            f"{counts.get(DiffType.REMOVED, 0)} removed, "
            f"{counts.get(DiffType.CHANGED, 0)} changed, "
            f"{counts.get(DiffType.CONTRADICTS, 0)} contradict, "
            f"{counts.get(DiffType.UNCHANGED, 0)} unchanged."
        )


def _looks_contradictory(a: str, b: str) -> bool:
    """Heuristic: do these two statements disagree?"""
    a_low = a.lower()
    b_low = b.lower()
    a_neg = any(h in a_low for h in _NEGATIVE_HINTS)
    b_neg = any(h in b_low for h in _NEGATIVE_HINTS)
    a_aff = any(h in a_low for h in _AFFIRMATIVE_HINTS)
    b_aff = any(h in b_low for h in _AFFIRMATIVE_HINTS)
    # Negation flip on similar surface text → contradiction.
    if a_neg != b_neg and a_aff and b_aff:
        # Quick overlap check.
        if token_overlap(a, b) > 0.3:
            return True
    # Antonym-style: share most tokens but have one of a small set of
    # opposite markers.
    opposite = {
        "shall": "shall not",
        "must": "must not",
        "required": "not required",
        "permitted": "prohibited",
        "allowed": "forbidden",
        "may": "may not",
    }
    for k, v in opposite.items():
        if (k in a_low and v in b_low) or (v in a_low and k in b_low):
            if token_overlap(a, b) > 0.3:
                return True
    return False


# ─── Timeline analyzer ────────────────────────────────────────────────────


class TimelineAnalyzer:
    """Extract :class:`TimelineEvent` from chunk contents."""

    def __init__(self) -> None:
        # Heuristic category hints.
        self._categories = [
            ("circular", [r"\bcircular\b", r"\bcircular no"]),
            ("master_direction", [r"\bmaster direction\b", r"\bmaster circular\b"]),
            ("amendment", [r"\bamend", r"\bamendment"]),
            ("repeal", [r"\brepeal", r"\brescind"]),
            ("notification", [r"\bnotification\b"]),
        ]

    def analyze(self, chunks: List[Dict[str, Any]]) -> Timeline:
        events: List[TimelineEvent] = []
        for chunk in chunks:
            c = _normalise_chunk(chunk)
            content = c["content"]
            if not content:
                continue
            event_date, event_year = _extract_date(content)
            if not (event_date or event_year):
                continue
            # Choose category.
            category = self._categorise(content)
            # Use the first sentence as the description.
            first = _split_sentences(content)[0] if content else content
            events.append(
                TimelineEvent(
                    event_date=event_date,
                    event_year=event_year,
                    document_id=c["document_id"] or None,
                    document_title=c["document_title"],
                    section=c["section"],
                    description=first,
                    category=category,
                    citation=c["chunk_id"] or None,
                )
            )
        # Sort by year/date.
        events.sort(key=lambda e: (e.event_year or 0, e.event_date or date(1900, 1, 1)))
        # Compute span.
        span_start = events[0].event_date if events else None
        span_end = events[-1].event_date if events else None
        # Group by year (period).
        grouped: Dict[str, List[TimelineEvent]] = defaultdict(list)
        for e in events:
            key = str(e.event_year) if e.event_year is not None else "unknown"
            grouped[key].append(e)
        summary = (
            f"{len(events)} event(s) extracted spanning "
            f"{span_start.isoformat() if span_start else 'n/a'} → "
            f"{span_end.isoformat() if span_end else 'n/a'}."
        )
        return Timeline(
            events=events,
            span_start=span_start,
            span_end=span_end,
            grouped_by_period=dict(grouped),
            summary=summary,
        )

    def _categorise(self, text: str) -> str:
        low = text.lower()
        for name, patterns in self._categories:
            for p in patterns:
                if re.search(p, low):
                    return name
        return "general"


# ─── Change detector ──────────────────────────────────────────────────────


class ChangeDetector:
    """Detect regulatory changes between two chunk sets."""

    def __init__(self, *, similarity_threshold: float = 0.6) -> None:
        self.similarity_threshold = similarity_threshold
        self.comparator = DocumentComparator(similarity_threshold=similarity_threshold)

    def detect(
        self, chunks_a: List[Dict[str, Any]], chunks_b: List[Dict[str, Any]]
    ) -> ChangeReport:
        diff = self.comparator.compare(chunks_a, chunks_b)
        changes: List[RegulatoryChange] = []
        for d in diff.differences:
            if d.diff_type == DiffType.ADDED:
                ct = ChangeType.NEW
            elif d.diff_type == DiffType.REMOVED:
                ct = ChangeType.REPEALED
            elif d.diff_type == DiffType.CONTRADICTS:
                ct = ChangeType.AMENDED
            elif d.diff_type == DiffType.CHANGED:
                ct = ChangeType.AMENDED
            elif d.diff_type == DiffType.UNCHANGED:
                continue
            else:
                continue
            effective_date = None
            if d.after:
                ed, _ = _extract_date(d.after)
                effective_date = ed
            elif d.before:
                ed, _ = _extract_date(d.before)
                effective_date = ed
            changes.append(
                RegulatoryChange(
                    change_type=ct,
                    document_a_id=d.citation_a,
                    document_b_id=d.citation_b,
                    section=d.section,
                    before=d.before,
                    after=d.after,
                    effective_date=effective_date,
                    significance=d.severity,
                    citation_a=d.citation_a,
                    citation_b=d.citation_b,
                    explanation=d.explanation,
                )
            )
        by_type: Dict[ChangeType, int] = Counter(c.change_type for c in changes)
        summary = (
            f"{len(changes)} change(s) detected "
            f"({by_type.get(ChangeType.NEW, 0)} new, "
            f"{by_type.get(ChangeType.AMENDED, 0)} amended, "
            f"{by_type.get(ChangeType.REPEALED, 0)} repealed)."
        )
        return ChangeReport(changes=changes, by_type=dict(by_type), summary=summary)


# ─── Contradiction detector ───────────────────────────────────────────────


class ContradictionDetector:
    """Find pairs of chunks that disagree on the same topic."""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.3,
        contradiction_overlap: float = 0.3,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.contradiction_overlap = contradiction_overlap

    def detect(self, chunks: List[Dict[str, Any]]) -> ContradictionReport:
        norm = [_normalise_chunk(c) for c in chunks]
        contradictions: List[Contradiction] = []
        for i in range(len(norm)):
            for j in range(i + 1, len(norm)):
                a, b = norm[i], norm[j]
                if a["document_id"] == b["document_id"]:
                    continue  # within-document; skip
                # Quick overlap gate.
                if (
                    token_overlap(a["content"], b["content"])
                    < self.similarity_threshold
                ):
                    continue
                if not _looks_contradictory(a["content"], b["content"]):
                    continue
                severity = self._severity(a["content"], b["content"])
                explanation = self._explain(a["content"], b["content"])
                contradictions.append(
                    Contradiction(
                        claim_a=a["content"],
                        source_a=a["document_title"] or a["document_id"],
                        citation_a=a["chunk_id"] or None,
                        claim_b=b["content"],
                        source_b=b["document_title"] or b["document_id"],
                        citation_b=b["chunk_id"] or None,
                        severity=severity,
                        explanation=explanation,
                    )
                )
        summary = f"{len(contradictions)} contradiction(s) found across the chunks."
        return ContradictionReport(contradictions=contradictions, summary=summary)

    def _severity(self, a: str, b: str) -> ContradictionSeverity:
        # Higher overlap + explicit negation → high severity.
        ov = token_overlap(a, b)
        if ov > 0.7:
            return ContradictionSeverity.HIGH
        if ov > 0.4:
            return ContradictionSeverity.MEDIUM
        return ContradictionSeverity.LOW

    def _explain(self, a: str, b: str) -> str:
        return (
            "The two chunks share the same topic but use opposite "
            "modal/negation markers (e.g. shall vs shall not)."
        )


# ─── Cross-document summary ───────────────────────────────────────────────


class CrossDocumentSummariser:
    """Produce a unified summary across multiple documents."""

    def summarise(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
    ) -> CrossDocumentSummary:
        norm = [_normalise_chunk(c) for c in chunks]
        # Group by document_id.
        by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in norm:
            if c["document_id"]:
                by_doc[c["document_id"]].append(c)
        doc_ids = list(by_doc.keys())
        doc_titles = sorted({c["document_title"] for c in norm if c["document_title"]})
        # Pick the top N sentences across all chunks (extractively) as key points.
        all_sentences: List[str] = []
        for c in norm:
            all_sentences.extend(_split_sentences(c["content"]))
        # Score sentences by query-term overlap.
        scored: List[Tuple[float, str]] = []
        for s in all_sentences:
            scored.append((token_overlap(query, s), s))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Take top-5 unique key points.
        seen: set = set()
        key_points: List[str] = []
        for _, s in scored:
            sig = s.lower()[:80]
            if sig in seen:
                continue
            seen.add(sig)
            key_points.append(s)
            if len(key_points) >= 5:
                break
        summary_text = " ".join(key_points)
        citations = [c["chunk_id"] for c in norm if c["chunk_id"]]
        return CrossDocumentSummary(
            topic=query,
            document_ids=doc_ids,
            document_titles=doc_titles,
            key_points=key_points,
            summary_text=summary_text,
            citations=citations,
        )


# ─── Reasoning coordinator ────────────────────────────────────────────────


class ReasoningCoordinator:
    """Orchestrates comparison / timeline / change / contradiction
    detection based on the requested :class:`ReasoningMode`."""

    def __init__(
        self,
        *,
        comparator: Optional[DocumentComparator] = None,
        timeline: Optional[TimelineAnalyzer] = None,
        changes: Optional[ChangeDetector] = None,
        contradictions: Optional[ContradictionDetector] = None,
        summariser: Optional[CrossDocumentSummariser] = None,
    ) -> None:
        self.comparator = comparator or DocumentComparator()
        self.timeline = timeline or TimelineAnalyzer()
        self.changes = changes or ChangeDetector()
        self.contradictions = contradictions or ContradictionDetector()
        self.summariser = summariser or CrossDocumentSummariser()

    def run(self, request: ReasoningRequest) -> ReasoningResponse:
        chunks = [_normalise_chunk(c) for c in request.chunks]
        all_citations = [c["chunk_id"] for c in chunks if c["chunk_id"]]
        diff: Optional[DocumentDiff] = None
        timeline: Optional[Timeline] = None
        changes: Optional[ChangeReport] = None
        contradictions_report: Optional[ContradictionReport] = None
        cross_summary: Optional[CrossDocumentSummary] = None
        modes = self._modes_for(request.mode)
        if "compare" in modes and self._has_multiple_docs(chunks):
            # Compare the first two distinct documents.
            docs = self._split_by_document(chunks)
            ids = sorted(docs.keys())
            if len(ids) >= 2:
                diff = self.comparator.compare(
                    docs[ids[0]],
                    docs[ids[1]],
                    document_a_id=ids[0],
                    document_b_id=ids[1],
                    document_a_title=docs[ids[0]][0].get("document_title", ""),
                    document_b_title=docs[ids[1]][0].get("document_title", ""),
                )
        if "timeline" in modes:
            timeline = self.timeline.analyze(chunks)
        if "changes" in modes and self._has_multiple_docs(chunks):
            docs = self._split_by_document(chunks)
            ids = sorted(docs.keys())
            if len(ids) >= 2:
                changes = self.changes.detect(docs[ids[0]], docs[ids[1]])
        if "contradictions" in modes:
            contradictions_report = self.contradictions.detect(chunks)
        if "cross_summary" in modes or "full" in modes:
            cross_summary = self.summariser.summarise(request.query, chunks)
        return ReasoningResponse(
            query=request.query,
            mode=request.mode,
            diff=diff,
            timeline=timeline,
            changes=changes,
            contradictions=contradictions_report,
            cross_summary=cross_summary,
            citations=all_citations,
            metadata=dict(request.metadata),
        )

    # ── helpers ───────────────────────────────────────────────────────────

    def _modes_for(self, mode: ReasoningMode) -> set:
        if mode == ReasoningMode.FULL:
            return {"compare", "timeline", "changes", "contradictions", "cross_summary"}
        return {mode.value}

    def _has_multiple_docs(self, chunks: List[Dict[str, Any]]) -> bool:
        docs = {c["document_id"] for c in chunks if c["document_id"]}
        return len(docs) >= 2

    def _split_by_document(
        self, chunks: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in chunks:
            if c["document_id"]:
                out[c["document_id"]].append(c)
            else:
                out.setdefault("__unknown__", []).append(c)
        return out


# ─── Top-level MultiDocumentReasoner ──────────────────────────────────────


class MultiDocumentReasoner:
    """DI-friendly top-level service."""

    def __init__(
        self,
        *,
        coordinator: Optional[ReasoningCoordinator] = None,
        comparator: Optional[DocumentComparator] = None,
        timeline: Optional[TimelineAnalyzer] = None,
        changes: Optional[ChangeDetector] = None,
        contradictions: Optional[ContradictionDetector] = None,
        summariser: Optional[CrossDocumentSummariser] = None,
    ) -> None:
        self.comparator = comparator or DocumentComparator()
        # Use underscored names to avoid shadowing the public methods
        # (timeline, changes, contradictions, cross_summary).
        self._timeline = timeline or TimelineAnalyzer()
        self._changes = changes or ChangeDetector()
        self._contradictions = contradictions or ContradictionDetector()
        self.summariser = summariser or CrossDocumentSummariser()
        self.coordinator = coordinator or ReasoningCoordinator(
            comparator=self.comparator,
            timeline=self._timeline,
            changes=self._changes,
            contradictions=self._contradictions,
            summariser=self.summariser,
        )

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        return self.coordinator.run(request)

    # Convenience methods.
    def compare(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ReasoningResponse:
        return self.reason(
            ReasoningRequest(
                query=query, chunks=chunks, mode=ReasoningMode.COMPARE, **kwargs
            )
        )

    def timeline(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ReasoningResponse:
        return self.reason(
            ReasoningRequest(
                query=query, chunks=chunks, mode=ReasoningMode.TIMELINE, **kwargs
            )
        )

    def changes(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ReasoningResponse:
        return self.reason(
            ReasoningRequest(
                query=query, chunks=chunks, mode=ReasoningMode.CHANGES, **kwargs
            )
        )

    def contradictions(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ReasoningResponse:
        return self.reason(
            ReasoningRequest(
                query=query, chunks=chunks, mode=ReasoningMode.CONTRADICTIONS, **kwargs
            )
        )

    def cross_summary(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ReasoningResponse:
        return self.reason(
            ReasoningRequest(
                query=query, chunks=chunks, mode=ReasoningMode.CROSS_SUMMARY, **kwargs
            )
        )


def build_default_multi_document_reasoner() -> MultiDocumentReasoner:
    return MultiDocumentReasoner()


__all__ = [
    "ChangeDetector",
    "ContradictionDetector",
    "CrossDocumentSummariser",
    "DocumentComparator",
    "MultiDocumentReasoner",
    "ReasoningCoordinator",
    "TimelineAnalyzer",
    "build_default_multi_document_reasoner",
]
