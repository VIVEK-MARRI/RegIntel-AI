"""Module 5.2 — Citation Engine benchmark (CLI).

Runs the deterministic :class:`CitationService` over a golden dataset
of regulatory Q&A pairs (Module 5.1 answer + Module 4.8 chunks),
measures latency, coverage, reference-list size, and marker quality.
Writes a JSON report to ``benchmarks/reports/``.

Usage
-----
    python -m benchmarks.benchmark_citation \\
        --output benchmarks/reports/citation_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.document import SourceEnum
from app.schemas.answer_generation import (
    AnswerSection,
    EvidenceChunk,
    RetrievedChunk,
)
from app.schemas.citation import (
    CitationRequest,
    CitationStyle,
)
from app.services.citation import build_default_citation_service

logger = logging.getLogger(__name__)


# ─── Golden dataset ─────────────────────────────────────────────────────────


@dataclass
class GoldenCase:
    query: str
    answer: AnswerSection
    chunks: List[RetrievedChunk]
    expected_reference_documents: List[str]  # document_ids that should appear in refs
    description: str = ""


def _chunk(cid: str, doc: str, content: str, source: str, page: int,
           section: str, title: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, document_id=doc, content=content, score=score,
        source=SourceEnum(source), page_number=page, section=section,
        document_title=title,
    )


def _answer(executive: str, detailed: str,
            references: Optional[List[str]] = None) -> AnswerSection:
    return AnswerSection(
        executive_summary=executive,
        detailed_explanation=detailed,
        supporting_evidence=[],
        key_regulatory_references=references or [],
    )


GOLDEN: List[GoldenCase] = [
    GoldenCase(
        query="What are the KYC obligations for banks?",
        description="KYC + RBI Master Direction",
        answer=_answer(
            executive="Banks must follow RBI KYC norms under Master Direction MD/2016/1.",
            detailed=(
                "Customer identification procedure requires PAN for transactions "
                "above fifty thousand rupees. Banks shall verify identity of "
                "beneficial owners. Customer due diligence is mandatory for all "
                "account categories including walk-in customers."
            ),
            references=["RBI Act 1934", "PMLA 2002"],
        ),
        chunks=[
            _chunk("c-1", "d-1",
                   "Banks must follow RBI KYC norms under Master Direction MD/2016/1. "
                   "Customer identification procedure requires PAN for transactions "
                   "above fifty thousand rupees. Banks shall verify identity of "
                   "beneficial owners. Customer due diligence is mandatory for all "
                   "account categories including walk-in customers.",
                   "RBI", 12, "KYC", "RBI Master Direction MD/2016/1 on KYC"),
            _chunk("c-2", "d-2",
                   "Officially valid documents include passport, driving licence, "
                   "Aadhaar, and voter identity card. PAN is mandatory for all "
                   "financial transactions.",
                   "RBI", 14, "Customer Identification", "RBI Master Direction MD/2016/1 on KYC"),
        ],
        expected_reference_documents=["d-1", "d-2"],
    ),
    GoldenCase(
        query="What are SEBI disclosure norms for mutual fund portfolio holdings?",
        description="SEBI Disclosure",
        answer=_answer(
            executive="Mutual funds must disclose portfolio holdings monthly.",
            detailed=(
                "Mutual funds shall disclose scheme-wise portfolio holdings on a "
                "monthly basis within seven days of the close of the month. "
                "Portfolio disclosure shall include ISIN, company name, quantity, "
                "and percentage of NAV. Sector-wise classification is mandatory "
                "for equity-oriented schemes."
            ),
            references=["SEBI LODR"],
        ),
        chunks=[
            _chunk("c-1", "d-1",
                   "Mutual funds shall disclose scheme-wise portfolio holdings on "
                   "a monthly basis within seven days of the close of the month.",
                   "SEBI", 4, "Portfolio Disclosure", "SEBI Circular 12/2024"),
            _chunk("c-2", "d-1",
                   "Portfolio disclosure shall include ISIN, company name, "
                   "quantity, and percentage of NAV. Sector-wise classification "
                   "is mandatory for equity-oriented schemes.",
                   "SEBI", 6, "Portfolio Disclosure", "SEBI Circular 12/2024"),
        ],
        expected_reference_documents=["d-1"],
    ),
    GoldenCase(
        query="AML reporting of suspicious transactions",
        description="AML + Suspicious transactions",
        answer=_answer(
            executive="Banks must report suspicious transactions to FIU-IND within seven days.",
            detailed=(
                "Principal officers shall report suspicious transactions to the "
                "Director, Financial Intelligence Unit-India (FIU-IND) within "
                "seven working days of arriving at the conclusion that a "
                "transaction is suspicious."
            ),
            references=["PMLA 2002"],
        ),
        chunks=[
            _chunk("c-1", "d-1",
                   "Principal officers shall report suspicious transactions to the "
                   "Director, Financial Intelligence Unit-India (FIU-IND) within "
                   "seven working days of arriving at the conclusion that a "
                   "transaction is suspicious.",
                   "RBI", 22, "AML Reporting", "PMLA 2002"),
        ],
        expected_reference_documents=["d-1"],
    ),
    GoldenCase(
        query="What is the KYC updation periodicity?",
        description="KYC + periodicity (low overlap test)",
        answer=_answer(
            executive="KYC records must be updated periodically.",
            detailed=(
                "The periodicity for updation of KYC records depends on the risk "
                "category of the customer. High-risk customers require annual "
                "updation while low-risk customers may be updated every ten years."
            ),
        ),
        chunks=[
            _chunk("c-1", "d-1",
                   "Customer due diligence is mandatory for all account categories "
                   "including walk-in customers. The periodicity for KYC updation "
                   "varies based on customer risk profile.",
                   "RBI", 15, "KYC Updation", "RBI Master Direction MD/2016/1 on KYC"),
        ],
        expected_reference_documents=["d-1"],
    ),
]


# ─── Result containers ──────────────────────────────────────────────────────


@dataclass
class CaseResult:
    query: str
    description: str
    expected_documents: List[str]
    actual_documents: List[str]
    document_recall: float
    total_claims: int
    cited_claims: int
    coverage_ratio: float
    reference_count: int
    unique_marker_count: int
    latency_ms: float
    error: Optional[str] = None


@dataclass
class BenchmarkReport:
    benchmark: str
    num_cases: int
    num_errors: int
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    mean_coverage: float
    min_coverage: float
    mean_doc_recall: float
    mean_references: float
    full_coverage_rate: float
    results: List[CaseResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Benchmark runner ──────────────────────────────────────────────────────


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


async def _run_case(svc, case: GoldenCase) -> CaseResult:
    request = CitationRequest(
        query=case.query,
        answer=case.answer,
        chunks=case.chunks,
        style=CitationStyle.BRACKETED_SOURCE,
    )
    t0 = time.perf_counter()
    try:
        response = await asyncio.to_thread(svc.cite, request)  # type: ignore[arg-type]
    except Exception as exc:
        return CaseResult(
            query=case.query,
            description=case.description,
            expected_documents=case.expected_reference_documents,
            actual_documents=[],
            document_recall=0.0,
            total_claims=0,
            cited_claims=0,
            coverage_ratio=0.0,
            reference_count=0,
            unique_marker_count=0,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            error=str(exc),
        )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    actual_docs = [r.document_id for r in response.annotated_answer.references]
    expected = set(case.expected_reference_documents)
    hits = sum(1 for d in actual_docs if d in expected)
    doc_recall = (hits / len(expected)) if expected else 0.0

    # Unique inline markers in annotated text.
    markers: set[str] = set()
    for c in response.annotated_answer.executive_summary.citations:
        markers.add(c.marker.strip())
    for c in response.annotated_answer.detailed_explanation.citations:
        markers.add(c.marker.strip())

    return CaseResult(
        query=case.query,
        description=case.description,
        expected_documents=case.expected_reference_documents,
        actual_documents=actual_docs,
        document_recall=doc_recall,
        total_claims=response.coverage.total_claims,
        cited_claims=response.coverage.cited_claims,
        coverage_ratio=response.coverage.coverage_ratio,
        reference_count=len(response.annotated_answer.references),
        unique_marker_count=len(markers),
        latency_ms=latency_ms,
    )


async def run_benchmark() -> BenchmarkReport:
    svc = build_default_citation_service()
    results: List[CaseResult] = []
    for case in GOLDEN:
        logger.info("benchmarking: %s", case.description)
        results.append(await _run_case(svc, case))

    latencies = [r.latency_ms for r in results if r.error is None]
    coverages = [r.coverage_ratio for r in results if r.error is None]
    doc_recalls = [r.document_recall for r in results if r.error is None]
    ref_counts = [r.reference_count for r in results if r.error is None]

    return BenchmarkReport(
        benchmark="citation_v1",
        num_cases=len(results),
        num_errors=sum(1 for r in results if r.error),
        mean_latency_ms=statistics.fmean(latencies) if latencies else 0.0,
        median_latency_ms=statistics.median(latencies) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 95.0),
        mean_coverage=statistics.fmean(coverages) if coverages else 0.0,
        min_coverage=min(coverages) if coverages else 0.0,
        mean_doc_recall=statistics.fmean(doc_recalls) if doc_recalls else 0.0,
        mean_references=statistics.fmean(ref_counts) if ref_counts else 0.0,
        full_coverage_rate=(
            sum(1 for c in coverages if c >= 1.0) / len(coverages)
            if coverages
            else 0.0
        ),
        results=results,
    )


# ─── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RegIntel-AI Citation Engine benchmark"
    )
    p.add_argument(
        "--output",
        default="benchmarks/reports/citation_report.json",
        help="Output JSON path (relative to repo root)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    report = await run_benchmark()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2))

    print(f"\n=== Citation Engine Benchmark — {report.benchmark} ===")
    print(f"Cases             : {report.num_cases}  (errors: {report.num_errors})")
    print(f"Mean latency      : {report.mean_latency_ms:.2f} ms")
    print(f"Median latency    : {report.median_latency_ms:.2f} ms")
    print(f"P95 latency       : {report.p95_latency_ms:.2f} ms")
    print(f"Mean coverage     : {report.mean_coverage * 100:.1f}%")
    print(f"Min coverage      : {report.min_coverage * 100:.1f}%")
    print(f"Full-coverage rate: {report.full_coverage_rate * 100:.1f}%")
    print(f"Mean doc recall   : {report.mean_doc_recall * 100:.1f}%")
    print(f"Mean references   : {report.mean_references:.1f}")
    print(f"\nReport written to: {out_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_main_async(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
