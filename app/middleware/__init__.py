"""Module 6.8 — Production middleware.

This package provides production-grade FastAPI middleware:

* :class:`SecurityHeadersMiddleware` — adds standard security headers
  to every response.
* :class:`RequestTracingMiddleware` — assigns / propagates an
  ``X-Request-ID`` for distributed tracing.
* :class:`RateLimitMiddleware` — sliding-window rate limiting keyed
  on the request ``X-Api-Key`` header (falls back to client IP).
* :class:`APIKeyMiddleware` — enforces presence + validity of an
  ``X-Api-Key`` header.
* :class:`AuditLogMiddleware` — records every request to a thread-
  safe in-memory audit log (and optionally a JSONL file).

The middleware classes are designed to be plug-and-play: each
implements the standard ASGI / Starlette ``BaseHTTPMiddleware``
interface and can be enabled / disabled independently.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# ─── Audit log ────────────────────────────────────────────────────────────


@dataclass
class AuditLogEntry:
    """A single audit-log record."""

    timestamp: datetime
    request_id: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    api_key_id: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """Thread-safe audit log (in-memory + optional JSONL)."""

    def __init__(self, *, persist_path: Optional[Path] = None, max_size: int = 10_000) -> None:
        self._entries: Deque[AuditLogEntry] = deque(maxlen=max_size)
        self._lock = threading.RLock()
        self._persist_path = persist_path

    def record(self, entry: AuditLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)
        if self._persist_path is not None:
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                with self._persist_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(_to_jsonable(entry)) + "\n")
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to persist audit log: %s", exc)

    def all(self) -> List[AuditLogEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _to_jsonable(entry: AuditLogEntry) -> Dict[str, Any]:
    return {
        "timestamp": entry.timestamp.isoformat(),
        "request_id": entry.request_id,
        "method": entry.method,
        "path": entry.path,
        "status_code": entry.status_code,
        "duration_ms": entry.duration_ms,
        "api_key_id": entry.api_key_id,
        "client_ip": entry.client_ip,
        "user_agent": entry.user_agent,
        "error": entry.error,
        "metadata": entry.metadata,
    }


# ─── API key store ────────────────────────────────────────────────────────


@dataclass
class APIKey:
    """An issued API key with quota and allowed-paths metadata."""

    key_id: str
    secret: str
    label: str = ""
    quota_per_minute: int = 60
    allowed_paths: Optional[Set[str]] = None  # None = all paths
    enabled: bool = True


class APIKeyStore:
    """In-memory API key store (thread-safe)."""

    def __init__(self) -> None:
        self._keys: Dict[str, APIKey] = {}
        self._lock = threading.RLock()

    def add(self, key: APIKey) -> None:
        with self._lock:
            self._keys[key.secret] = key

    def remove(self, secret: str) -> None:
        with self._lock:
            self._keys.pop(secret, None)

    def lookup(self, secret: str) -> Optional[APIKey]:
        with self._lock:
            return self._keys.get(secret)

    def all(self) -> List[APIKey]:
        with self._lock:
            return list(self._keys.values())

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()


# ─── Sliding window rate limiter ──────────────────────────────────────────


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter.

    Tracks per-identity timestamps in a deque and counts requests
    within the last ``window_seconds`` window.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.RLock()

    def allow(
        self, identity: str, *, limit: int, window_seconds: float
    ) -> Tuple[bool, int, float]:
        """Return ``(allowed, remaining, retry_after_seconds)``."""
        now = time.time()
        with self._lock:
            dq = self._hits.setdefault(identity, deque())
            cutoff = now - window_seconds
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = max(0.0, window_seconds - (now - dq[0]))
                return False, 0, retry_after
            dq.append(now)
            return True, limit - len(dq), 0.0

    def reset(self, identity: Optional[str] = None) -> None:
        with self._lock:
            if identity is None:
                self._hits.clear()
            else:
                self._hits.pop(identity, None)


# ─── Security headers middleware ──────────────────────────────────────────


DEFAULT_SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds the standard set of security headers to every response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(app)
        self.headers = dict(headers or DEFAULT_SECURITY_HEADERS)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for k, v in self.headers.items():
            response.headers[k] = v
        return response


# ─── Request tracing middleware ───────────────────────────────────────────


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Assigns / propagates ``X-Request-ID`` and exposes it on
    ``request.state.request_id``."""

    HEADER = "X-Request-ID"

    def __init__(self, app: ASGIApp, *, header: str = HEADER) -> None:
        super().__init__(app)
        self.header = header

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get(self.header) or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[self.header] = rid
        return response


# ─── API key middleware ──────────────────────────────────────────────────


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates ``X-Api-Key`` against the :class:`APIKeyStore`.

    Endpoints listed in ``exempt_paths`` (e.g. ``/health``, ``/docs``)
    are not subject to API key enforcement.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: APIKeyStore,
        header: str = "X-Api-Key",
        exempt_paths: Optional[Set[str]] = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.store = store
        self.header = header
        self.exempt_paths = set(exempt_paths or {"/", "/health", "/docs", "/openapi.json", "/redoc"})
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if not self.enabled or request.url.path in self.exempt_paths:
            return await call_next(request)
        secret = request.headers.get(self.header)
        if not secret:
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"detail": f"missing {self.header} header"},
                status_code=401,
            )
        key = self.store.lookup(secret)
        if key is None or not key.enabled:
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"detail": "invalid API key"},
                status_code=401,
            )
        if key.allowed_paths and not any(
            request.url.path.startswith(p) for p in key.allowed_paths
        ):
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"detail": "API key not authorized for this path"},
                status_code=403,
            )
        request.state.api_key = key
        return await call_next(request)


# ─── Rate-limit middleware ────────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limit per identity (API key id, else IP)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: Optional[SlidingWindowRateLimiter] = None,
        default_limit: int = 60,
        window_seconds: float = 60.0,
        exempt_paths: Optional[Set[str]] = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowRateLimiter()
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.exempt_paths = set(exempt_paths or {"/", "/health", "/docs", "/openapi.json", "/redoc"})
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if not self.enabled or request.url.path in self.exempt_paths:
            return await call_next(request)
        # Identity: API key id if present, else client IP.
        key = getattr(request.state, "api_key", None)
        if key is not None:
            identity = f"key:{key.key_id}"
            limit = key.quota_per_minute
        else:
            client = request.client
            identity = f"ip:{client.host if client else 'unknown'}"
            limit = self.default_limit
        allowed, remaining, retry_after = self.limiter.allow(
            identity, limit=limit, window_seconds=self.window_seconds
        )
        if not allowed:
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={
                    "Retry-After": str(int(retry_after) + 1),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# ─── Audit log middleware ────────────────────────────────────────────────


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Records every request to an :class:`AuditLog`."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        audit_log: AuditLog,
        exempt_paths: Optional[Set[str]] = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.audit_log = audit_log
        self.exempt_paths = set(exempt_paths or set())
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if not self.enabled or request.url.path in self.exempt_paths:
            return await call_next(request)
        start = time.perf_counter()
        error: Optional[str] = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:  # pragma: no cover
            error = str(exc)
            raise
        finally:
            duration = (time.perf_counter() - start) * 1000.0
            key = getattr(request.state, "api_key", None)
            client = request.client
            self.audit_log.record(
                AuditLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    request_id=getattr(request.state, "request_id", uuid.uuid4().hex),
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=duration,
                    api_key_id=key.key_id if key else None,
                    client_ip=client.host if client else None,
                    user_agent=request.headers.get("user-agent"),
                    error=error,
                )
            )


__all__ = [
    "APIKey",
    "APIKeyMiddleware",
    "APIKeyStore",
    "AuditLog",
    "AuditLogEntry",
    "AuditLogMiddleware",
    "DEFAULT_SECURITY_HEADERS",
    "RateLimitMiddleware",
    "RequestTracingMiddleware",
    "SecurityHeadersMiddleware",
    "SlidingWindowRateLimiter",
]
