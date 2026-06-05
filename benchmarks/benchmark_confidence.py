"""Module 5.3 — Confidence Scoring benchmark (CLI).

Runs the deterministic :class:`ConfidenceService` over a golden dataset
of regulatory Q&A pairs, measures confidence + level + per-factor
scores, and writes a JSON report to ``benchmarks/reports/``.

The benchmark also exercises the in-process
:class:`ConfidenceMetrics` collector so the report includes the
aggregate level distribution and per-factor statistics.

Usage
-----
    python -m benchmarks.benchmark_confidence \\
        --output benchmarks/reports/confidence_report.json

    python -m benchmarks.benchmark_confidence --reset-metrics
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

from app.api.dependencies import reset_confidence_service
from app.schemas.confidence import (
    ConfidenceFactorName,
    ConfidenceFlag,
    ConfidenceLevel,
    ConfidenceRequest,
)
from app.services.confidence import build_default_confidence_service

logger = logging.getLogger(__name__)


# ─── Golden dataset ─────────────────────────────────────────────────────────


@dataclass
class GoldenCase:
    description: str
    query: str
    answer: Dict[str, Any]
    chunks: List[Dict[str, Any]]
    retrieval_scores: Optional[List[float]] = None
    reranker_scores: Optional[List[float]] = None
    citation_coverage: Optional[float] = None
    expected_level: Optional[ConfidenceLevel] = None


def _chunk(cid: str, doc: str, content: str, source: str, score: float,
           page: int = 1, section: str = "KYC") -> Dict[str, Any]:
    return {
        "chunk_id": cid, "document_id": doc, "content": content,
        "score": score, "source": source, "page_number": page, "section": section,
    }


def _answer(executive: str, detailed: str = "Supporting details.",
            evidence: int = 3) -> Dict[str, Any]:
    return {
        "executive_summary": executive,
        "detailed_explanation": detailed,
        "supporting_evidence": [{"chunk_id": f"c-{i}"} for i in range(evidence)],
        "key_regulatory_references": ["RBI Act 1934"],
    }


GOLDEN: List[GoldenCase] = [
    GoldenCase(
        description="High-quality KYC answer (single source, all factors strong)",
        query="What are KYC obligations for banks?",
        answer=_answer(
            executive="Banks must follow RBI KYC norms under Master Direction MD/2016/1.",
            detailed="Customer identification procedure requires PAN for transactions.",
        ),
        chunks=[_chunk(f"c-{i}", f"d-{i}", f"KYC rule {i}", "RBI", 0.92, 12 + i)
                for i in range(5)],
        retrieval_scores=[0.92, 0.90, 0.88, 0.86, 0.84],
        reranker_scores=[0.95, 0.93, 0.91, 0.89, 0.87],
        citation_coverage=1.0,
        expected_level=ConfidenceLevel.HIGH,
    ),
    GoldenCase(
        description="Mixed-source SEBI/RBI answer (medium confidence)",
        query="What are SEBI portfolio disclosure norms?",
        answer=_answer(
            executive="Mutual funds must disclose portfolio holdings monthly.",
            detailed="Monthly disclosure includes ISIN, quantity, and NAV percentage.",
        ),
        chunks=[
            _chunk("c-1", "d-1", "SEBI mandates monthly disclosure.", "SEBI", 0.85),
            _chunk("c-2", "d-2", "RBI KYC norms apply.", "RBI", 0.78),
            _chunk("c-3", "d-1", "Disclosure must include ISIN.", "SEBI", 0.82),
        ],
        retrieval_scores=[0.85, 0.78, 0.82],
        reranker_scores=[0.88, 0.80, 0.85],
        citation_coverage=0.9,
        expected_level=ConfidenceLevel.MEDIUM,
    ),
    GoldenCase(
        description="Low-quality: no rerank, low citation coverage, low chunk count",
        query="What is the AML reporting periodicity?",
        answer=_answer(
            executive="Banks report suspicious transactions to FIU-IND.",
            detailed="Reporting is mandatory within seven days.",
            evidence=1,
        ),
        chunks=[_chunk("c-1", "d-1", "AML rule", "RBI", 0.55)],
        retrieval_scores=[0.55],
        reranker_scores=None,
        citation_coverage=0.4,
        expected_level=ConfidenceLevel.LOW,
    ),
    GoldenCase(
        description="Edge case: empty chunks",
        query="Irrelevant question",
        answer=_answer("No information available.", "No details.", evidence=0),
        chunks=[],
        retrieval_scores=[],
        reranker_scores=None,
        citation_coverage=None,
        expected_level=ConfidenceLevel.LOW,
    ),
    GoldenCase(
        description="Single-source high-quality (5 RBI chunks, all strong)",
        query="KYC documentation requirements",
        answer=_answer(
            executive="Banks require officially valid documents for KYC.",
            detailed="PAN is mandatory for financial transactions.",
        ),
        chunks=[_chunk(f"c-{i}", "d-1", f"Rule {i}", "RBI", 0.95, 5 + i)
                for i in range(5)],
        retrieval_scores=[0.95] * 5,
        reranker_scores=[0.97] * 5,
        citation_coverage=1.0,
        expected_level=ConfidenceLevel.HIGH,
    ),
]


# ─── Result containers ──────────────────────────────────────────────────────


@dataclass
class CaseResult:
    description: str
    query: str
    confidence: float
    level: str
    expected_level: Optional[str]
    level_match: Optional[bool]
    factor_scores: Dict[str, float]
    factor_contributions: Dict[str, float]
    flag_count: int
    flags: List[str]
    latency_ms: float


@dataclass
class BenchmarkReport:
    benchmark: str
    num_cases: int
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    mean_confidence: float
    level_distribution: Dict[str, int]
    expected_match_rate: float
    factor_score_means: Dict[str, float]
    flag_frequency: Dict[str, int]
    results: List[CaseResult] = field(default_factory=list)
    metrics_snapshot: Optional[Dict[str, Any]] = None

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


def _run_case(svc, case: GoldenCase) -> CaseResult:
    request = ConfidenceRequest(
        query=case.query,
        answer=case.answer,
        chunks=case.chunks,
        retrieval_scores=case.retrieval_scores,
        reranker_scores=case.reranker_scores,
        citation_coverage=case.citation_coverage,
    )
    t0 = time.perf_counter()
    response = svc.score(request)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    factor_scores = {
        f.name.value: f.score for f in response.breakdown.factors
    }
    factor_contributions = {
        f.name.value: f.contribution for f in response.breakdown.factors
    }
    level_match = (
        case.expected_level is None
        or response.level == case.expected_level
    )
    return CaseResult(
        description=case.description,
        query=case.query,
        confidence=response.confidence,
        level=response.level.value,
        expected_level=case.expected_level.value if case.expected_level else None,
        level_match=level_match,
        factor_scores=factor_scores,
        factor_contributions=factor_contributions,
        flag_count=len(response.flags),
        flags=[f.value for f in response.flags],
        latency_ms=latency_ms,
    )


def run_benchmark(*, reset_metrics: bool = False) -> BenchmarkReport:
    if reset_metrics:
        reset_confidence_service()
    svc = build_default_confidence_service()
    if reset_metrics:
        svc.metrics.reset()

    results = [_run_case(svc, case) for case in GOLDEN]

    latencies = [r.latency_ms for r in results]
    confidences = [r.confidence for r in results]
    level_dist: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for r in results:
        level_dist[r.level] = level_dist.get(r.level, 0) + 1

    matches = [r.level_match for r in results if r.level_match is not None]
    expected_match_rate = (
        sum(1 for m in matches if m) / len(matches) if matches else 0.0
    )

    factor_means: Dict[str, float] = {}
    for factor_name in ConfidenceFactorName:
        scores = [r.factor_scores.get(factor_name.value, 0.0) for r in results]
        factor_means[factor_name.value] = statistics.fmean(scores) if scores else 0.0

    flag_freq: Dict[str, int] = {}
    for r in results:
        for f in r.flags:
            flag_freq[f] = flag_freq.get(f, 0) + 1

    return BenchmarkReport(
        benchmark="confidence_v1",
        num_cases=len(results),
        mean_latency_ms=statistics.fmean(latencies) if latencies else 0.0,
        median_latency_ms=statistics.median(latencies) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 95.0),
        mean_confidence=statistics.fmean(confidences) if confidences else 0.0,
        level_distribution=level_dist,
        expected_match_rate=expected_match_rate,
        factor_score_means=factor_means,
        flag_frequency=flag_freq,
        results=results,
        metrics_snapshot=svc.metrics.snapshot(),
    )


# ─── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RegIntel-AI Confidence Scoring benchmark"
    )
    p.add_argument(
        "--output",
        default="benchmarks/reports/confidence_report.json",
        help="Output JSON path (relative to repo root)",
    )
    p.add_argument(
        "--reset-metrics",
        action="store_true",
        help="Reset the in-process metrics collector before running.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    report = run_benchmark(reset_metrics=args.reset_metrics)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2))

    print(f"\n=== Confidence Scoring Benchmark — {report.benchmark} ===")
    print(f"Cases              : {report.num_cases}")
    print(f"Mean latency       : {report.mean_latency_ms:.2f} ms")
    print(f"Median latency     : {report.median_latency_ms:.2f} ms")
    print(f"P95 latency        : {report.p95_latency_ms:.2f} ms")
    print(f"Mean confidence    : {report.mean_confidence:.3f}")
    print(f"Level distribution : {report.level_distribution}")
    print(f"Expected match rate: {report.expected_match_rate * 100:.1f}%")
    print("\nFactor score means:")
    for name, mean in report.factor_score_means.items():
        print(f"  {name:25s} {mean:.3f}")
    if report.flag_frequency:
        print("\nFlag frequency:")
        for flag, count in sorted(report.flag_frequency.items(), key=lambda x: -x[1]):
            print(f"  {flag:30s} {count}")
    print(f"\nReport written to: {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
