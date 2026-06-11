"""Module 6.8 — Production health-check API.

Endpoints
---------
* ``GET /health/live``  — liveness probe (always 200 if the process runs).
* ``GET /health/ready`` — readiness probe (checks critical components).
* ``GET /health/deep``  — deep diagnostic (checks all components).
* ``GET /health``       — simple ``ok`` response.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.health import (
    HealthChecker,
    HealthStatus,
    always_healthy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# Singleton health checker (wired by main.py startup hook).
_health_checker: HealthChecker = HealthChecker()


def get_health_checker() -> HealthChecker:
    return _health_checker


def set_health_checker(checker: HealthChecker) -> None:
    global _health_checker
    _health_checker = checker


@router.get(
    "",
    summary="Simple liveness check",
    response_class=JSONResponse,
)
async def health() -> Dict[str, Any]:
    return {"status": "ok"}


@router.get(
    "/live",
    summary="Liveness probe (Kubernetes style)",
    response_class=JSONResponse,
)
async def liveness() -> JSONResponse:
    """Always 200 — signals the process is running."""
    return JSONResponse({"status": "alive"})


@router.get(
    "/ready",
    summary="Readiness probe (checks critical components)",
    response_class=JSONResponse,
    responses={503: {"description": "Service not ready"}},
)
async def readiness() -> JSONResponse:
    """Returns 200 only if all critical components are healthy."""
    checker = get_health_checker()
    # Critical = liveness + registered "critical" components.
    critical_checks = [
        name for name in checker.checks()
        if name in {"liveness", "storage", "config", "environment", "database"}
    ]
    report = checker.run(names=critical_checks)
    if report.status == HealthStatus.UNHEALTHY:
        return JSONResponse(report.to_dict(), status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return JSONResponse(report.to_dict())


@router.get(
    "/deep",
    summary="Deep diagnostic of all registered components",
    response_class=JSONResponse,
    responses={503: {"description": "Service unhealthy"}},
)
async def deep() -> JSONResponse:
    checker = get_health_checker()
    report = checker.run()
    if report.status == HealthStatus.UNHEALTHY:
        return JSONResponse(report.to_dict(), status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return JSONResponse(report.to_dict())


__all__ = [
    "get_health_checker",
    "router",
    "set_health_checker",
]
