"""Module 5.1 — Answer Generation benchmark (CLI).

Runs the :class:`AnswerGeneratorService` over a small golden dataset of
regulatory questions, measures latency, output length, evidence
coverage, and writes a JSON report to ``benchmarks/reports/``.

The benchmark uses the in-process :class:`MockLLMProvider` so it can
run without external API keys; real provider benchmarks can be
enabled with ``--provider openai|gemini|litellm`` (requires the
relevant SDK and env vars).

Usage
-----
    python -m benchmarks.benchmark_answer_generation \\
        --output benchmarks/reports/answer_gen_report.json

    python -m benchmarks.benchmark_answer_generation \\
        --provider openai --model gpt-4o-mini
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
    AnswerGenerationRequest,
    AnswerTone,
    LLMProviderName,
    RetrievedChunk,
)
from app.services.answer_generation import build_default_service

logger = logging.getLogger(__name__)


# ─── Golden dataset ─────────────────────────────────────────────────────────


@dataclass
class GoldenQuestion:
    """One benchmark question with its expected evidence."""

    query: str
    expected_chunk_ids: List[str]
    chunks: List[RetrievedChunk]
    description: str = ""


def _chunk(cid: str, doc: str, content: str, source: str, page: int, section: str,
           title: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        content=content,
        score=score,
        source=SourceEnum(source),
        page_number=page,
        section=section,
        document_title=title,
    )


GOLDEN: List[GoldenQuestion] = [
    GoldenQuestion(
        query="What are the KYC obligations for banks under RBI regulations?",
        expected_chunk_ids=["rbi-kyc-1", "rbi-kyc-2"],
        description="KYC + RBI",
        chunks=[
            _chunk("rbi-kyc-1", "doc-1",
                   "Banks shall undertake customer due diligence for all accounts "
                   "including walk-in customers. The KYC process must verify the "
                   "identity of the customer, beneficial owner, and persons on "
                   "whose behalf the account is operated.",
                   "RBI", 12, "KYC Process", "RBI Master Direction 2016"),
            _chunk("rbi-kyc-2", "doc-1",
                   "Customer identification procedure includes obtaining "
                   "officially valid documents, permanent account number (PAN) "
                   "for all transactions above fifty thousand rupees, and "
                   "periodic updation of KYC records.",
                   "RBI", 14, "Customer Identification", "RBI Master Direction 2016"),
        ],
    ),
    GoldenQuestion(
        query="What are SEBI disclosure norms for mutual fund portfolio holdings?",
        expected_chunk_ids=["sebi-disc-1", "sebi-disc-2"],
        description="SEBI + Disclosure",
        chunks=[
            _chunk("sebi-disc-1", "doc-2",
                   "Mutual funds shall disclose scheme-wise portfolio holdings on "
                   "a monthly basis within seven days of the close of the month.",
                   "SEBI", 4, "Portfolio Disclosure", "SEBI Circular 2020"),
            _chunk("sebi-disc-2", "doc-2",
                   "Portfolio disclosure shall include ISIN, company name, "
                   "quantity, and percentage of NAV. Sector-wise classification "
                   "is mandatory for equity-oriented schemes.",
                   "SEBI", 6, "Portfolio Disclosure", "SEBI Circular 2020"),
        ],
    ),
    GoldenQuestion(
        query="What are the AML reporting requirements for suspicious transactions?",
        expected_chunk_ids=["rbi-aml-1"],
        description="AML + Suspicious transactions",
        chunks=[
            _chunk("rbi-aml-1", "doc-3",
                   "Principal officers shall report suspicious transactions to the "
                   "Director, Financial Intelligence Unit-India (FIU-IND) within "
                   "seven working days of arriving at the conclusion that a "
                   "transaction is suspicious.",
                   "RBI", 22, "AML Reporting", "PMLA 2002"),
        ],
    ),
]


# ─── Result containers ──────────────────────────────────────────────────────


@dataclass
class QuestionResult:
    query: str
    description: str
    expected_chunk_ids: List[str]
    evidence_chunk_ids: List[str]
    evidence_coverage: float
    has_executive_summary: bool
    has_detailed_explanation: bool
    key_reference_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    sources: List[str]
    error: Optional[str] = None


@dataclass
class BenchmarkReport:
    benchmark: str
    provider: str
    model: str
    num_questions: int
    num_errors: int
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    mean_total_tokens: float
    mean_evidence_coverage: float
    executive_summary_present_rate: float
    detailed_explanation_present_rate: float
    results: List[QuestionResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


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


async def _run_one(svc, question: GoldenQuestion) -> QuestionResult:
    request = AnswerGenerationRequest(
        query=question.query,
        chunks=question.chunks,
        tone=AnswerTone.REGULATORY,
        stream=False,
    )
    t0 = time.perf_counter()
    try:
        response = await svc.generate(request)
    except Exception as exc:
        return QuestionResult(
            query=question.query,
            description=question.description,
            expected_chunk_ids=question.expected_chunk_ids,
            evidence_chunk_ids=[],
            evidence_coverage=0.0,
            has_executive_summary=False,
            has_detailed_explanation=False,
            key_reference_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            sources=[],
            error=str(exc),
        )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    evidence_ids = [e.chunk_id for e in response.answer.supporting_evidence]
    expected = set(question.expected_chunk_ids)
    hits = sum(1 for cid in evidence_ids if cid in expected)
    coverage = (hits / len(expected)) if expected else 0.0

    return QuestionResult(
        query=question.query,
        description=question.description,
        expected_chunk_ids=question.expected_chunk_ids,
        evidence_chunk_ids=evidence_ids,
        evidence_coverage=coverage,
        has_executive_summary=bool(response.answer.executive_summary.strip()),
        has_detailed_explanation=bool(
            response.answer.detailed_explanation.strip()
        ),
        key_reference_count=len(response.answer.key_regulatory_references),
        prompt_tokens=response.metadata.prompt_tokens,
        completion_tokens=response.metadata.completion_tokens,
        total_tokens=response.metadata.total_tokens,
        latency_ms=latency_ms,
        sources=response.metadata.sources,
    )


async def run_benchmark(
    *,
    provider: LLMProviderName = LLMProviderName.MOCK,
    model: str = "mock-default",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> BenchmarkReport:
    """Execute the benchmark and return an aggregate report."""
    svc = build_default_service(
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
    )
    results: List[QuestionResult] = []
    for q in GOLDEN:
        logger.info("benchmarking: %s", q.description)
        results.append(await _run_one(svc, q))

    latencies = [r.latency_ms for r in results if r.error is None]
    tokens = [r.total_tokens for r in results if r.error is None]
    coverages = [r.evidence_coverage for r in results if r.error is None]
    summary_rate = (
        sum(1 for r in results if r.has_executive_summary) / len(results)
        if results
        else 0.0
    )
    detail_rate = (
        sum(1 for r in results if r.has_detailed_explanation) / len(results)
        if results
        else 0.0
    )

    return BenchmarkReport(
        benchmark="answer_generation_v1",
        provider=provider.value,
        model=model,
        num_questions=len(results),
        num_errors=sum(1 for r in results if r.error),
        mean_latency_ms=statistics.fmean(latencies) if latencies else 0.0,
        median_latency_ms=statistics.median(latencies) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 95.0),
        mean_total_tokens=statistics.fmean(tokens) if tokens else 0.0,
        mean_evidence_coverage=statistics.fmean(coverages) if coverages else 0.0,
        executive_summary_present_rate=summary_rate,
        detailed_explanation_present_rate=detail_rate,
        results=results,
    )


# ─── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RegIntel-AI Answer Generation benchmark"
    )
    p.add_argument(
        "--provider",
        default="mock",
        choices=[n.value for n in LLMProviderName],
        help="LLM provider (default: mock)",
    )
    p.add_argument("--model", default="mock-default", help="Model identifier")
    p.add_argument("--api-key", default=None, help="API key (or use env)")
    p.add_argument("--api-base", default=None, help="Optional custom base URL")
    p.add_argument(
        "--output",
        default="benchmarks/reports/answer_gen_report.json",
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
    report = await run_benchmark(
        provider=LLMProviderName(args.provider),
        model=args.model,
        api_key=args.api_key,
        api_base=args.api_base,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2))

    print(f"\n=== Answer Generation Benchmark — {report.benchmark} ===")
    print(f"Provider / model : {report.provider} / {report.model}")
    print(f"Questions        : {report.num_questions}  (errors: {report.num_errors})")
    print(f"Mean latency     : {report.mean_latency_ms:.2f} ms")
    print(f"Median latency   : {report.median_latency_ms:.2f} ms")
    print(f"P95 latency      : {report.p95_latency_ms:.2f} ms")
    print(f"Mean tokens      : {report.mean_total_tokens:.1f}")
    print(f"Evidence coverage: {report.mean_evidence_coverage * 100:.1f}%")
    print(f"Summary present  : {report.executive_summary_present_rate * 100:.1f}%")
    print(f"Detail present   : {report.detailed_explanation_present_rate * 100:.1f}%")
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
