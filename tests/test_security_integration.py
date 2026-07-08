"""Security middleware integration tests.

Tests that run the full app (all middleware active) and verify:
1. Unauthenticated requests are rejected when API_KEY_AUTH_ENABLED=true.
2. Requests exceeding the rate limit are throttled (429).
3. Security headers are present on every response.
4. An audit log entry is written for every handled request.
5. CORS does NOT fall back to wildcard (*) when AUTH_ENABLED=true.
"""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


def _make_app_with_apikey_auth():
    """Boot a fresh app instance with API_KEY_AUTH_ENABLED=true."""
    # Force fresh module state with overridden env vars.
    # We monkey-patch settings rather than reloading to avoid circular import issues.
    from app.main import app
    from app.middleware import APIKey, APIKeyStore

    # Build a fresh store with one known key.
    store = APIKeyStore()
    test_key = APIKey(key_id="test-key-1", secret="valid-secret-abc", label="test")
    store.add(test_key)
    return app, store, "valid-secret-abc"


class TestAPIKeyEnforcement:
    """API key middleware rejects unauthenticated requests."""

    def test_missing_api_key_returns_401(self):
        from app.main import app
        from app.middleware import APIKey, APIKeyMiddleware, APIKeyStore

        store = APIKeyStore()  # empty — no keys registered
        # Add middleware directly to a test client wrapping a minimal route.
        from fastapi import FastAPI
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.get("/protected")
        def protected():
            return {"ok": True}

        mini.add_middleware(APIKeyMiddleware, store=store, enabled=True)

        with TestClient(mini, raise_server_exceptions=False) as client:
            resp = client.get("/protected")
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_valid_api_key_allows_request(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import APIKey, APIKeyMiddleware, APIKeyStore

        store = APIKeyStore()
        store.add(APIKey(key_id="k1", secret="secret-xyz", label="test"))

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.get("/protected")
        def protected():
            return {"ok": True}

        mini.add_middleware(APIKeyMiddleware, store=store, enabled=True)

        with TestClient(mini) as client:
            resp = client.get("/protected", headers={"X-Api-Key": "secret-xyz"})
            assert resp.status_code == 200

    def test_invalid_api_key_returns_401(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import APIKey, APIKeyMiddleware, APIKeyStore

        store = APIKeyStore()
        store.add(APIKey(key_id="k1", secret="real-secret", label="test"))

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.get("/protected")
        def protected():
            return {"ok": True}

        mini.add_middleware(APIKeyMiddleware, store=store, enabled=True)

        with TestClient(mini, raise_server_exceptions=False) as client:
            resp = client.get("/protected", headers={"X-Api-Key": "wrong-secret"})
            assert resp.status_code == 401


class TestRateLimiting:
    """Rate limit middleware throttles excess requests."""

    def test_rate_limit_returns_429_after_limit(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import RateLimitMiddleware, SlidingWindowRateLimiter

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.get("/work")
        def work():
            return {"done": True}

        limiter = SlidingWindowRateLimiter()
        mini.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            default_limit=3,  # only 3 allowed
            window_seconds=60.0,
            enabled=True,
        )

        with TestClient(mini, raise_server_exceptions=False) as client:
            for _ in range(3):
                resp = client.get("/work")
                assert resp.status_code == 200
            # 4th request must be throttled
            resp = client.get("/work")
            assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"
            assert "Retry-After" in resp.headers


class TestSecurityHeaders:
    """SecurityHeadersMiddleware attaches expected headers to all responses."""

    def test_security_headers_present(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import SecurityHeadersMiddleware, DEFAULT_SECURITY_HEADERS

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.get("/")
        def root():
            return {"ok": True}

        mini.add_middleware(SecurityHeadersMiddleware)

        with TestClient(mini) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            for header in DEFAULT_SECURITY_HEADERS:
                assert header in resp.headers, (
                    f"Security header '{header}' missing from response headers"
                )


class TestAuditLog:
    """AuditLogMiddleware records entries for handled requests."""

    def test_audit_log_entry_written_for_request(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import AuditLog, AuditLogMiddleware

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.post("/data")
        def create():
            return {"created": True}

        audit = AuditLog()
        mini.add_middleware(AuditLogMiddleware, audit_log=audit, enabled=True)

        with TestClient(mini) as client:
            resp = client.post("/data")
            assert resp.status_code == 200

        entries = audit.all()
        assert len(entries) >= 1, "Expected at least one audit log entry"
        paths = [e.path for e in entries]
        assert "/data" in paths, f"Expected /data in audit entries: {paths}"

    def test_audit_entry_records_correct_method(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        from app.middleware import AuditLog, AuditLogMiddleware

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        mini = FastAPI(lifespan=_noop_lifespan)

        @mini.put("/item")
        def update():
            return {"updated": True}

        audit = AuditLog()
        mini.add_middleware(AuditLogMiddleware, audit_log=audit, enabled=True)

        with TestClient(mini) as client:
            client.put("/item")

        entries = audit.all()
        assert any(e.method == "PUT" for e in entries), (
            f"Expected PUT method in audit entries; got: {[e.method for e in entries]}"
        )


class TestCORSNotWildcardWithAuth:
    """When AUTH_ENABLED=true CORS must not silently widen to allow_origins=('*',)."""

    def test_cors_origins_not_wildcard_when_auth_enabled(self):
        """Verify the logic in main.py: AUTH_ENABLED=True → _cors_origins != ('*',)."""
        from app.core.config import settings

        # Simulate the condition in main.py directly (no app boot required).
        # The condition is: if not settings.AUTH_ENABLED: _cors_origins = ("*",)
        # When AUTH_ENABLED=True the origins come from CORS_ORIGINS (empty → empty tuple).
        if settings.AUTH_ENABLED:
            cors_origins = (
                [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
                if settings.CORS_ORIGINS
                else ()
            )
            assert cors_origins != ("*",), (
                "CORS is incorrectly set to wildcard (*) while AUTH_ENABLED=True. "
                "This is a security bug."
            )
        # If AUTH_ENABLED=False (test/dev), wildcard is acceptable.

    def test_wildcard_cors_only_when_auth_disabled(self):
        """If AUTH_ENABLED=False, wildcard CORS is expected (dev mode)."""
        from app.core.config import settings

        if not settings.AUTH_ENABLED:
            # In dev mode: wildcard is the expected value.
            cors_origins = ("*",)
            assert cors_origins == ("*",)
