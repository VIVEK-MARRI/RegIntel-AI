"""CLI for the M10.5 benchmark platform.

Examples
--------

    python -m app.benchmark.cli --quick --output /tmp/bench.json
    python -m app.benchmark.cli --suite standard --output /tmp/bench.json
    python -m app.benchmark.cli report --input /tmp/bench.json --out-dir /tmp/bench-reports
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import sys

from app.benchmark.benchmark_service import (
    BenchmarkService,
    get_benchmark_service,
)
from app.benchmark.models import BenchmarkRequest, BenchmarkResponse, BenchmarkSuite

logger = logging.getLogger("app.benchmark.cli")


def _parse_suite(value: str) -> BenchmarkSuite:
    value = (value or "").strip().lower()
    try:
        return BenchmarkSuite(value)
    except ValueError as exc:
        raise SystemExit(
            f"Unknown suite: {value!r}. Use one of: {[s.value for s in BenchmarkSuite]}"
        ) from exc


async def _run(args: argparse.Namespace) -> int:
    suite = _parse_suite(args.suite)
    request = BenchmarkRequest(
        suite=suite,
        iterations=args.iterations,
        concurrency=args.concurrency,
        persist_path=args.output if args.output and args.persist else None,
    )
    svc: BenchmarkService = get_benchmark_service()
    response = await svc.run(request)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(response.model_dump(mode="json"), fh, indent=2, default=str)
        print(f"Wrote {args.output}")
    # Always print a one-liner to stdout for CI logs.
    s = response.summary
    print(
        f"suite={response.suite.value} ops={s.total_operations} "
        f"success={s.successful} failed={s.failed} "
        f"err_rate={s.error_rate * 100:.2f}% "
        f"throughput={s.throughput_ops_per_sec:.2f}ops/s "
        f"p50={s.latency.p50_ms:.2f}ms p95={s.latency.p95_ms:.2f}ms p99={s.latency.p99_ms:.2f}ms"
    )
    if args.reports:
        written = svc.write_reports(response, args.reports)
        print(f"Wrote {len(written)} report files into {args.reports}")
    return 0


def _report(args: argparse.Namespace) -> int:
    with open(args.input, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    response = BenchmarkResponse.model_validate(data)
    svc = get_benchmark_service()
    written = svc.write_reports(response, args.out_dir)
    for name, path in written.items():
        print(f"  {name} -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.benchmark.cli")
    sub = parser.add_subparsers(dest="cmd", required=False)

    run = sub.add_parser("run", help="Run a benchmark")
    run.add_argument("--suite", default="standard")
    run.add_argument("--quick", action="store_true", help="Shortcut for --suite quick")
    run.add_argument("--iterations", type=int, default=None)
    run.add_argument("--concurrency", type=int, default=None)
    run.add_argument("--output", default=None, help="Where to write the run JSON")
    run.add_argument(
        "--persist",
        action="store_true",
        help="Persist via BenchmarkRequest.persist_path",
    )
    run.add_argument("--reports", default=None, help="Optional directory for reports")
    run.set_defaults(handler=_run, _parser=run)

    report = sub.add_parser("report", help="Generate reports from a saved run")
    report.add_argument("--input", required=True)
    report.add_argument("--out-dir", required=True)
    report.set_defaults(handler=_report, _parser=report)

    # Default to "run" with sane flags for ergonomics.
    if argv is None:
        argv = sys.argv[1:]
    if not argv or (argv[0] not in {"run", "report"} and argv[0].startswith("-")):
        argv = ["run", *argv]
    args = parser.parse_args(argv)
    # Treat `python -m app.benchmark.cli --quick ...` as a run command.
    if getattr(args, "quick", False):
        args.suite = "quick"
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return (
        asyncio.run(handler(args))
        if inspect.iscoroutinefunction(handler)
        else handler(args)
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
