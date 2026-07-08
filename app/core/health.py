"""Module 6.8 — Production health checks.

This module provides:

* :class:`ComponentHealth` — per-component health snapshot.
* :class:`HealthReport` — aggregated report.
* :class:`HealthChecker` — runs each registered check and aggregates
  the results.
* A few standard checkers (always-healthy, environment-present,
  storage-writable).
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = __import__("logging").getLogger(__name__)


class HealthStatus(str, Enum):
    """Component health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health snapshot for a single component."""

    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class HealthReport:
    """Aggregated health report."""

    status: HealthStatus
    components: List[ComponentHealth] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "6.8.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "components": [c.to_dict() for c in self.components],
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
        }

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


CheckFn = Callable[[], ComponentHealth]


class HealthChecker:
    """Aggregates a set of named health checks."""

    def __init__(self, version: str = "6.8.0") -> None:
        self._checks: Dict[str, CheckFn] = {}
        self._lock = threading.RLock()
        self.version = version

    def register(self, name: str, fn: CheckFn) -> None:
        with self._lock:
            self._checks[name] = fn

    def unregister(self, name: str) -> None:
        with self._lock:
            self._checks.pop(name, None)

    def checks(self) -> Dict[str, CheckFn]:
        with self._lock:
            return dict(self._checks)

    def run(self, *, names: Optional[List[str]] = None) -> HealthReport:
        with self._lock:
            selected = (
                list(self._checks.items())
                if names is None
                else [(n, self._checks[n]) for n in names if n in self._checks]
            )
        components: List[ComponentHealth] = []
        agg = HealthStatus.HEALTHY
        for name, fn in selected:
            start = time.perf_counter()
            try:
                comp = fn()
                latency = (time.perf_counter() - start) * 1000.0
                comp.latency_ms = latency
            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000.0
                comp = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message=f"check raised: {exc}",
                )
            components.append(comp)
            if comp.status == HealthStatus.UNHEALTHY:
                agg = HealthStatus.UNHEALTHY
            elif comp.status == HealthStatus.DEGRADED and agg != HealthStatus.UNHEALTHY:
                agg = HealthStatus.DEGRADED
        return HealthReport(status=agg, components=components, version=self.version)


# ─── Built-in checks ─────────────────────────────────────────────────────


def always_healthy(name: str = "liveness") -> ComponentHealth:
    return ComponentHealth(name=name, status=HealthStatus.HEALTHY, message="ok")


def env_present(name: str, env_var: str) -> ComponentHealth:
    present = env_var in os.environ
    return ComponentHealth(
        name=name,
        status=HealthStatus.HEALTHY if present else HealthStatus.DEGRADED,
        message=("present" if present else f"{env_var} not set"),
        details={"env_var": env_var, "present": present},
    )


def storage_writable(name: str, path: Path) -> ComponentHealth:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        disk = shutil.disk_usage(path)
        return ComponentHealth(
            name=name,
            status=HealthStatus.HEALTHY,
            message="writable",
            details={
                "path": str(path),
                "free_bytes": disk.free,
                "total_bytes": disk.total,
            },
        )
    except Exception as exc:
        return ComponentHealth(
            name=name,
            status=HealthStatus.UNHEALTHY,
            message=f"not writable: {exc}",
            details={"path": str(path)},
        )


__all__ = [
    "CheckFn",
    "ComponentHealth",
    "HealthChecker",
    "HealthReport",
    "HealthStatus",
    "always_healthy",
    "env_present",
    "storage_writable",
]
