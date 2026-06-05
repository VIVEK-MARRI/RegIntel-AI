"""Module 5.4 — Hallucination Guard benchmark.

Runs a deterministic offline evaluation of the HallucinationGuardService
over a golden dataset of known-good and known-bad answers, and writes
a JSON report to ``benchmarks/reports/hallucination_report.json``.

The benchmark exercises the lexical path so it runs without any LLM
SDK or API key.  The ``--method`` flag lets you switch to
``llm`` / ``hybrid`` if a provider is wired up.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.hallucination import VerificationMethod
from app.services.hallucination import (
    HallucinationGuardService,
    MockFaithfulnessProvider,
    build_default_hallucination_guard,
)

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent / "reports"


# ─── Golden dataset ─────────────────────────────────────────────────────────


GOLDEN_DATASET: List[Dict[str, Any]] = [
    {
        "name": "kyc_fully_supported",
        "description": "KYC answer fully supported by the chunks.",
        "query": "What does the KYC process require?",
        "answer": AnswerSection(
            executive_summary="Banks perform KYC at onboarding.",
            detailed_explanation=(
                "Banks must perform customer identification at onboarding. "
                "KYC includes identity verification, address proof, and risk "
                "profiling."
            ),
            supporting_evidence=[],
            key_regulatory_references=[],
        ),
        "chunks": [
            RetrievedChunk(
                chunk_id="chk-1",
                document_id="doc-1",
                document_title="RBI Master Direction on KYC",
                source="RBI",
                page_number=8,
                section="KYC Norms",
                content=(
                    "Banks must perform customer identification at onboarding. "
                    "The KYC process includes identity verification, address "
                    "proof, and risk profiling."
                ),
                score=0.92,
            ),
        ],
        "expected_hallucination": False,
        "expected_min_faithfulness": 0.9,
    },
    {
        "name": "fabricated_filing_obligation",
        "description": "Answer fabricates a monthly tax return obligation.",
        "query": "What does KYC require?",
        "answer": AnswerSection(
            executive_summary="Banks perform KYC.",
            detailed_explanation=(
                "KYC includes identity verification and address proof. "
                "Banks must also file monthly tax returns for every account "
                "holder."
            ),
            supporting_evidence=[],
            key_regulatory_references=[],
        ),
        "chunks": [
            RetrievedChunk(
                chunk_id="chk-1",
                document_id="doc-1",
                document_title="RBI Master Direction on KYC",
                source="RBI",
                page_number=8,
                section="KYC Norms",
                content=(
                    "Banks must perform customer identification at onboarding. "
                    "KYC includes identity verification, address proof, and "
                    "risk profiling."
                ),
                score=0.92,
            ),
        ],
        "expected_hallucination": True,
        "expected_max_faithfulness": 0.8,
    },
    {
        "name": "no_chunks_means_no_support",
        "description": "Empty chunks force hallucination flag.",
        "query": "What is KYC?",
        "answer": AnswerSection(
            executive_summary="Banks perform KYC.",
            detailed_explanation="KYC is required at onboarding.",
            supporting_evidence=[],
            key_regulatory_references=[],
        ),
        "chunks": [],
        "expected_hallucination": True,
        "expected_max_faithfulness": 0.1,
    },
    {
        "name": "sebi_disclosure_supported",
        "description": "SEBI disclosure obligation supported by SEBI circular chunk.",
        "query": "What are SEBI disclosure obligations for listed entities?",
        "answer": AnswerSection(
            executive_summary="Listed entities must disclose material information.",
            detailed_explanation=(
                "Material information must be disclosed promptly to the stock "
                "exchanges. Insider trading regulations prohibit trading on "
                "unpublished price sensitive information."
            ),
            supporting_evidence=[],
            key_regulatory_references=[],
        ),
        "chunks": [
            RetrievedChunk(
                chunk_id="chk-sebi-1",
                document_id="doc-sebi-1",
                document_title="SEBI LODR Regulations",
                source="SEBI",
                page_number=42,
                section="Disclosure Obligations",
                content=(
                    "Listed entities must disclose material information to "
                    "stock exchanges promptly. Insider trading regulations "
                    "prohibit trading on unpublished price sensitive "
                    "information."
                ),
                score=0.88,
            ),
        ],
        "expected_hallucination": False,
        "expected_min_faithfulness": 0.9,
    },
    {
        "name": "fabricated_quantum",
        "description": "Answer invents specific penalty quantum not in evidence.",
        "query": "What is the penalty for non-disclosure under SEBI LODR?",
        "answer": AnswerSection(
            executive_summary="The penalty is Rs 25 crore per violation.",
            detailed_explanation=(
                "Non-disclosure of material information attracts a penalty of "
                "Rs 25 crore per violation. The penalty is doubled for "
                "repeat offenders within 12 months."
            ),
            supporting_evidence=[],
            key_regulatory_references=[],
        ),
        "chunks": [
            RetrievedChunk(
                chunk_id="chk-sebi-2",
                document_id="doc-sebi-2",
                document_title="SEBI LODR Regulations",
                source="SEBI",
                page_number=15,
                section="Penalties",
                content=(
                    "Non-disclosure may attract penalties as prescribed by the "
                    "Board from time to time. The quantum depends on the "
                    "nature and gravity of the violation."
                ),
                score=0.81,
            ),
        ],
        "expected_hallucination": True,
        "expected_max_faithfulness": 0.6,
    },
]


# ─── Benchmark runner ───────────────────────────────────────────────────────


async def run_benchmark(
    *,
    method: VerificationMethod = VerificationMethod.LEXICAL,
    use_mock_provider: bool = False,
) -> Dict[str, Any]:
    """Run the benchmark and return a JSON-serialisable report."""
    provider = MockFaithfulnessProvider() if use_mock_provider else None
    guard = build_default_hallucination_guard(provider=provider)

    per_case: List[Dict[str, Any]] = []
    latencies: List[float] = []
    faithfulness_scores: List[float] = []
    hallucination_flags: List[bool] = []

    for case in GOLDEN_DATASET:
        t0 = time.perf_counter()
        resp = await guard.verify_answer(
            query=case["query"],
            answer=case["answer"],
            chunks=case["chunks"],
            method=method,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)
        faithfulness_scores.append(resp.report.faithfulness_score)
        hallucination_flags.append(resp.report.hallucination_detected)

        # Verify expectations.
        expected_hallu = case.get("expected_hallucination")
        min_faith = case.get("expected_min_faithfulness")
        max_faith = case.get("expected_max_faithfulness")
        expectations_met: List[str] = []
        if expected_hallu is not None:
            if resp.report.hallucination_detected == expected_hallu:
                expectations_met.append("hallucination")
            else:
                expectations_met.append(
                    f"hallucination:expected={expected_hallu} got={resp.report.hallucination_detected}"
                )
        if min_faith is not None:
            if resp.report.faithfulness_score >= min_faith:
                expectations_met.append("min_faithfulness")
            else:
                expectations_met.append(
                    f"min_faithfulness:expected>={min_faith} got={resp.report.faithfulness_score:.3f}"
                )
        if max_faith is not None:
            if resp.report.faithfulness_score <= max_faith:
                expectations_met.append("max_faithfulness")
            else:
                expectations_met.append(
                    f"max_faithfulness:expected<={max_faith} got={resp.report.faithfulness_score:.3f}"
                )
        all_met = all("=" not in e and ":" not in e for e in expectations_met)

        per_case.append({
            "name": case["name"],
            "description": case["description"],
            "method": resp.method.value,
            "provider_used": resp.metadata.provider_used,
            "faithfulness_score": round(resp.report.faithfulness_score, 4),
            "hallucination_detected": resp.report.hallucination_detected,
            "risk_level": resp.report.risk_level.value,
            "total_claims": resp.report.total_claims,
            "supported_count": resp.report.supported_count,
            "unsupported_count": resp.report.unsupported_count,
            "unsupported_claims": [
                {
                    "claim_id": c.claim_id,
                    "claim": c.claim,
                    "reason": c.reason,
                }
                for c in resp.report.unsupported_claims
            ],
            "latency_ms": round(latency_ms, 3),
            "expectations": expectations_met,
            "all_expectations_met": all_met,
        })

    # Aggregate.
    total = len(GOLDEN_DATASET)
    cases_meeting_expectations = sum(1 for c in per_case if c["all_expectations_met"])
    detection_accuracy = cases_meeting_expectations / total if total else 0.0
    avg_latency = statistics.mean(latencies) if latencies else 0.0
    p95_latency = (
        statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 5 else max(latencies or [0.0])
    )
    avg_faithfulness = statistics.mean(faithfulness_scores) if faithfulness_scores else 0.0
    hallucination_rate = (
        sum(1 for h in hallucination_flags if h) / total if total else 0.0
    )

    report: Dict[str, Any] = {
        "module": "hallucination_guard",
        "version": "5.4.0",
        "method": method.value,
        "use_mock_provider": use_mock_provider,
        "total_cases": total,
        "cases_meeting_expectations": cases_meeting_expectations,
        "detection_accuracy": round(detection_accuracy, 4),
        "average_faithfulness_score": round(avg_faithfulness, 4),
        "hallucination_rate": round(hallucination_rate, 4),
        "average_latency_ms": round(avg_latency, 3),
        "p95_latency_ms": round(p95_latency, 3),
        "cases": per_case,
    }
    return report


def write_report(report: Dict[str, Any], path: Optional[Path] = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    target = path or (REPORTS_DIR / "hallucination_report.json")
    target.write_text(json.dumps(report, indent=2))
    return target


def _print_summary(report: Dict[str, Any]) -> None:
    print("=" * 72)
    print(f"Hallucination Guard Benchmark — method={report['method']}")
    print("=" * 72)
    print(f"  total cases:                 {report['total_cases']}")
    print(f"  cases meeting expectations:  {report['cases_meeting_expectations']}")
    print(f"  detection accuracy:          {report['detection_accuracy']:.2%}")
    print(f"  average faithfulness:        {report['average_faithfulness_score']:.3f}")
    print(f"  hallucination rate:          {report['hallucination_rate']:.2%}")
    print(f"  average latency (ms):        {report['average_latency_ms']:.2f}")
    print(f"  p95 latency (ms):            {report['p95_latency_ms']:.2f}")
    print()
    print(f"  {'case':<35} {'faith':>8} {'hallu':>6} {'risk':>8} {'pass':>6}")
    for c in report["cases"]:
        pass_marker = "OK" if c["all_expectations_met"] else "FAIL"
        print(
            f"  {c['name']:<35} "
            f"{c['faithfulness_score']:>8.3f} "
            f"{str(c['hallucination_detected']):>6} "
            f"{c['risk_level']:>8} "
            f"{pass_marker:>6}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--method",
        choices=[m.value for m in VerificationMethod],
        default=VerificationMethod.LEXICAL.value,
        help="Verification method to benchmark (default: lexical).",
    )
    parser.add_argument(
        "--use-mock-provider",
        action="store_true",
        help="Wire a mock LLM provider for LLM/HYBRID methods.",
    )
    parser.add_argument("--out", type=str, default=None, help="Override report path.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    method = VerificationMethod(args.method)
    report = asyncio.run(
        run_benchmark(method=method, use_mock_provider=args.use_mock_provider)
    )
    out = write_report(report, Path(args.out) if args.out else None)
    _print_summary(report)
    print()
    print(f"report written to: {out}")


if __name__ == "__main__":
    main()
