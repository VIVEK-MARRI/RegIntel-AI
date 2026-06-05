"""Module 5.2 — benchmark test wrapper.

Verifies the citation benchmark CLI runs end-to-end and the report
contains plausible aggregate metrics.  The citation engine is
deterministic and offline, so the benchmark is fully reproducible.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "benchmarks" / "reports" / "citation_report.json"


def _run_benchmark() -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "benchmarks.benchmark_citation",
        "--output",
        str(REPORT_PATH.relative_to(REPO_ROOT)),
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
    assert report["benchmark"] == "citation_v1"
    assert report["num_cases"] >= 1
    assert report["num_errors"] == 0
    assert report["mean_latency_ms"] >= 0.0
    assert 0.0 <= report["mean_coverage"] <= 1.0
    assert 0.0 <= report["min_coverage"] <= 1.0
    assert 0.0 <= report["mean_doc_recall"] <= 1.0
    assert 0.0 <= report["full_coverage_rate"] <= 1.0
    assert isinstance(report["results"], list)
    for r in report["results"]:
        assert r["query"]
        assert r["latency_ms"] >= 0.0
        assert 0.0 <= r["coverage_ratio"] <= 1.0
        assert 0.0 <= r["document_recall"] <= 1.0


@pytest.mark.timeout(60)
def test_benchmark_idempotent():
    proc1 = _run_benchmark()
    proc2 = _run_benchmark()
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    r1 = json.loads(REPORT_PATH.read_text())
    r2 = json.loads(REPORT_PATH.read_text())
    assert r1["num_cases"] == r2["num_cases"]
    assert r1["num_errors"] == r2["num_errors"] == 0
    # Determinism: identical reports on re-run.
    assert r1["mean_coverage"] == r2["mean_coverage"]
    assert r1["mean_doc_recall"] == r2["mean_doc_recall"]
