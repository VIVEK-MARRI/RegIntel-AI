"""Module 6.8 — Environment & startup validation.

Helpers
-------
* :func:`validate_environment` — checks required environment variables
  and returns a list of errors (empty list = OK).
* :func:`validate_required_env` — raises :class:`EnvironmentValidationError`
  if any required env var is missing.
* :func:`on_startup` / :func:`on_shutdown` — FastAPI event handlers
  that wire the health checker and run pre-flight checks.
* :class:`EnvironmentValidationError` — raised when validation fails.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EnvironmentValidationError(RuntimeError):
    """Raised when one or more required environment variables are missing."""


@dataclass
class StartupReport:
    """Result of a startup validation run."""

    started_at: datetime
    finished_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    components_registered: List[str] = field(default_factory=list)
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "components_registered": list(self.components_registered),
            "success": self.success,
        }


def validate_environment(
    required: Optional[List[str]] = None,
    *,
    raise_on_error: bool = False,
) -> List[str]:
    """Return a list of validation errors (empty if all OK).

    Parameters
    ----------
    required:
        Names of environment variables that must be present.
    raise_on_error:
        If True, raise :class:`EnvironmentValidationError` when any
        required variable is missing.
    """
    required = list(required or [])
    errors: List[str] = []
    for var in required:
        if not os.environ.get(var):
            errors.append(f"missing required environment variable: {var}")
    if raise_on_error and errors:
        raise EnvironmentValidationError("; ".join(errors))
    return errors


def validate_storage_root(path: Path) -> List[str]:
    """Ensure ``STORAGE_ROOT`` exists and is writable."""
    errors: List[str] = []
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".startup_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"storage root not writable: {path} ({exc})")
    return errors


def register_default_health_checks(
    health_checker,  # type: ignore[no-untyped-def]
    *,
    required_env: Optional[List[str]] = None,
    storage_root: Optional[Path] = None,
) -> List[str]:
    """Register a small set of standard health checks and return their names.

    Re-registering with the same name replaces the previous check.
    """
    from app.core.health import (
        ComponentHealth,
        HealthStatus,
        env_present,
        storage_writable,
    )

    registered: List[str] = []

    health_checker.register("liveness", lambda: ComponentHealth(
        name="liveness",
        status=HealthStatus.HEALTHY,
        message="process alive",
    ))
    registered.append("liveness")

    if required_env:
        for var in required_env:
            def _make_check(v=var):  # type: ignore[no-untyped-def]
                return lambda: env_present(name=f"env:{v}", env_var=v)
            name = f"env:{var}"
            health_checker.register(name, _make_check())
            registered.append(name)

    if storage_root is not None:
        health_checker.register(
            "storage",
            lambda: storage_writable("storage", storage_root),
        )
        registered.append("storage")

    return registered


def on_startup(
    app=None,  # type: ignore[no-untyped-def]
    *,
    required_env: Optional[List[str]] = None,
    storage_root: Optional[Path] = None,
    raise_on_error: bool = False,
) -> StartupReport:
    """Run pre-flight startup checks.

    Registers default health checks on the singleton health checker
    (see :mod:`app.api.v1.health`) and validates environment.

    Returns
    -------
    StartupReport
        A structured report; ``success`` is True if there are no
        blocking errors.
    """
    from app.api.v1.health import get_health_checker

    report = StartupReport(started_at=datetime.now(timezone.utc))
    env_errors = validate_environment(required_env)
    report.errors.extend(env_errors)
    if storage_root is not None:
        report.errors.extend(validate_storage_root(storage_root))
    checker = get_health_checker()
    registered = register_default_health_checks(
        checker,
        required_env=required_env,
        storage_root=storage_root,
    )
    report.components_registered = registered
    report.finished_at = datetime.now(timezone.utc)
    report.success = not report.errors
    if not report.success:
        logger.warning("Startup validation reported issues: %s", report.errors)
        if raise_on_error:
            raise EnvironmentValidationError("; ".join(report.errors))
    else:
        logger.info(
            "Startup validation OK; registered %d health checks.",
            len(registered),
        )
    return report


def on_shutdown(app=None) -> None:  # type: ignore[no-untyped-def]
    """Hook for graceful shutdown logging."""
    logger.info("RegIntel-AI shutting down at %s", datetime.now(timezone.utc).isoformat())


__all__ = [
    "EnvironmentValidationError",
    "StartupReport",
    "on_shutdown",
    "on_startup",
    "register_default_health_checks",
    "validate_environment",
    "validate_storage_root",
]
