"""Module 5.1 — benchmark test wrapper.

Verifies the benchmark CLI runs end-to-end and the report contains
plausible aggregate metrics.  Uses the in-process Mock provider so it
runs offline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "benchmarks" / "reports" / "answer_gen_report.json"


def _run_benchmark() -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "benchmarks.benchmark_answer_generation",
        "--provider",
        "mock",
        "--model",
        "mock-default",
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
    assert report["benchmark"] == "answer_generation_v1"
    assert report["provider"] == "mock"
    assert report["num_questions"] >= 1
    assert report["num_errors"] == 0
    assert report["mean_latency_ms"] >= 0.0
    assert report["mean_total_tokens"] >= 0.0
    assert 0.0 <= report["mean_evidence_coverage"] <= 1.0
    assert 0.0 <= report["executive_summary_present_rate"] <= 1.0
    assert 0.0 <= report["detailed_explanation_present_rate"] <= 1.0
    assert isinstance(report["results"], list)
    for r in report["results"]:
        assert r["query"]
        assert r["latency_ms"] >= 0.0
        assert isinstance(r["expected_chunk_ids"], list)


@pytest.mark.timeout(60)
def test_benchmark_idempotent():
    proc1 = _run_benchmark()
    proc2 = _run_benchmark()
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    r1 = json.loads(REPORT_PATH.read_text())
    r2 = json.loads(REPORT_PATH.read_text())
    assert r1["num_questions"] == r2["num_questions"]
    assert r1["num_errors"] == r2["num_errors"] == 0
