"""Module 7.3 — Regulatory Change Detection Engine.

Public surface
--------------
* :class:`VersionComparator` — diffs two plain-text versions using
  sequence-level diffing.
* :class:`ClauseComparator` — section-aware clause-level diffing.
* :class:`DocumentDiffEngine` — orchestrator: pulls text/sections,
  runs comparators, returns a :class:`DocumentDiff`.
* :class:`ChangeClassifier` — assigns severity + category to each
  clause change using deterministic keyword / structure heuristics.
* :class:`ChangeDetectionService` — top-level DI-friendly facade.

The engine is intentionally pluggable and offline-friendly. No LLM
calls are required: the classifiers use deterministic keyword +
structure heuristics. This keeps the platform testable and removes
external latency from the hot path of change detection.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel

from app.core.config import settings
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionRequest,
    ChangeDetectionResult,
    ChangeDetectionStats,
    ChangeFilter,
    ChangeSeverity,
    ChangeType,
    ClauseChange,
    DocumentDiff,
    PaginatedDiffs,
    SectionRef,
)
from app.services.observability import (
    get_change_detection_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Tokenisation helpers ──────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenise(text: str) -> List[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _token_overlap(a: List[str], b: List[str]) -> float:
    """Jaccard-like overlap between two token lists."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _split_sections(text: str) -> List[Tuple[str, str]]:
    """Split text into (section_header, body) pairs.

    Recognises common regulatory patterns::

        1. Title
           ...
        1.1 Subtitle
           ...
        (a) clause
        Section 12. ...

    Returns a list of (header, body) tuples.  The header is the
    shortest form that uniquely identifies the section.
    """
    if not text:
        return []
    out: List[Tuple[str, str]] = []
    section_re = re.compile(
        r"^\s*(?:"
        r"(?:\d+\.)+\d*\s+[A-Z][^\n]+"        # 1. 1.1  1.1.1  title
        r"|Section\s+\d+[^\n]*"               # Section 12
        r"|Article\s+\d+[^\n]*"               # Article 12
        r"|Regulation\s+\d+[^\n]*"            # Regulation 12
        r"|Chapter\s+\d+[^\n]*"               # Chapter 12
        r"|(?:[A-Z][A-Z\s\-]{3,})$"           # ALL CAPS LINE
        r")",
        re.MULTILINE,
    )
    matches = list(section_re.finditer(text))
    if not matches:
        return [("", text.strip())]
    if matches[0].start() > 0:
        prelude = text[: matches[0].start()].strip()
        if prelude:
            out.append(("", prelude))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        header = m.group(0).strip()
        body = text[start + len(m.group(0)): end].strip()
        out.append((header, body))
    return out


def _split_clauses(section_body: str) -> List[str]:
    """Split a section body into individual clauses.

    Heuristics: split on numbered/lettered prefixes and on sentence
    boundaries.  Always returns at least one element.
    """
    if not section_body.strip():
        return []
    clause_re = re.compile(
        r"(?:^|\n)\s*(?:"
        r"\([a-z]\)"            # (a)
        r"|\(\d+\)"              # (1)
        r"|\(\d+\.\d+\)"         # (1.1)
        r"|\(\d+\.\d+\.\d+\)"    # (1.1.1)
        r")\s+",
    )
    matches = list(clause_re.finditer(section_body))
    if matches:
        clauses: List[str] = []
        if matches[0].start() > 0:
            prelude = section_body[: matches[0].start()].strip()
            if prelude:
                clauses.append(prelude)
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(section_body)
            clause = section_body[start:end].strip()
            if clause:
                clauses.append(clause)
        return clauses
    # Fallback: split on sentence boundaries.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", section_body.strip())
    return [s.strip() for s in sentences if s.strip()]


# ─── Change classifier ────────────────────────────────────────────────


_HIGH_SEVERITY_KEYWORDS = {
    "shall not",
    "must not",
    "prohibited",
    "forbidden",
    "penalty",
    "penalties",
    "sanction",
    "fine",
    "imprisonment",
    "revoke",
    "revocation",
    "suspend",
    "cancellation",
    "license",
    "licence",
    "registration",
    "compliance deadline",
    "effective immediately",
    "cease",
    "mandatory",
    "compulsory",
}

_MEDIUM_SEVERITY_KEYWORDS = {
    "amend",
    "amended",
    "amendment",
    "modify",
    "modified",
    "modification",
    "revise",
    "revised",
    "update",
    "updated",
    "replace",
    "replaced",
    "substitute",
    "new requirement",
    "new obligation",
    "reporting",
    "disclose",
    "disclosure",
    "submit",
    "notification",
    "notify",
    "deadline",
    "timeline",
    "limit",
    "threshold",
}

_LOW_SEVERITY_KEYWORDS = {
    "clarify",
    "clarification",
    "format",
    "formatting",
    "spelling",
    "wording",
    "typo",
    "minor change",
    "editorial",
    "reorder",
    "renumber",
}


_CATEGORY_KEYWORDS: Dict[ChangeCategory, Tuple[float, set]] = {
    ChangeCategory.PENALTY_CHANGE: (
        1.0,
        {"penalty", "penalties", "fine", "fines", "sanction", "sanctions", "punishable"},
    ),
    ChangeCategory.COMPLIANCE_DEADLINE: (
        1.0,
        {"deadline", "effective", "compliance", "by", "within", "no later than"},
    ),
    ChangeCategory.REPORTING_REQUIREMENT: (
        1.0,
        {"report", "reports", "reporting", "submit", "disclose", "disclosure", "notify", "notification"},
    ),
    ChangeCategory.CAPITAL_REQUIREMENT: (
        1.0,
        {"capital", "tier", "car", "leverage", "liquidity", "lcr", "nsfr", "crr", "slr"},
    ),
    ChangeCategory.SCOPE_CHANGE: (
        1.0,
        {"scope", "applicability", "applies to", "covered", "excluded", "exemption"},
    ),
    ChangeCategory.NEW_GUIDANCE: (
        0.9,
        {"guidance", "advisory", "recommended", "best practice", "expect"},
    ),
    ChangeCategory.CLARIFICATION: (
        0.7,
        {"clarify", "clarification", "explain", "interpret", "interpretation", "meaning"},
    ),
    ChangeCategory.REGULATORY_AMENDMENT: (
        0.8,
        {"amend", "amended", "amendment", "substitute", "replace", "replaced"},
    ),
    ChangeCategory.POLICY_UPDATE: (
        0.5,
        {"policy", "framework", "guideline", "directive", "circular"},
    ),
}


def _keyword_hits(text: str, keywords: Iterable[str]) -> int:
    if not text:
        return 0
    blob = text.lower()
    return sum(1 for kw in keywords if kw in blob)


def _classify_severity(text: str, change_type: ChangeType) -> ChangeSeverity:
    """Severity heuristic.

    * ADDED / REMOVED with high-severity keywords → HIGH
    * ADDED / REMOVED with medium keywords → MEDIUM
    * MODIFIED with high diff ratio + high keywords → HIGH
    * MODIFIED with low diff ratio + low keywords → LOW
    * Otherwise MEDIUM
    """
    high = _keyword_hits(text, _HIGH_SEVERITY_KEYWORDS)
    medium = _keyword_hits(text, _MEDIUM_SEVERITY_KEYWORDS)
    low = _keyword_hits(text, _LOW_SEVERITY_KEYWORDS)
    if change_type in (ChangeType.ADDED, ChangeType.REMOVED):
        if high:
            return ChangeSeverity.CRITICAL if high >= 2 else ChangeSeverity.HIGH
        if medium:
            return ChangeSeverity.MEDIUM
        return ChangeSeverity.LOW
    # MODIFIED
    if high >= 2:
        return ChangeSeverity.CRITICAL
    if high:
        return ChangeSeverity.HIGH
    if medium:
        return ChangeSeverity.MEDIUM
    if low and not medium:
        return ChangeSeverity.LOW
    return ChangeSeverity.LOW


def _classify_category(text: str) -> ChangeCategory:
    """Category heuristic: best matching keyword set wins."""
    if not text:
        return ChangeCategory.OTHER
    best_cat = ChangeCategory.OTHER
    best_score = 0.0
    for cat, (weight, keywords) in _CATEGORY_KEYWORDS.items():
        hits = _keyword_hits(text, keywords)
        if hits == 0:
            continue
        score = weight * hits
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def _rationale(change_type: ChangeType, severity: ChangeSeverity, old: Optional[str], new: Optional[str]) -> str:
    if change_type == ChangeType.ADDED:
        return f"New content added. Severity: {severity.value}."
    if change_type == ChangeType.REMOVED:
        return f"Existing content removed. Severity: {severity.value}."
    if change_type == ChangeType.MODIFIED:
        return f"Existing content modified. Severity: {severity.value}."
    return "Content unchanged."


# ─── Comparators ───────────────────────────────────────────────────────


@dataclass
class _ClausePair:
    old_text: Optional[str]
    new_text: Optional[str]
    location: SectionRef
    change_type: ChangeType
    similarity: float


class VersionComparator:
    """Plain-text version comparator using :class:`difflib.SequenceMatcher`."""

    def compare_texts(
        self,
        old_text: str,
        new_text: str,
        *,
        granularity: str = "sentence",
    ) -> List[_ClausePair]:
        """Compare two plain texts at sentence or paragraph granularity.

        Returns a list of clause pairs with a change_type and similarity
        score. Used as a fallback when section breakdown is unavailable.
        """
        if granularity == "sentence":
            old_units = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", old_text or "")
            new_units = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", new_text or "")
        else:
            old_units = (old_text or "").split("\n\n")
            new_units = (new_text or "").split("\n\n")
        old_units = [u.strip() for u in old_units if u.strip()]
        new_units = [u.strip() for u in new_units if u.strip()]
        return self._align_units(old_units, new_units)

    def _align_units(
        self, old_units: List[str], new_units: List[str]
    ) -> List[_ClausePair]:
        if not old_units and not new_units:
            return []
        sm = SequenceMatcher(a=old_units, b=new_units, autojunk=False)
        pairs: List[_ClausePair] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    pairs.append(
                        _ClausePair(
                            old_text=old_units[i1 + k],
                            new_text=new_units[j1 + k],
                            location=SectionRef(clause=f"c{i1 + k}"),
                            change_type=ChangeType.UNCHANGED,
                            similarity=1.0,
                        )
                    )
            elif tag == "delete":
                for k in range(i1, i2):
                    pairs.append(
                        _ClausePair(
                            old_text=old_units[k],
                            new_text=None,
                            location=SectionRef(clause=f"c{k}"),
                            change_type=ChangeType.REMOVED,
                            similarity=0.0,
                        )
                    )
            elif tag == "insert":
                for k in range(j1, j2):
                    pairs.append(
                        _ClausePair(
                            old_text=None,
                            new_text=new_units[k],
                            location=SectionRef(clause=f"c{k}"),
                            change_type=ChangeType.ADDED,
                            similarity=0.0,
                        )
                    )
            elif tag == "replace":
                # Pair up similar items, mark extras as removed/added.
                a_block = old_units[i1:i2]
                b_block = new_units[j1:j2]
                sim_matrix = [
                    [
                        SequenceMatcher(a=a, b=b, autojunk=False).ratio()
                        for b in b_block
                    ]
                    for a in a_block
                ]
                used_b = set()
                for ai, a in enumerate(a_block):
                    best_bj = -1
                    best_score = 0.0
                    for bj, b in enumerate(b_block):
                        if bj in used_b:
                            continue
                        if sim_matrix[ai][bj] > best_score:
                            best_score = sim_matrix[ai][bj]
                            best_bj = bj
                    if best_bj >= 0 and best_score >= 0.5:
                        used_b.add(best_bj)
                        pairs.append(
                            _ClausePair(
                                old_text=a,
                                new_text=b_block[best_bj],
                                location=SectionRef(clause=f"c{ai}"),
                                change_type=(
                                    ChangeType.MODIFIED
                                    if best_score < 1.0
                                    else ChangeType.UNCHANGED
                                ),
                                similarity=best_score,
                            )
                        )
                    else:
                        pairs.append(
                            _ClausePair(
                                old_text=a,
                                new_text=None,
                                location=SectionRef(clause=f"c{ai}"),
                                change_type=ChangeType.REMOVED,
                                similarity=0.0,
                            )
                        )
                for bj, b in enumerate(b_block):
                    if bj in used_b:
                        continue
                    pairs.append(
                        _ClausePair(
                            old_text=None,
                            new_text=b,
                            location=SectionRef(clause=f"c{bj}"),
                            change_type=ChangeType.ADDED,
                            similarity=0.0,
                        )
                    )
        return pairs


class ClauseComparator:
    """Section-aware clause-level comparator.

    Splits both old/new into sections, then matches sections by header
    and within matched sections diffs clauses.
    """

    def __init__(self, version_comparator: Optional[VersionComparator] = None) -> None:
        self.version_comparator = version_comparator or VersionComparator()

    def compare_sections(
        self,
        old_sections: List[Dict[str, Any]],
        new_sections: List[Dict[str, Any]],
    ) -> List[_ClausePair]:
        old_by_header = {s.get("section", ""): s for s in old_sections}
        new_by_header = {s.get("section", ""): s for s in new_sections}
        pairs: List[_ClausePair] = []
        # Process old headers in order, then any new-only headers.
        seen_new: set = set()
        for old_header, old_sec in old_by_header.items():
            new_sec = new_by_header.get(old_header)
            if new_sec is None:
                # Section removed
                for clause in _split_clauses(old_sec.get("text", "")):
                    pairs.append(
                        _ClausePair(
                            old_text=clause,
                            new_text=None,
                            location=SectionRef(
                                section=old_sec.get("section"),
                                subsection=old_sec.get("subsection"),
                            ),
                            change_type=ChangeType.REMOVED,
                            similarity=0.0,
                        )
                    )
                continue
            seen_new.add(old_header)
            old_clauses = _split_clauses(old_sec.get("text", ""))
            new_clauses = _split_clauses(new_sec.get("text", ""))
            inner_pairs = self.version_comparator._align_units(
                old_clauses, new_clauses
            )
            for p in inner_pairs:
                pairs.append(
                    _ClausePair(
                        old_text=p.old_text,
                        new_text=p.new_text,
                        location=SectionRef(
                            section=old_sec.get("section"),
                            subsection=old_sec.get("subsection"),
                        ),
                        change_type=p.change_type,
                        similarity=p.similarity,
                    )
                )
        for new_header, new_sec in new_by_header.items():
            if new_header in seen_new:
                continue
            for clause in _split_clauses(new_sec.get("text", "")):
                pairs.append(
                    _ClausePair(
                        old_text=None,
                        new_text=clause,
                        location=SectionRef(
                            section=new_sec.get("section"),
                            subsection=new_sec.get("subsection"),
                        ),
                        change_type=ChangeType.ADDED,
                        similarity=0.0,
                    )
                )
        return pairs


# ─── Change classifier (high-level) ────────────────────────────────────


class ChangeClassifier:
    """Assigns severity + category + rationale to a clause pair."""

    def classify(self, pair: _ClausePair) -> ClauseChange:
        if pair.change_type == ChangeType.UNCHANGED:
            return ClauseChange(
                change_type=ChangeType.UNCHANGED,
                location=pair.location,
                old_text=pair.old_text,
                new_text=pair.new_text,
                severity=ChangeSeverity.LOW,
                category=ChangeCategory.OTHER,
                rationale="No change.",
            )
        text_blob = ((pair.new_text or "") + " " + (pair.old_text or "")).strip()
        severity = _classify_severity(text_blob, pair.change_type)
        category = _classify_category(text_blob)
        # Severity floor for high-impact categories
        if category in {
            ChangeCategory.PENALTY_CHANGE,
            ChangeCategory.COMPLIANCE_DEADLINE,
        } and pair.change_type != ChangeType.UNCHANGED:
            if severity == ChangeSeverity.LOW:
                severity = ChangeSeverity.MEDIUM
            elif severity == ChangeSeverity.MEDIUM:
                severity = ChangeSeverity.HIGH
        rationale = _rationale(pair.change_type, severity, pair.old_text, pair.new_text)
        return ClauseChange(
            change_type=pair.change_type,
            location=pair.location,
            old_text=pair.old_text,
            new_text=pair.new_text,
            severity=severity,
            category=category,
            rationale=rationale,
            metadata={"similarity": pair.similarity},
        )


# ─── Document diff engine ─────────────────────────────────────────────


def _overall_severity(changes: List[ClauseChange]) -> ChangeSeverity:
    if not changes:
        return ChangeSeverity.LOW
    order = {
        ChangeSeverity.LOW: 0,
        ChangeSeverity.MEDIUM: 1,
        ChangeSeverity.HIGH: 2,
        ChangeSeverity.CRITICAL: 3,
    }
    worst = ChangeSeverity.LOW
    for c in changes:
        if c.change_type == ChangeType.UNCHANGED:
            continue
        if order[c.severity] > order[worst]:
            worst = c.severity
    return worst


def _overall_category(changes: List[ClauseChange]) -> ChangeCategory:
    counts: Dict[ChangeCategory, int] = {}
    for c in changes:
        if c.change_type == ChangeType.UNCHANGED:
            continue
        counts[c.category] = counts.get(c.category, 0) + 1
    if not counts:
        return ChangeCategory.OTHER
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _generate_summary(diff: DocumentDiff) -> str:
    if not any(c.change_type != ChangeType.UNCHANGED for c in diff.changes):
        return "No substantive changes detected."
    parts = []
    if diff.added_count:
        parts.append(f"{diff.added_count} addition(s)")
    if diff.removed_count:
        parts.append(f"{diff.removed_count} removal(s)")
    if diff.modified_count:
        parts.append(f"{diff.modified_count} modification(s)")
    return (
        f"Detected {', '.join(parts)} with overall severity "
        f"{diff.overall_severity.value} and category "
        f"{diff.overall_category.value}."
    )


class DocumentDiffEngine:
    """Top-level orchestrator: takes a :class:`ChangeDetectionRequest`
    and returns a fully populated :class:`DocumentDiff`.
    """

    def __init__(
        self,
        version_comparator: Optional[VersionComparator] = None,
        clause_comparator: Optional[ClauseComparator] = None,
        classifier: Optional[ChangeClassifier] = None,
    ) -> None:
        self.version_comparator = version_comparator or VersionComparator()
        self.clause_comparator = clause_comparator or ClauseComparator(
            self.version_comparator
        )
        self.classifier = classifier or ChangeClassifier()

    def detect(self, request: ChangeDetectionRequest) -> DocumentDiff:
        start = time.perf_counter()
        with track_request(
            endpoint="/api/v1/changes/detect", strategy="change_detection"
        ):
            # Choose comparator based on input shape.
            if request.old_sections is not None and request.new_sections is not None:
                pairs = self.clause_comparator.compare_sections(
                    request.old_sections, request.new_sections
                )
            else:
                pairs = self.version_comparator.compare_texts(
                    request.old_text or "", request.new_text or ""
                )
            # Classify each pair.
            changes: List[ClauseChange] = [
                self.classifier.classify(p) for p in pairs
            ]
            added = sum(1 for c in changes if c.change_type == ChangeType.ADDED)
            removed = sum(1 for c in changes if c.change_type == ChangeType.REMOVED)
            modified = sum(1 for c in changes if c.change_type == ChangeType.MODIFIED)
            unchanged = sum(
                1 for c in changes if c.change_type == ChangeType.UNCHANGED
            )
            overall_sev = _overall_severity(changes)
            overall_cat = _overall_category(changes)
            diff = DocumentDiff(
                document_id=request.document_id,
                old_version=request.old_version,
                new_version=request.new_version,
                source=request.source,
                old_publication_date=request.old_publication_date,
                new_publication_date=request.new_publication_date,
                changes=changes,
                added_count=added,
                removed_count=removed,
                modified_count=modified,
                unchanged_count=unchanged,
                overall_severity=overall_sev,
                overall_category=overall_cat,
                duration_ms=(time.perf_counter() - start) * 1000.0,
                metadata=request.metadata,
            )
            diff.summary = _generate_summary(diff)
        # Update observability.
        metrics = get_change_detection_metrics()
        metrics.record_diff(diff)
        return diff


# ─── Persistence ───────────────────────────────────────────────────────


class ChangeStore(ABC):
    def add_diff(self, diff: DocumentDiff) -> None: ...
    def list_diffs(self) -> List[DocumentDiff]: ...
    def get_diff(self, diff_id: str) -> Optional[DocumentDiff]: ...
    def reset(self) -> None: ...


class InMemoryChangeStore(ChangeStore):
    """Thread-safe in-memory change store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._diffs: Dict[str, DocumentDiff] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if self._persist_path and self._persist_path.exists():
            self._load()

    def _load(self) -> None:
        try:
            for line in self._persist_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                d = DocumentDiff.model_validate(row)
                self._diffs[d.diff_id] = d
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load change store: %s", exc)

    def _persist(self, diff: DocumentDiff) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(diff.model_dump(mode="json")) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist diff: %s", exc)

    def add_diff(self, diff: DocumentDiff) -> None:
        with self._lock:
            self._diffs[diff.diff_id] = diff
        self._persist(diff)

    def list_diffs(self) -> List[DocumentDiff]:
        with self._lock:
            return list(self._diffs.values())

    def get_diff(self, diff_id: str) -> Optional[DocumentDiff]:
        with self._lock:
            return self._diffs.get(diff_id)

    def reset(self) -> None:
        with self._lock:
            self._diffs.clear()


class ChangeRepository:
    def __init__(self, store: ChangeStore) -> None:
        self.store = store

    def add(self, diff: DocumentDiff) -> DocumentDiff:
        self.store.add_diff(diff)
        return diff

    def get(self, diff_id: str) -> Optional[DocumentDiff]:
        return self.store.get_diff(diff_id)

    def search(self, flt: ChangeFilter) -> PaginatedDiffs:
        items = list(self.store.list_diffs())
        if flt.document_id is not None:
            items = [d for d in items if d.document_id == flt.document_id]
        if flt.source is not None:
            items = [d for d in items if d.source == flt.source]
        if flt.category is not None:
            items = [d for d in items if d.overall_category == flt.category]
        if flt.min_severity is not None:
            order = {
                ChangeSeverity.LOW: 0,
                ChangeSeverity.MEDIUM: 1,
                ChangeSeverity.HIGH: 2,
                ChangeSeverity.CRITICAL: 3,
            }
            threshold = order[flt.min_severity]
            items = [
                d for d in items if order[d.overall_severity] >= threshold
            ]
        if flt.after is not None:
            items = [d for d in items if d.computed_at >= flt.after]
        if flt.before is not None:
            items = [d for d in items if d.computed_at <= flt.before]
        items.sort(key=lambda d: d.computed_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedDiffs(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> ChangeDetectionStats:
        diffs = self.store.list_diffs()
        if not diffs:
            return ChangeDetectionStats()
        total_changes = 0
        added = 0
        removed = 0
        modified = 0
        by_sev: Dict[ChangeSeverity, int] = {}
        by_cat: Dict[ChangeCategory, int] = {}
        by_src: Dict[str, int] = {}
        total_duration = 0.0
        for d in diffs:
            total_changes += len(d.changes)
            added += d.added_count
            removed += d.removed_count
            modified += d.modified_count
            by_sev[d.overall_severity] = by_sev.get(d.overall_severity, 0) + 1
            by_cat[d.overall_category] = by_cat.get(d.overall_category, 0) + 1
            by_src[d.source or "unknown"] = by_src.get(d.source or "unknown", 0) + 1
            total_duration += d.duration_ms
        return ChangeDetectionStats(
            total_diffs=len(diffs),
            total_changes=total_changes,
            added=added,
            removed=removed,
            modified=modified,
            by_severity=by_sev,
            by_category=by_cat,
            by_source=by_src,
            average_duration_ms=total_duration / len(diffs) if diffs else 0.0,
        )


# ─── Top-level service ────────────────────────────────────────────────


class ChangeDetectionService:
    """DI-friendly top-level facade."""

    def __init__(
        self,
        *,
        engine: Optional[DocumentDiffEngine] = None,
        store: Optional[ChangeStore] = None,
        repository: Optional[ChangeRepository] = None,
    ) -> None:
        self.engine = engine or DocumentDiffEngine()
        self.store = store or InMemoryChangeStore(
            persist_path=Path(settings.STORAGE_ROOT) / "changes" / "diffs.jsonl"
        )
        self.repository = repository or ChangeRepository(self.store)

    def detect(self, request: ChangeDetectionRequest) -> ChangeDetectionResult:
        if not request.old_text and not request.new_text and not (
            request.old_sections and request.new_sections
        ):
            raise ValueError(
                "either (old_text, new_text) or (old_sections, new_sections) "
                "must be provided"
            )
        diff = self.engine.detect(request)
        self.repository.add(diff)
        affected_sections = sorted(
            {
                c.location.section
                for c in diff.changes
                if c.change_type != ChangeType.UNCHANGED and c.location.section
            }
        )
        return ChangeDetectionResult(
            diff=diff,
            affected_sections=affected_sections,
            has_changes=any(
                c.change_type != ChangeType.UNCHANGED for c in diff.changes
            ),
        )

    def get(self, diff_id: str) -> Optional[DocumentDiff]:
        return self.repository.get(diff_id)

    def search(self, flt: ChangeFilter) -> PaginatedDiffs:
        return self.repository.search(flt)

    def stats(self) -> ChangeDetectionStats:
        return self.repository.stats()


def build_default_change_detection_service() -> ChangeDetectionService:
    return ChangeDetectionService()


__all__ = [
    "ChangeClassifier",
    "ChangeDetectionService",
    "ChangeRepository",
    "ChangeStore",
    "ClauseComparator",
    "DocumentDiffEngine",
    "InMemoryChangeStore",
    "VersionComparator",
    "build_default_change_detection_service",
]
