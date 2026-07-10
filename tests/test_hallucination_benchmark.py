"""Benchmark wrapper tests for Module 5.4 (Hallucination Guard)."""

from __future__ import annotations

import json

import pytest

from benchmarks.benchmark_hallucination import (
    GOLDEN_DATASET,
    REPORTS_DIR,
    run_benchmark,
    write_report,
)
from app.schemas.hallucination import VerificationMethod


@pytest.mark.asyncio
async def test_benchmark_hallucination_lexical_runs():
    """The lexical benchmark runs end-to-end and produces a report."""
    report = await run_benchmark(method=VerificationMethod.LEXICAL)
    assert report["module"] == "hallucination_guard"
    assert report["method"] == "lexical"
    assert report["total_cases"] == len(GOLDEN_DATASET)
    assert len(report["cases"]) == len(GOLDEN_DATASET)
    # Every case carries the expected metadata.
    for case in report["cases"]:
        assert "faithfulness_score" in case
        assert "hallucination_detected" in case
        assert "risk_level" in case
        assert "expectations" in case


@pytest.mark.asyncio
async def test_benchmark_hallucination_writes_report_file():
    """The benchmark writes a JSON report to disk and parses cleanly."""
    report = await run_benchmark(method=VerificationMethod.LEXICAL)
    path = write_report(report, path=REPORTS_DIR / "hallucination_report.json")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["module"] == "hallucination_guard"
    assert data["total_cases"] == len(GOLDEN_DATASET)
    # Aggregate metrics are present and sane.
    assert 0.0 <= data["detection_accuracy"] <= 1.0
    assert 0.0 <= data["average_faithfulness_score"] <= 1.0
    assert 0.0 <= data["hallucination_rate"] <= 1.0
    assert data["average_latency_ms"] >= 0.0
