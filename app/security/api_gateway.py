"""API gateway security (M10.6).

Provides:

* :class:`CORSConfig` / :func:`cors_headers_for` — strict-by-default CORS
  responses that only allow the configured origins.
* :class:`IPAllowList` — accept / deny / shadow lists of CIDR ranges.
* :class:`RequestSigner` — HMAC-SHA256 request signing and verification
  (timestamp + body + path bound).
* :class:`APIGateway` — convenience facade that composes the three
  above into a single, deterministic decision: ``allow / deny``.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)


# ─── CORS ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CORSConfig:
    """Strict-by-default CORS configuration.

    Defaults: no cross-origin access. Set ``allowed_origins`` explicitly
    to enable; credentials are disabled by default.
    """

    allowed_origins: Sequence[str] = ()
    allowed_methods: Sequence[str] = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
    allowed_headers: Sequence[str] = (
        "Authorization",
        "Content-Type",
        "X-Api-Key",
        "X-Request-ID",
    )
    expose_headers: Sequence[str] = (
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
    )
    allow_credentials: bool = False
    max_age_seconds: int = 600

    def headers_for(self, origin: Optional[str]) -> Dict[str, str]:
        """Return the CORS response headers for the given request origin."""
        if not origin or not self._origin_allowed(origin):
            return {}
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": ", ".join(self.allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self.allowed_headers),
            "Access-Control-Expose-Headers": ", ".join(self.expose_headers),
            "Access-Control-Max-Age": str(self.max_age_seconds),
        }
        if self.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
        return headers

    def _origin_allowed(self, origin: str) -> bool:
        for allowed in self.allowed_origins:
            if allowed == "*" and self.allow_credentials:
                return False  # never allow wildcard with credentials
            if allowed == origin or allowed == "*":
                return True
        return False


def cors_headers_for(origin: Optional[str], config: Optional[CORSConfig] = None) -> Dict[str, str]:
    """Convenience wrapper used by middleware."""
    return (config or CORSConfig()).headers_for(origin)


# ─── IP allow / deny lists ──────────────────────────────────────────


@dataclass
class IPAllowList:
    """Accept / deny list with simple CIDR matching.

    Decision order: ``denied`` → ``allowed`` → default ``default_allow``.
    """

    allowed: Set[str] = field(default_factory=set)
    denied: Set[str] = field(default_factory=set)
    default_allow: bool = True

    @classmethod
    def from_cidrs(
        cls,
        allowed_cidrs: Iterable[str] = (),
        denied_cidrs: Iterable[str] = (),
        default_allow: bool = True,
    ) -> "IPAllowList":
        allowed_networks = [_parse_cidr(c) for c in allowed_cidrs if c.strip()]
        denied_networks = [_parse_cidr(c) for c in denied_cidrs if c.strip()]
        return cls(allowed=set(allowed_networks), denied=set(denied_networks), default_allow=default_allow)

    def decide(self, ip: str) -> Tuple[bool, str]:
        """Return ``(allowed, reason)`` for the given client IP."""
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False, "invalid ip"

        for network in self.denied:
            if address in network:
                return False, f"denied by {network}"
        for network in self.allowed:
            if address in network:
                return True, f"allowed by {network}"
        return self.default_allow, "default policy"

    def is_allowed(self, ip: str) -> bool:
        return self.decide(ip)[0]


def _parse_cidr(value: str) -> Any:
    """Parse a CIDR or single IP into a network object.

    Single IPs are wrapped to /32 (v4) or /128 (v6) so that the ``in`` test
    works uniformly for both single addresses and CIDR ranges.
    """
    value = value.strip()
    if "/" in value:
        return ipaddress.ip_network(value, strict=False)
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv4Address):
        return ipaddress.ip_network(f"{value}/32", strict=False)
    return ipaddress.ip_network(f"{value}/128", strict=False)


# ─── Request signing (HMAC-SHA256) ──────────────────────────────────


class RequestSigner:
    """Issue and verify HMAC-SHA256 request signatures.

    The signed string is::

        METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + SHA256(BODY)

    The signature is ``base64url(HMAC(secret, signing_string))``. The
    timestamp guards against replay (default 5 minute window).
    """

    def __init__(self, secret: str, *, max_skew_seconds: int = 300) -> None:
        if not secret or len(secret) < 16:
            raise ValueError("RequestSigner requires a 16+ character secret")
        self._secret = secret.encode("utf-8")
        self._max_skew_seconds = max_skew_seconds

    def sign(
        self,
        method: str,
        path: str,
        body: bytes | str,
        *,
        timestamp: Optional[int] = None,
    ) -> Dict[str, str]:
        ts = int(timestamp if timestamp is not None else time.time())
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        signing_string = f"{method.upper()}\n{path}\n{ts}\n{body_hash}"
        digest = hmac.new(self._secret, signing_string.encode("utf-8"), hashlib.sha256).digest()
        import base64

        return {
            "X-Signature-Timestamp": str(ts),
            "X-Signature": base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
        }

    def verify(
        self,
        method: str,
        path: str,
        body: bytes | str,
        signature: str,
        timestamp: str,
        *,
        now: Optional[int] = None,
    ) -> Tuple[bool, str]:
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False, "bad timestamp"
        current = int(now if now is not None else time.time())
        if abs(current - ts) > self._max_skew_seconds:
            return False, "timestamp outside allowed window"
        expected = self.sign(method, path, body, timestamp=ts)
        if not hmac.compare_digest(expected["X-Signature"], signature):
            return False, "signature mismatch"
        return True, "ok"


# ─── APIGateway facade ──────────────────────────────────────────────


@dataclass
class APIGateway:
    """Composed decision: CORS + IP allow list + (optional) signing."""

    cors: CORSConfig = field(default_factory=CORSConfig)
    ip_allow: IPAllowList = field(default_factory=IPAllowList)
    signer: Optional[RequestSigner] = None
    require_signature_paths: Set[str] = field(default_factory=set)

    def cors_headers(self, origin: Optional[str]) -> Dict[str, str]:
        return self.cors.headers_for(origin)

    def check_ip(self, ip: Optional[str]) -> Tuple[bool, str]:
        if not ip:
            return False, "missing ip"
        return self.ip_allow.decide(ip)

    def check_request_signature(
        self,
        method: str,
        path: str,
        body: bytes,
        signature: Optional[str],
        timestamp: Optional[str],
    ) -> Tuple[bool, str]:
        if path not in self.require_signature_paths:
            return True, "signature not required"
        if not signature or not timestamp:
            return False, "missing signature"
        if self.signer is None:
            return False, "signer not configured"
        return self.signer.verify(method, path, body, signature, timestamp)

    def summary(self) -> Dict[str, Any]:
        return {
            "cors_origins": list(self.cors.allowed_origins),
            "ip_allow_count": len(self.ip_allow.allowed),
            "ip_deny_count": len(self.ip_allow.denied),
            "ip_default_allow": self.ip_allow.default_allow,
            "signature_required_paths": sorted(self.require_signature_paths),
            "signer_configured": self.signer is not None,
        }
