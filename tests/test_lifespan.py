"""Integration test: lifespan startup and shutdown hooks fire correctly.

Verifies that:
1. The FastAPI lifespan context manager runs startup (health checks registered).
2. The lifespan context manager runs shutdown (no unhandled errors).
3. The /health/live endpoint returns 200 after boot.
4. The /health/ready endpoint includes the embedding_backend component.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_startup_registers_health_checks():
    """Startup must register at least the liveness check in the health checker."""
    from app.main import app
    from app.api.v1.health import get_health_checker

    with TestClient(app) as client:
        checker = get_health_checker()
        registered = list(checker.checks().keys())
        assert "liveness" in registered, (
            f"Expected 'liveness' check to be registered after startup; got: {registered}"
        )


def test_liveness_endpoint_returns_200():
    """GET /health/live must return 200 with status:alive after startup."""
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "alive", f"Unexpected body: {body}"


def test_readiness_endpoint_includes_embedding_backend():
    """/health/ready must include an embedding_backend component."""
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/health/ready")
        assert resp.status_code in (200, 503), f"Unexpected status: {resp.status_code}"
        body = resp.json()
        component_names = [c["name"] for c in body.get("components", [])]
        assert "embedding_backend" in component_names, (
            f"embedding_backend missing from /health/ready components: {component_names}"
        )


def test_shutdown_hook_does_not_raise():
    """Shutdown hook must complete without raising exceptions."""
    from app.main import app

    # TestClient's context manager calls lifespan exit (shutdown).
    # If it raises, the test fails naturally.
    with TestClient(app) as client:
        resp = client.get("/health/live")
        assert resp.status_code == 200
    # If we reach here, shutdown completed without error.


def test_embedding_backend_name_in_readiness_details():
    """/health/ready must expose embedding backend name in component details."""
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/health/ready")
        body = resp.json()
        components = {c["name"]: c for c in body.get("components", [])}
        if "embedding_backend" in components:
            details = components["embedding_backend"].get("details", {})
            assert "backend" in details, (
                f"embedding_backend component missing 'backend' key in details: {details}"
            )
            backend_name = details["backend"]
            assert backend_name in ("bge", "tfidf_fallback"), (
                f"Unexpected backend name: {backend_name!r}"
            )
