"""JWT authentication (M10.6).

A minimal, dependency-free HS256 implementation of RFC 7519.

Tokens carry:

* ``sub``     — principal id (user / service account)
* ``roles``   — list of role names (consumed by :mod:`app.security.rbac`)
* ``scopes``  — list of permission scopes
* ``iat``     — issued-at (Unix seconds)
* ``exp``     — expiry (Unix seconds)
* ``iss``     — issuer (``"regintel-ai"``)
* ``aud``     — audience (defaults to ``"regintel-api"``)
* ``jti``     — unique token id (for revocation / replay tracking)

Example
-------
>>> from app.security import JWTIssuer, JWTConfig
>>> issuer = JWTIssuer(JWTConfig(secret="x" * 32))
>>> pair = issuer.issue("alice", roles=["admin"])
>>> pair.access_token[:20]
'eyJhbGciOiJIUzI1NiI...'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

# ─── Encoding helpers ────────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _json_canonical(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


# ─── Errors ──────────────────────────────────────────────────────────


class JWTError(Exception):
    """Base class for all JWT errors."""


class JWTExpiredError(JWTError):
    """Raised when the token has expired."""


class JWTInvalidSignatureError(JWTError):
    """Raised when the signature does not match."""


class JWTMalformedError(JWTError):
    """Raised when the token is malformed."""


class JWTConfigurationError(JWTError):
    """Raised when the issuer is misconfigured (e.g. weak secret)."""


# ─── Config ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JWTConfig:
    """Configuration for a :class:`JWTIssuer`."""

    secret: str
    issuer: str = "regintel-ai"
    audience: str = "regintel-api"
    algorithm: str = "HS256"
    access_ttl_seconds: int = 900  # 15 min default
    refresh_ttl_seconds: int = 7 * 24 * 3600  # 7 days
    clock_skew_seconds: int = 30
    leeway_seconds: int = 5  # for backward compat with older leeway parameter
    min_secret_length: int = 32

    def __post_init__(self) -> None:
        if not self.secret or len(self.secret) < self.min_secret_length:
            raise JWTConfigurationError(
                f"JWT secret must be at least {self.min_secret_length} characters"
            )
        if self.algorithm != "HS256":
            raise JWTConfigurationError(
                f"Only HS256 is supported in this build, got {self.algorithm}"
            )
        if self.access_ttl_seconds < 60:
            raise JWTConfigurationError("access_ttl_seconds must be >= 60")


# ─── Principal + token pair ──────────────────────────────────────────


@dataclass(frozen=True)
class JWTPrincipal:
    """The resolved caller of an authenticated request."""

    sub: str
    roles: Tuple[str, ...] = ()
    scopes: Tuple[str, ...] = ()
    raw_claims: Mapping[str, Any] = field(default_factory=dict)
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def to_claims(self) -> Dict[str, Any]:
        return {
            "sub": self.sub,
            "roles": list(self.roles),
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class TokenPair:
    """An access token plus a refresh token (both JWTs)."""

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "Bearer"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": int(
                (self.access_expires_at - datetime.now(timezone.utc)).total_seconds()
            ),
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
        }


# ─── Issuer ──────────────────────────────────────────────────────────


class JWTIssuer:
    """Issue, sign, and verify HS256 JWTs."""

    def __init__(self, config: JWTConfig) -> None:
        self.config = config

    # ─── Issue ─────────────────────────────────────────────────────

    def issue(
        self,
        subject: str,
        *,
        roles: Iterable[str] = (),
        scopes: Iterable[str] = (),
        ttl_seconds: Optional[int] = None,
        extra_claims: Optional[Mapping[str, Any]] = None,
        access_ttl: Optional[int] = None,
        refresh_ttl: Optional[int] = None,
    ) -> TokenPair:
        """Return a fresh :class:`TokenPair` for ``subject``."""
        access_ttl = (
            access_ttl
            if access_ttl is not None
            else (ttl_seconds or self.config.access_ttl_seconds)
        )
        refresh_ttl = (
            refresh_ttl if refresh_ttl is not None else self.config.refresh_ttl_seconds
        )

        now = int(time.time())
        access_exp = now + access_ttl
        refresh_exp = now + refresh_ttl

        access_claims: Dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": subject,
            "iat": now,
            "exp": access_exp,
            "jti": uuid.uuid4().hex,
            "token_use": "access",
            "roles": list(roles),
            "scopes": list(scopes),
        }
        refresh_claims: Dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": subject,
            "iat": now,
            "exp": refresh_exp,
            "jti": uuid.uuid4().hex,
            "token_use": "refresh",
            # Carry roles + scopes through so a refresh can mint a new access
            # token with the same authorization. Both are still bound to the
            # HS256 signature; rotation happens on every refresh.
            "roles": list(roles),
            "scopes": list(scopes),
        }
        if extra_claims:
            for k, v in extra_claims.items():
                if k in access_claims:
                    continue
                access_claims[k] = v

        return TokenPair(
            access_token=self._encode(access_claims),
            refresh_token=self._encode(refresh_claims),
            access_expires_at=_epoch_to_dt(access_exp),
            refresh_expires_at=_epoch_to_dt(refresh_exp),
        )

    # ─── Encode / Decode ───────────────────────────────────────────

    def _encode(self, claims: Mapping[str, Any]) -> str:
        header = {"alg": self.config.algorithm, "typ": "JWT"}
        signing_input = (
            _b64url(_json_canonical(header))
            + "."
            + _b64url(_json_canonical(dict(claims)))
        )
        signature = hmac.new(
            self.config.secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return signing_input + "." + _b64url(signature)

    def verify(
        self, token: str, *, expected_audience: Optional[str] = None
    ) -> JWTPrincipal:
        return decode_jwt(
            token,
            secret=self.config.secret,
            algorithm=self.config.algorithm,
            issuer=self.config.issuer,
            audience=expected_audience or self.config.audience,
            leeway=self.config.leeway_seconds,
            clock_skew=self.config.clock_skew_seconds,
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        """Exchange a refresh token for a fresh :class:`TokenPair`."""
        principal = self.verify(refresh_token)
        if principal.raw_claims.get("token_use") != "refresh":
            raise JWTError("not a refresh token")
        return self.issue(
            principal.sub,
            roles=principal.roles,
            scopes=principal.scopes,
        )


# ─── Module-level decoder ────────────────────────────────────────────


def decode_jwt(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    leeway: int = 0,
    clock_skew: int = 0,
) -> JWTPrincipal:
    """Decode and verify a JWT, returning a :class:`JWTPrincipal`.

    Raises:
        JWTMalformedError: token is not a well-formed JWT.
        JWTInvalidSignatureError: signature does not match.
        JWTExpiredError: token has expired (with leeway).
    """
    if not token or not isinstance(token, str):
        raise JWTMalformedError("token must be a non-empty string")
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTMalformedError("JWT must have three dot-separated sections")

    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        signature = _b64url_decode(parts[2])
    except (ValueError, json.JSONDecodeError) as exc:
        raise JWTMalformedError("JWT contains invalid base64 / JSON") from exc

    if header.get("alg") != algorithm:
        raise JWTInvalidSignatureError(f"unexpected alg: {header.get('alg')!r}")

    signing_input = (parts[0] + "." + parts[1]).encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise JWTInvalidSignatureError("signature mismatch")

    now = int(time.time())
    skew = max(leeway, clock_skew)
    if "exp" in payload and int(payload["exp"]) + skew < now:
        raise JWTExpiredError("token expired")
    if "nbf" in payload and int(payload["nbf"]) - skew > now:
        raise JWTError("token not yet valid")
    if issuer is not None and payload.get("iss") != issuer:
        raise JWTError(f"unexpected issuer: {payload.get('iss')!r}")
    if audience is not None:
        aud = payload.get("aud")
        if isinstance(aud, str):
            ok = aud == audience
        elif isinstance(aud, list):
            ok = audience in aud
        else:
            ok = False
        if not ok:
            raise JWTError(f"unexpected audience: {aud!r}")

    sub = str(payload.get("sub", ""))
    roles = tuple(str(r) for r in payload.get("roles", ()) or ())
    scopes = tuple(str(s) for s in payload.get("scopes", ()) or ())
    issued_at = _epoch_to_dt(int(payload["iat"])) if "iat" in payload else None
    expires_at = _epoch_to_dt(int(payload["exp"])) if "exp" in payload else None
    return JWTPrincipal(
        sub=sub,
        roles=roles,
        scopes=scopes,
        raw_claims=dict(payload),
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _epoch_to_dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def generate_development_secret() -> str:
    """Generate a strong, random secret suitable for development use."""
    return secrets.token_urlsafe(48)
