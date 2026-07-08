"""Report generators for the M10.5 benchmark platform.

Produces four kinds of JSON reports plus an aggregate ``summary.md`` and
``summary.html``:

* ``latency_report.json``            â€” p50/p90/p95/p99, by operation kind
* ``cost_report.json``               â€” tokens, cost units, per-op / per-success
* ``agent_performance_report.json``  â€” per-agent success / latency / cost
* ``system_performance_report.json`` â€” process + host snapshots
"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.benchmark.metrics_collector import (
    compute_cost_summary,
    compute_latency_stats,
)
from app.benchmark.models import (
    BenchmarkResponse,
    OperationResult,
    SystemSnapshot,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Reporter:
    """Generates benchmark reports from a :class:`BenchmarkResponse`."""

    # â”€â”€â”€ Latency â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def latency_report(self, response: BenchmarkResponse) -> Dict[str, Any]:
        all_lat = [r.latency.total_ms for r in response.results]
        by_kind: Dict[str, List[float]] = defaultdict(list)
        for r in response.results:
            by_kind[r.kind.value].append(r.latency.total_ms)

        return {
            "report": "latency",
            "run_id": response.run_id,
            "name": response.name,
            "suite": response.suite.value,
            "summary": response.summary.latency.model_dump(mode="json"),
            "by_kind": {
                k: compute_latency_stats(v).model_dump(mode="json")
                for k, v in by_kind.items()
            },
            "wall_clock_ms": response.summary.wall_clock_ms,
            "throughput_ops_per_sec": response.summary.throughput_ops_per_sec,
            "generated_at": _now_iso(),
        }

    # â”€â”€â”€ Cost â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def cost_report(self, response: BenchmarkResponse) -> Dict[str, Any]:
        return {
            "report": "cost",
            "run_id": response.run_id,
            "name": response.name,
            "suite": response.suite.value,
            "summary": response.summary.cost.model_dump(mode="json"),
            "by_kind": self._cost_by_kind(response.results),
            "config": dict(response.config),
            "generated_at": _now_iso(),
        }

    def _cost_by_kind(self, results: Sequence[OperationResult]) -> Dict[str, Dict[str, Any]]:
        buckets: Dict[str, List[OperationResult]] = defaultdict(list)
        for r in results:
            buckets[r.kind.value].append(r)
        out: Dict[str, Dict[str, Any]] = {}
        for k, rs in buckets.items():
            success = sum(1 for r in rs if r.success)
            cs = compute_cost_summary(
                (r.tokens for r in rs),
                cost_per_1k_input=response_cost_factor(rs, "input"),
                cost_per_1k_output=response_cost_factor(rs, "output"),
                cost_per_retrieval=response_cost_factor(rs, "retrieval"),
                successful=success or 1,
                total=len(rs) or 1,
            )
            out[k] = {
                "count": len(rs),
                "successful": success,
                **cs.model_dump(mode="json"),
            }
        return out

    # â”€â”€â”€ Agent performance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def agent_performance_report(self, response: BenchmarkResponse) -> Dict[str, Any]:
        agent_ops = [r for r in response.results if r.kind.value == "agent"]
        by_name: Dict[str, List[OperationResult]] = defaultdict(list)
        for r in agent_ops:
            by_name[r.name].append(r)

        per_agent = []
        for name, rs in by_name.items():
            success = sum(1 for r in rs if r.success)
            latencies = [r.latency.total_ms for r in rs]
            tokens_in = sum(r.tokens.input_tokens for r in rs)
            tokens_out = sum(r.tokens.output_tokens for r in rs)
            cost = sum(r.cost_units for r in rs)
            per_agent.append({
                "agent": name,
                "invocations": len(rs),
                "successful": success,
                "failed": len(rs) - success,
                "error_rate": ((len(rs) - success) / len(rs)) if rs else 0.0,
                "latency": compute_latency_stats(latencies).model_dump(mode="json"),
                "tokens": {"input": tokens_in, "output": tokens_out},
                "cost_units": round(cost, 8),
            })

        # Sort leaderboard-style: composite score = 0.6*success + 0.3*invocations_normalized + 0.1*speed
        if per_agent:
            max_inv = max(p["invocations"] for p in per_agent) or 1
            for p in per_agent:
                speed = 1.0 / (1.0 + p["latency"]["mean_ms"] / 1000.0)
                p["composite_score"] = round(
                    0.6 * (1 - p["error_rate"])
                    + 0.3 * (p["invocations"] / max_inv)
                    + 0.1 * speed,
                    4,
                )
            per_agent.sort(key=lambda p: p["composite_score"], reverse=True)

        return {
            "report": "agent_performance",
            "run_id": response.run_id,
            "name": response.name,
            "suite": response.suite.value,
            "leaderboard": per_agent,
            "totals": {
                "agents": len(per_agent),
                "invocations": sum(p["invocations"] for p in per_agent),
                "successful": sum(p["successful"] for p in per_agent),
                "failed": sum(p["failed"] for p in per_agent),
            },
            "generated_at": _now_iso(),
        }

    # â”€â”€â”€ System performance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def system_performance_report(
        self,
        response: BenchmarkResponse,
        snapshots: Sequence[SystemSnapshot] = (),
    ) -> Dict[str, Any]:
        snaps = list(snapshots) or list(response.system_snapshots)
        rss_values = [s.process_rss_mb for s in snaps]
        cpu_values = [s.process_cpu_percent for s in snaps]
        threads_values = [s.process_threads for s in snaps]
        host_cpu = [s.host_cpu_percent for s in snaps if s.host_cpu_percent is not None]
        host_mem = [s.host_memory_percent for s in snaps if s.host_memory_percent is not None]

        return {
            "report": "system_performance",
            "run_id": response.run_id,
            "name": response.name,
            "suite": response.suite.value,
            "process": {
                "rss_mb": _stats(rss_values),
                "cpu_percent": _stats(cpu_values),
                "threads": _stats_int(threads_values),
                "snapshots": [s.model_dump(mode="json") for s in snaps],
            },
            "host": {
                "cpu_percent": _stats(host_cpu),
                "memory_percent": _stats(host_mem),
            },
            "totals": {
                "operations": response.summary.total_operations,
                "throughput_ops_per_sec": response.summary.throughput_ops_per_sec,
                "wall_clock_ms": response.summary.wall_clock_ms,
                "errors": response.summary.failed,
            },
            "generated_at": _now_iso(),
        }

    # â”€â”€â”€ Disk writers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def write_all(self, response: BenchmarkResponse, out_dir: str) -> Dict[str, str]:
        os.makedirs(out_dir, exist_ok=True)
        written: Dict[str, str] = {}

        def _write(name: str, payload: Mapping[str, Any]) -> None:
            path = os.path.join(out_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            written[name] = path

        _write("latency_report.json", self.latency_report(response))
        _write("cost_report.json", self.cost_report(response))
        _write("agent_performance_report.json", self.agent_performance_report(response))
        _write("system_performance_report.json", self.system_performance_report(response))

        # Save the raw run for later inspection.
        raw_path = os.path.join(out_dir, "run.json")
        with open(raw_path, "w", encoding="utf-8") as fh:
            json.dump(response.model_dump(mode="json"), fh, indent=2, default=str)
        written["run.json"] = raw_path

        # Markdown + HTML summary for the GitHub comment.
        summary_md = self.render_markdown_summary(response)
        with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
            fh.write(summary_md)
        written["summary.md"] = os.path.join(out_dir, "summary.md")

        summary_html = self.render_html_summary(response)
        with open(os.path.join(out_dir, "summary.html"), "w", encoding="utf-8") as fh:
            fh.write(summary_html)
        written["summary.html"] = os.path.join(out_dir, "summary.html")

        return written

    # â”€â”€â”€ Markdown / HTML renderers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def render_markdown_summary(self, response: BenchmarkResponse) -> str:
        s = response.summary
        lines = [
            f"### Benchmark â€” `{response.name}`",
            f"- Run ID: `{response.run_id}`",
            f"- Suite: `{response.suite.value}`",
            f"- Operations: **{s.total_operations}** (success {s.successful}, failed {s.failed})",
            f"- Error rate: **{s.error_rate * 100:.2f}%**",
            f"- Throughput: **{s.throughput_ops_per_sec:.2f} ops/s**",
            f"- Wall clock: **{s.wall_clock_ms:.2f} ms**",
            "",
            "#### Latency (ms)",
            f"- min {s.latency.min_ms:.2f} / mean {s.latency.mean_ms:.2f} / median {s.latency.median_ms:.2f}",
            f"- p50 {s.latency.p50_ms:.2f} / p90 {s.latency.p90_ms:.2f} / p95 {s.latency.p95_ms:.2f} / p99 {s.latency.p99_ms:.2f}",
            f"- max {s.latency.max_ms:.2f}",
            "",
            "#### Cost",
            f"- Total: **{s.cost.total_cost_units:.6f} {s.cost.currency}**",
            f"- Per operation: **{s.cost.cost_per_operation:.6f}**",
            f"- Per success: **{s.cost.cost_per_success:.6f}**",
            f"- Tokens: in {s.cost.total_input_tokens:,} / out {s.cost.total_output_tokens:,}",
            "",
            "#### Latency by kind",
            "| Kind | count | p50 | p95 | p99 | mean |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for k, stats in sorted(s.latency_by_kind.items()):
            lines.append(
                f"| {k} | {stats.count} | {stats.p50_ms:.2f} | {stats.p95_ms:.2f} | {stats.p99_ms:.2f} | {stats.mean_ms:.2f} |"
            )
        return "\n".join(lines) + "\n"

    def render_html_summary(self, response: BenchmarkResponse) -> str:
        s = response.summary
        rows = "".join(
            f"<tr><td>{k}</td><td>{v.count}</td><td>{v.p50_ms:.2f}</td><td>{v.p95_ms:.2f}</td><td>{v.p99_ms:.2f}</td><td>{v.mean_ms:.2f}</td></tr>"
            for k, v in sorted(s.latency_by_kind.items())
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Benchmark {response.name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #111; }}
  h1, h2, h3 {{ color: #0f172a; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 0.5rem 0.75rem; text-align: right; }}
  th {{ background: #f1f5f9; text-align: left; }}
  td:first-child {{ text-align: left; font-family: ui-monospace, monospace; }}
  .metric {{ display: inline-block; margin-right: 2rem; }}
  .metric .v {{ font-size: 1.5rem; font-weight: 600; color: #2563eb; }}
  .metric .l {{ color: #64748b; font-size: 0.85rem; }}
</style>
</head><body>
<h1>Benchmark: {response.name}</h1>
<p>Run <code>{response.run_id}</code> Â· suite <code>{response.suite.value}</code></p>
<h2>Overview</h2>
<div>
  <div class="metric"><div class="v">{s.total_operations}</div><div class="l">operations</div></div>
  <div class="metric"><div class="v">{s.error_rate * 100:.2f}%</div><div class="l">error rate</div></div>
  <div class="metric"><div class="v">{s.throughput_ops_per_sec:.2f}</div><div class="l">ops/sec</div></div>
  <div class="metric"><div class="v">{s.wall_clock_ms:.0f} ms</div><div class="l">wall clock</div></div>
</div>
<h2>Latency by kind (ms)</h2>
<table>
<thead><tr><th>kind</th><th>count</th><th>p50</th><th>p95</th><th>p99</th><th>mean</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<h2>Cost</h2>
<p>Total <strong>{s.cost.total_cost_units:.6f} {s.cost.currency}</strong> Â· {s.cost.total_input_tokens:,} input tokens Â· {s.cost.total_output_tokens:,} output tokens</p>
</body></html>
"""


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def response_cost_factor(_results: Iterable[OperationResult], _kind: str) -> float:
    """Best-effort cost factor pull from per-result metadata; falls back to default."""
    return {
        "input": 0.00015,
        "output": 0.00060,
        "retrieval": 0.00001,
    }[_kind]


def _stats(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0}
    return {
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": float(statistics.fmean(values)),
        "median": float(statistics.median(values)),
    }


def _stats_int(values: Sequence[int]) -> Dict[str, int]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0, "median": 0}
    return {
        "min": int(min(values)),
        "max": int(max(values)),
        "mean": int(statistics.fmean(values)),
        "median": int(statistics.median(values)),
    }
