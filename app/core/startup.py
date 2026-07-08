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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

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

    health_checker.register(
        "liveness",
        lambda: ComponentHealth(
            name="liveness",
            status=HealthStatus.HEALTHY,
            message="process alive",
        ),
    )
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

    if settings.DATABASE_URL and not settings.DATABASE_URL.startswith("sqlite"):

        def _db_check() -> ComponentHealth:
            try:
                import anyio

                async def _probe() -> bool:
                    try:
                        from sqlalchemy.ext.asyncio import create_async_engine

                        engine = create_async_engine(
                            settings.DATABASE_URL, pool_size=1, max_overflow=0
                        )
                        async with engine.connect() as conn:
                            await conn.execute(
                                __import__("sqlalchemy").text("SELECT 1")
                            )
                        await engine.dispose()
                        return True
                    except Exception:
                        return False

                ok = anyio.run(_probe)
                if ok:
                    return ComponentHealth(
                        name="database",
                        status=HealthStatus.HEALTHY,
                        message="database reachable",
                    )
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    message="database unreachable",
                )
            except Exception as exc:
                return ComponentHealth(
                    name="database", status=HealthStatus.UNHEALTHY, message=str(exc)
                )

        health_checker.register("database", _db_check)
        registered.append("database")

    # Embedding backend — reports which backend is active (bge / tfidf_fallback).
    def _embedding_check() -> ComponentHealth:
        try:
            from app.services.embedding import (
                EMBEDDING_BACKEND_NAME,
                embedding_provider,
            )

            ok = embedding_provider.health_check()
            status = HealthStatus.HEALTHY if ok else HealthStatus.DEGRADED
            return ComponentHealth(
                name="embedding_backend",
                status=status,
                message=EMBEDDING_BACKEND_NAME
                if ok
                else f"{EMBEDDING_BACKEND_NAME} health_check failed",
                details={"backend": EMBEDDING_BACKEND_NAME},
            )
        except Exception as exc:
            return ComponentHealth(
                name="embedding_backend",
                status=HealthStatus.DEGRADED,
                message=str(exc),
            )

    health_checker.register("embedding_backend", _embedding_check)
    registered.append("embedding_backend")

    # LLM provider — simple reachability check (mock provider always healthy).
    def _llm_check() -> ComponentHealth:
        try:
            from app.core.config import settings as _s

            provider_name = _s.LLM_PROVIDER
            if provider_name == "mock":
                return ComponentHealth(
                    name="llm_provider",
                    status=HealthStatus.HEALTHY,
                    message="mock provider (no external dependency)",
                    details={"provider": provider_name},
                )
            # For real providers, check that the API key is set.
            has_key = bool(_s.LLM_API_KEY)
            return ComponentHealth(
                name="llm_provider",
                status=HealthStatus.HEALTHY if has_key else HealthStatus.DEGRADED,
                message=("api_key configured" if has_key else "LLM_API_KEY not set"),
                details={"provider": provider_name, "api_key_set": has_key},
            )
        except Exception as exc:
            return ComponentHealth(
                name="llm_provider",
                status=HealthStatus.DEGRADED,
                message=str(exc),
            )

    health_checker.register("llm_provider", _llm_check)
    registered.append("llm_provider")

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

    # P0.2 — Hard fail in production if the resolved LLM provider is the
    # mock. The mock provider returns templated, rule-based pseudo-answers
    # that are indistinguishable at a glance from real generated answers;
    # serving them in production would silently mislead users. Refuse to
    # start instead of degrading silently.
    if settings.ENV == "production" and settings.LLM_PROVIDER.strip().lower() == "mock":
        msg = (
            "Refusing to start: LLM_PROVIDER is 'mock' in a production "
            "environment. Set LLM_PROVIDER to a real provider "
            "(openai | gemini | litellm) with a valid LLM_API_KEY."
        )
        logger.error(msg)
        raise EnvironmentValidationError(msg)
    # Development convenience: create all tables if using SQLite
    if settings.ENV == "development" and settings.DATABASE_URL.startswith("sqlite"):
        try:
            from sqlalchemy import create_engine
            from app.models.document import Base

            sync_url = settings.DATABASE_URL.replace("+aiosqlite", "+pysqlite")
            sync_engine = create_engine(sync_url)
            Base.metadata.create_all(sync_engine)
            sync_engine.dispose()
            logger.info("Development mode: ensured all database tables exist")
        except Exception as exc:
            logger.warning("Could not auto-create tables: %s", exc)

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
    logger.info(
        "RegIntel-AI shutting down at %s", datetime.now(timezone.utc).isoformat()
    )


__all__ = [
    "EnvironmentValidationError",
    "StartupReport",
    "on_shutdown",
    "on_startup",
    "register_default_health_checks",
    "validate_environment",
    "validate_storage_root",
]
