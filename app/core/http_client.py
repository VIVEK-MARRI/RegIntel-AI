"""Shared async HTTP client used by Milestone 7 monitoring adapters.

This is the first HTTP client in the codebase. The adapters for the
regulatory authorities (RBI, SEBI, IRDAI, PFRDA, MoF) all go through
:class:`HTTPClient` so that:

* timeouts, retries, and headers are uniform,
* tests can monkey-patch a single seam,
* the client lifecycle is owned by the application (closed on shutdown).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class HTTPClientConfig:
    """Static configuration for :class:`HTTPClient`."""

    timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_factor: float = 0.5
    user_agent: str = (
        "RegIntel-AI/7.0 (+https://regintel.example.com) monitoring-bot"
    )
    follow_redirects: bool = True
    verify_ssl: bool = True
    default_headers: Dict[str, str] = field(default_factory=dict)


class HTTPClient:
    """Thin async HTTP wrapper with retry, timeout, and structured logging."""

    def __init__(
        self,
        config: Optional[HTTPClientConfig] = None,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._config = config or HTTPClientConfig()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            follow_redirects=self._config.follow_redirects,
            verify=self._config.verify_ssl,
            headers={
                "User-Agent": self._config.user_agent,
                **self._config.default_headers,
            },
        )

    @property
    def config(self) -> HTTPClientConfig:
        return self._config

    @property
    def raw(self) -> httpx.AsyncClient:
        return self._client

    async def get(
        self, url: str, *, params: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        return await self._request("GET", url, params=params)

    async def head(self, url: str) -> httpx.Response:
        return await self._request("HEAD", url)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                logger.debug(
                    "http_request",
                    extra={"method": method, "url": url, "attempt": attempt},
                )
                response = await self._client.request(
                    method, url, params=params
                )
                response.raise_for_status()
                return response
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
            ) as exc:
                last_exc = exc
                if attempt >= self._config.max_retries:
                    break
                sleep_for = self._config.backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "http_retry",
                    extra={
                        "method": method,
                        "url": url,
                        "attempt": attempt,
                        "sleep_for": sleep_for,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(sleep_for)
        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def build_default_http_client() -> HTTPClient:
    """Factory: production-default HTTP client."""
    return HTTPClient()


__all__ = [
    "HTTPClient",
    "HTTPClientConfig",
    "build_default_http_client",
]
