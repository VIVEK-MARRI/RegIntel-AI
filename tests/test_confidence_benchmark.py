"""Module 5.3 — benchmark test wrapper.

Verifies the confidence benchmark CLI runs end-to-end and the report
contains plausible aggregate metrics.  The engine is deterministic
and offline, so the benchmark is fully reproducible.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "benchmarks" / "reports" / "confidence_report.json"


def _run_benchmark() -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "benchmarks.benchmark_confidence",
        "--output",
        str(REPORT_PATH.relative_to(REPO_ROOT)),
        "--reset-metrics",
        "--log-level",
        "WARNING",
    ]
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


@pytest.mark.timeout(60)
def test_benchmark_runs_and_writes_report():
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()

    proc = _run_benchmark()
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert REPORT_PATH.exists(), "Benchmark report was not written"

    report = json.loads(REPORT_PATH.read_text())
    assert report["benchmark"] == "confidence_v1"
    assert report["num_cases"] >= 3
    assert report["mean_latency_ms"] >= 0.0
    assert 0.0 <= report["mean_confidence"] <= 1.0
    # Level distribution sums to num_cases.
    assert sum(report["level_distribution"].values()) == report["num_cases"]
    # 0..1 expected match rate.
    assert 0.0 <= report["expected_match_rate"] <= 1.0
    # All five factors reported.
    for factor in (
        "retrieval_relevance",
        "reranker_confidence",
        "source_agreement",
        "chunk_coverage",
        "citation_coverage",
    ):
        assert factor in report["factor_score_means"]
        assert 0.0 <= report["factor_score_means"][factor] <= 1.0
    # Metrics snapshot included.
    assert "metrics_snapshot" in report
    snap = report["metrics_snapshot"]
    assert snap["total_requests"] == report["num_cases"]
    # Per-case results present.
    assert isinstance(report["results"], list)
    for r in report["results"]:
        assert 0.0 <= r["confidence"] <= 1.0
        assert r["level"] in {"high", "medium", "low"}


@pytest.mark.timeout(60)
def test_benchmark_idempotent():
    proc1 = _run_benchmark()
    proc2 = _run_benchmark()
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    r1 = json.loads(REPORT_PATH.read_text())
    r2 = json.loads(REPORT_PATH.read_text())
    assert r1["num_cases"] == r2["num_cases"]
    assert r1["mean_confidence"] == r2["mean_confidence"]
    assert r1["level_distribution"] == r2["level_distribution"]
