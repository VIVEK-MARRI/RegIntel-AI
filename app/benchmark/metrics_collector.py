"""Low-level metrics collection for the M10.5 benchmark platform.

The :class:`MetricsCollector` provides portable helpers for measuring
latency, memory, token usage, and cost. The implementation gracefully
degrades when optional libraries (``psutil``, ``tracemalloc``) are missing
or unsupported on the current platform (e.g. ``resource`` on Windows).
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from app.benchmark.models import (
    CostSummary,
    LatencyMetric,
    LatencyStats,
    MemoryMetric,
    SystemSnapshot,
    TokenUsage,
)


# ─── Optional imports ──────────────────────────────────────────────────

try:  # pragma: no cover - optional dependency
    import psutil  # type: ignore
except Exception:  # pragma: no cover - environment-specific
    psutil = None  # type: ignore[assignment]


_HAS_TRACEMALLOC = hasattr(sys, "gettrace") or hasattr(sys, "settrace")
_tracemalloc_mod = None
try:  # pragma: no cover - optional
    import tracemalloc as _tracemalloc_mod  # type: ignore
except Exception:  # pragma: no cover
    _tracemalloc_mod = None


# ─── Per-process helpers ──────────────────────────────────────────────

def _process_memory_mb() -> float:
    """Resident-set size in MB for the current process (best effort)."""
    if psutil is not None:
        try:
            return float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024)
        except Exception:
            pass
    # Fall back to the Win32 process API on Windows.
    if platform.system() == "Windows":  # pragma: no cover - Windows specific
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
            if ctypes.windll.kernel32.GetProcessMemoryInfo(  # type: ignore[attr-defined]
                handle, ctypes.byref(counters), counters.cb
            ):
                return float(counters.WorkingSetSize) / (1024 * 1024)
        except Exception:
            pass
    return 0.0


def _process_vms_mb() -> float:
    """Virtual memory size in MB for the current process."""
    if psutil is not None:
        try:
            return float(psutil.Process(os.getpid()).memory_info().vms) / (1024 * 1024)
        except Exception:
            pass
    return 0.0


def _process_cpu_percent() -> float:
    """Process CPU% (interval=None since we are sampling)."""
    if psutil is not None:
        try:
            return float(psutil.Process(os.getpid()).cpu_percent(interval=None))
        except Exception:
            pass
    return 0.0


def _process_threads() -> int:
    if psutil is not None:
        try:
            return int(psutil.Process(os.getpid()).num_threads())
        except Exception:
            pass
    return 0


def _host_loadavg() -> Optional[List[float]]:
    if psutil is not None:
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            load: List[float] = [float(cpu)]
            try:
                loadavg = os.getloadavg()
                load = [float(x) for x in loadavg]
            except (OSError, AttributeError):
                pass
            return [float(cpu), float(mem), *load]
        except Exception:
            pass
    return None


def _host_memory_percent() -> Optional[float]:
    if psutil is not None:
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            pass
    return None


# ─── Stats helpers ─────────────────────────────────────────────────────

def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Return the linear-interpolated percentile of a sorted sequence."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def compute_latency_stats(values: Iterable[float]) -> LatencyStats:
    """Compute aggregate statistics from an iterable of millisecond values."""
    values = [float(v) for v in values if v is not None]
    if not values:
        return LatencyStats(
            count=0, min_ms=0.0, max_ms=0.0, mean_ms=0.0, median_ms=0.0,
            p50_ms=0.0, p90_ms=0.0, p95_ms=0.0, p99_ms=0.0, stddev_ms=0.0,
        )
    sorted_v = sorted(values)
    return LatencyStats(
        count=len(sorted_v),
        min_ms=sorted_v[0],
        max_ms=sorted_v[-1],
        mean_ms=statistics.fmean(sorted_v),
        median_ms=statistics.median(sorted_v),
        p50_ms=_percentile(sorted_v, 50),
        p90_ms=_percentile(sorted_v, 90),
        p95_ms=_percentile(sorted_v, 95),
        p99_ms=_percentile(sorted_v, 99),
        stddev_ms=statistics.pstdev(sorted_v) if len(sorted_v) > 1 else 0.0,
    )


def compute_cost_summary(
    usages: Iterable[TokenUsage],
    cost_per_1k_input: float,
    cost_per_1k_output: float,
    cost_per_retrieval: float,
    successful: int,
    total: int,
) -> CostSummary:
    """Aggregate token usages and compute the total cost."""
    usages = list(usages)
    in_t = sum(u.input_tokens for u in usages)
    out_t = sum(u.output_tokens for u in usages)
    retr = sum(u.retrieval_units for u in usages)
    total_cost = (
        (in_t / 1000.0) * cost_per_1k_input
        + (out_t / 1000.0) * cost_per_1k_output
        + retr * cost_per_retrieval
    )
    return CostSummary(
        total_cost_units=round(total_cost, 8),
        total_input_tokens=in_t,
        total_output_tokens=out_t,
        total_retrieval_units=retr,
        cost_per_operation=round(total_cost / total, 8) if total else 0.0,
        cost_per_success=round(total_cost / successful, 8) if successful else 0.0,
        currency="USD",
    )


# ─── Public collector ─────────────────────────────────────────────────

class MetricsCollector:
    """Collects latency, memory and token metrics around operation calls."""

    def __init__(self, *, tracemalloc: bool = False) -> None:
        self._tracemalloc_enabled = bool(tracemalloc) and _tracemalloc_mod is not None
        if self._tracemalloc_enabled:
            try:
                if not _tracemalloc_mod.is_tracing():  # type: ignore[union-attr]
                    _tracemalloc_mod.start()  # type: ignore[union-attr]
            except Exception:  # pragma: no cover
                self._tracemalloc_enabled = False

    # ─── snapshots ──────────────────────────────────────────────────

    def memory_snapshot(self) -> MemoryMetric:
        rss = _process_memory_mb()
        heap: Optional[float] = None
        traced: Optional[float] = None
        if self._tracemalloc_enabled and _tracemalloc_mod is not None:
            try:
                snap = _tracemalloc_mod.take_snapshot()  # type: ignore[union-attr]
                stats = snap.statistics("filename")
                traced = float(sum(s.size for s in stats)) / (1024 * 1024)
            except Exception:  # pragma: no cover
                traced = None
        return MemoryMetric(rss_mb=rss, heap_mb=heap, traced_mb=traced)

    def system_snapshot(self) -> SystemSnapshot:
        host = _host_loadavg()
        return SystemSnapshot(
            process_rss_mb=_process_memory_mb(),
            process_vms_mb=_process_vms_mb(),
            process_cpu_percent=_process_cpu_percent(),
            process_threads=_process_threads(),
            host_cpu_percent=host[0] if host else None,
            host_memory_percent=_host_memory_percent(),
            host_loadavg=host[1:] if host and len(host) > 1 else None,
        )

    # ─── timing context ────────────────────────────────────────────

    @contextmanager
    def time(self):
        """Yield a callable that returns a :class:`LatencyMetric` for the elapsed time."""
        start = time.perf_counter()
        captured: Dict[str, float] = {"total_ms": 0.0}

        def _finalise(server_ms: Optional[float] = None, queue_ms: Optional[float] = None) -> LatencyMetric:
            end = time.perf_counter()
            total_ms = (end - start) * 1000.0
            captured["total_ms"] = total_ms
            return LatencyMetric(
                total_ms=total_ms,
                server_ms=server_ms,
                queue_ms=queue_ms,
            )

        try:
            yield _finalise
        finally:
            if captured["total_ms"] == 0.0:
                end = time.perf_counter()
                captured["total_ms"] = (end - start) * 1000.0

    # ─── token accounting ──────────────────────────────────────────

    def compute_tokens(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        embedding_tokens: int = 0,
        retrieval_units: int = 0,
    ) -> TokenUsage:
        return TokenUsage(
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
            embedding_tokens=max(0, int(embedding_tokens)),
            retrieval_units=max(0, int(retrieval_units)),
        )

    def compute_cost(
        self,
        usage: TokenUsage,
        cost_per_1k_input: float,
        cost_per_1k_output: float,
        cost_per_retrieval: float,
    ) -> float:
        return round(
            (usage.input_tokens / 1000.0) * cost_per_1k_input
            + (usage.output_tokens / 1000.0) * cost_per_1k_output
            + usage.retrieval_units * cost_per_retrieval,
            8,
        )


# ─── Convenience dataclass for callers that want a stateful helper ───

@dataclass
class _TokenLedger:
    total_input: int = 0
    total_output: int = 0
    total_embeddings: int = 0
    total_retrievals: int = 0

    def add(self, usage: TokenUsage) -> None:
        self.total_input += usage.input_tokens
        self.total_output += usage.output_tokens
        self.total_embeddings += usage.embedding_tokens
        self.total_retrievals += usage.retrieval_units

    def to_usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.total_input,
            output_tokens=self.total_output,
            embedding_tokens=self.total_embeddings,
            retrieval_units=self.total_retrievals,
        )
