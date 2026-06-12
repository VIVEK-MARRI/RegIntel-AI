"""FastAPI security routes (M10.6).

All endpoints are namespaced under ``/api/v1/security``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.security.audit_review import (
    AuditQuery,
    AuditReview,
    get_audit_review,
)
from app.security.jwt_auth import (
    JWTConfig,
    JWTIssuer,
    decode_jwt,
    generate_development_secret,
)
from app.security.monitoring import (
    SecurityMonitor,
    get_security_monitor,
)
from app.core.config import settings
from app.security.rbac import Permission, Principal, Role
from app.security.secrets import SecretsManager, get_secrets_manager
from app.security.threat_detection import ThreatDetector, get_threat_detector

# ─── Account lockout tracker ───────────────────────────────────────
_lockout_lock = threading.Lock()
_lockout_attempts: Dict[str, int] = {}
_lockout_until: Dict[str, float] = {}
_LOCKOUT_MAX = 5
_LOCKOUT_DURATION = 300.0


def _check_lockout(identity: str) -> None:
    with _lockout_lock:
        until = _lockout_until.get(identity)
        if until is not None and time.time() < until:
            remaining = int(until - time.time())
            raise HTTPException(
                status_code=429,
                detail=f"account temporarily locked out; retry in {remaining}s",
            )


def _record_failure(identity: str) -> None:
    import os
    max_attempts = int(os.environ.get("AUTH_MAX_FAILED_ATTEMPTS", str(_LOCKOUT_MAX)))
    duration = int(float(os.environ.get("AUTH_LOCKOUT_DURATION_SECONDS", str(_LOCKOUT_DURATION))))
    if max_attempts <= 0:
        return
    with _lockout_lock:
        _lockout_attempts[identity] = _lockout_attempts.get(identity, 0) + 1
        if _lockout_attempts[identity] >= max_attempts:
            _lockout_until[identity] = time.time() + duration


def _reset_lockout(identity: str) -> None:
    with _lockout_lock:
        _lockout_attempts.pop(identity, None)
        _lockout_until.pop(identity, None)


# ─── Refresh token revocation ─────────────────────────────────────
_revoked_refresh_tokens: Set[str] = set()
_revocation_lock = threading.Lock()


def _revoke_refresh_token(jti: str) -> None:
    with _revocation_lock:
        _revoked_refresh_tokens.add(jti)


def _is_refresh_token_revoked(jti: str) -> bool:
    with _revocation_lock:
        return jti in _revoked_refresh_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["security"])


# ─── Schemas ────────────────────────────────────────────────────────


class TokenRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=128)
    roles: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default_factory=list)
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=24 * 3600)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    access_expires_at: str
    refresh_expires_at: str


class AuditReviewRequest(BaseModel):
    request_id: str
    status: str = Field(..., pattern="^(pending|approved|rejected)$")
    notes: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    access_expires_at: str
    refresh_expires_at: str
    user: Dict[str, Any]


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=300)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=200)
    username: str = Field(default="", max_length=120)


class SignupResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    access_expires_at: str
    refresh_expires_at: str
    user: Dict[str, Any]


# ─── Helpers ────────────────────────────────────────────────────────


def _demo_principal() -> Principal:
    """Return a full-access demo principal used when AUTH_ENABLED=False."""
    return Principal(
        subject_id="demo-user",
        email="demo@regintel.ai",
        username="demo",
        full_name="Demo User",
        roles={Role.ADMIN, Role.ANALYST, Role.OPERATOR, Role.AUDITOR, Role.ADMIN},
    )

def _principal_from_request(request: Request) -> Optional[Principal]:
    """Best-effort principal resolution from a JWT in the Authorization header."""
    if not settings.AUTH_ENABLED:
        return _demo_principal()
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    from app.main import _security_jwt_issuer  # type: ignore[attr-defined]
    try:
        jwt_principal = _security_jwt_issuer.verify(token)
    except Exception:
        return None
    return Principal.from_jwt(jwt_principal)


# ─── Health ────────────────────────────────────────────────────────


@router.get("/health", summary="Security platform health")
async def health() -> Dict[str, Any]:
    monitor = get_security_monitor()
    return {
        "status": "healthy",
        "module": "security",
        "version": "1.0.0",
        "dashboard": monitor.dashboard(),
    }


# ─── Auth ───────────────────────────────────────────────────────────


@router.post(
    "/auth/signup",
    response_model=SignupResponse,
    status_code=201,
    summary="Register a new user account",
)
async def signup(body: SignupRequest) -> SignupResponse:
    """Create a new user account and return JWT tokens."""
    if not settings.AUTH_ENABLED:
        resp = _demo_login_response()
        return SignupResponse(
            access_token=resp.access_token,
            refresh_token=resp.refresh_token,
            token_type=resp.token_type,
            expires_in=resp.expires_in,
            access_expires_at=resp.access_expires_at,
            refresh_expires_at=resp.refresh_expires_at,
            user=resp.user,
        )

    from app.main import _security_jwt_issuer
    from app.services.admin import build_default_admin_service
    from app.schemas.admin import UserCreateRequest

    svc = build_default_admin_service()

    if svc.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="email already registered")

    username = body.username or body.email.split("@")[0]
    full_name = body.full_name or username

    req = UserCreateRequest(
        username=username,
        email=body.email,
        password=body.password,
        full_name=full_name,
    )
    try:
        user = svc.create_user(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rbac_roles = ["viewer"]
    pair = _security_jwt_issuer.issue(
        user.user_id,
        roles=rbac_roles,
        scopes=[],
    )

    return SignupResponse(
        **pair.to_dict(),
        user={
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "roles": [],
            "rbac_roles": rbac_roles,
        },
    )


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="Authenticate with email and password",
)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate a user by email and password. Returns JWT tokens and user info."""
    if not settings.AUTH_ENABLED:
        return _demo_login_response()

    from app.main import _security_jwt_issuer
    from app.services.admin import build_default_admin_service
    from app.services.admin import _verify_password

    identity = f"login:{body.email}"
    _check_lockout(identity)

    svc = build_default_admin_service()
    user = svc.get_user_by_email(body.email)

    if user is None:
        _record_failure(identity)
        raise HTTPException(status_code=401, detail="invalid email or password")

    if user.status.value != "active":
        _record_failure(identity)
        raise HTTPException(status_code=401, detail="account is not active")

    if not _verify_password(body.password, user.password_hash):
        _record_failure(identity)
        raise HTTPException(status_code=401, detail="invalid email or password")

    _reset_lockout(identity)

    role_names = []
    for rid in user.role_ids:
        role = svc.get_role(rid)
        if role:
            role_names.append(role.name)

    rbac_roles = []
    for r in role_names:
        if r == "admin":
            rbac_roles.append("admin")
        elif r in ("compliance_officer", "risk_manager", "reviewer", "analyst"):
            rbac_roles.append("analyst")
        elif r == "auditor":
            rbac_roles.append("auditor")
        else:
            rbac_roles.append("viewer")

    if not rbac_roles:
        rbac_roles = ["viewer"]

    pair = _security_jwt_issuer.issue(
        user.user_id,
        roles=rbac_roles,
        scopes=[],
    )

    user.last_login_at = time.time()
    svc.user_management._store.update_user(user)

    return LoginResponse(
        **pair.to_dict(),
        user={
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "roles": role_names,
            "rbac_roles": rbac_roles,
        },
    )


def _demo_login_response() -> LoginResponse:
    """Return a fake admin login response used when AUTH_ENABLED=False."""
    from app.main import _security_jwt_issuer
    pair = _security_jwt_issuer.issue(
        "demo-user",
        roles=["admin", "analyst", "operator", "auditor"],
        scopes=[],
    )
    return LoginResponse(
        **pair.to_dict(),
        user={
            "user_id": "demo-user",
            "username": "demo",
            "email": "demo@regintel.ai",
            "full_name": "Demo User",
            "roles": ["admin", "analyst", "operator", "auditor"],
            "rbac_roles": ["admin", "analyst", "operator", "auditor"],
        },
    )


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="Issue a JWT access/refresh pair (dev only — disable in production)",
)
async def issue_token(request: TokenRequest) -> TokenResponse:
    """Issue a JWT pair for the given subject.

    In production this endpoint MUST be disabled or replaced with a
    proper identity provider integration. The default configuration
    requires ``SECURITY_DEV_TOKEN_ENDPOINT=true`` to be active.
    """
    import os

    if os.environ.get("SECURITY_DEV_TOKEN_ENDPOINT", "true").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="endpoint disabled")

    from app.main import _security_jwt_issuer  # type: ignore[attr-defined]
    pair = _security_jwt_issuer.issue(
        request.subject,
        roles=request.roles,
        scopes=request.scopes,
        ttl_seconds=request.ttl_seconds,
    )
    return TokenResponse(**pair.to_dict())


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new access/refresh pair",
)
async def refresh_token(body: Dict[str, str]) -> TokenResponse:
    refresh = body.get("refresh_token", "")
    if not refresh:
        if not settings.AUTH_ENABLED:
            resp = _demo_login_response()
            return TokenResponse(
                access_token=resp.access_token,
                refresh_token=resp.refresh_token,
                token_type=resp.token_type,
                expires_in=resp.expires_in,
                access_expires_at=resp.access_expires_at,
                refresh_expires_at=resp.refresh_expires_at,
            )
        raise HTTPException(status_code=400, detail="missing refresh_token")
    from app.main import _security_jwt_issuer  # type: ignore[attr-defined]
    try:
        principal = _security_jwt_issuer.verify(refresh)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"refresh failed: {exc}") from exc
    if principal.raw_claims.get("token_use") != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")
    jti = principal.raw_claims.get("jti", "")
    if jti and _is_refresh_token_revoked(jti):
        raise HTTPException(status_code=401, detail="refresh token revoked")
    _revoke_refresh_token(jti)
    try:
        pair = _security_jwt_issuer.refresh(refresh)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"refresh failed: {exc}") from exc
    return TokenResponse(**pair.to_dict())


@router.get(
    "/auth/me",
    summary="Inspect the current principal",
)
async def me(principal: Optional[Principal] = Depends(_principal_from_request)) -> Dict[str, Any]:
    if principal is None:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
    return {
        "subject_id": principal.subject_id,
        "roles": [r.value for r in principal.roles],
        "scopes": [p.value for p in principal.scopes],
        "permissions": [p.value for p in sorted(principal.permissions(), key=lambda x: x.value)],
    }


# ─── Roles & permissions ────────────────────────────────────────────


@router.get(
    "/roles",
    summary="List built-in roles and their permission grants",
)
async def list_roles() -> Dict[str, Any]:
    from app.security.rbac import role_permissions
    out = {}
    for role in Role:
        out[role.value] = sorted(p.value for p in role_permissions(role))
    return {"roles": out, "permissions": sorted(p.value for p in Permission)}


@router.get(
    "/api-gateway/summary",
    summary="Describe the active API gateway configuration",
)
async def api_gateway_summary() -> Dict[str, Any]:
    from app.main import _api_gateway  # type: ignore[attr-defined]
    return _api_gateway.summary()


# ─── Secrets ───────────────────────────────────────────────────────


@router.get(
    "/secrets",
    summary="Diagnostics for the secrets manager (never returns values)",
)
async def secrets_diag() -> Dict[str, Any]:
    return get_secrets_manager().diagnostics()


@router.get(
    "/secrets/list",
    summary="List known secret names (never values)",
)
async def secrets_list() -> Dict[str, Any]:
    manager = get_secrets_manager()
    return {
        "known": list(manager.list_known()),
        "diagnostics": manager.diagnostics(),
    }


# ─── Audit review ──────────────────────────────────────────────────


@router.get(
    "/audit/records",
    summary="List audit records (filterable, paginated)",
)
async def audit_records(
    method: Optional[str] = None,
    path_prefix: Optional[str] = None,
    status_code: Optional[int] = None,
    status_min: Optional[int] = None,
    status_max: Optional[int] = None,
    api_key_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    review_status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    review = get_audit_review()
    query = AuditQuery(
        method=method,
        path_prefix=path_prefix,
        status_code=status_code,
        status_min=status_min,
        status_max=status_max,
        api_key_id=api_key_id,
        client_ip=client_ip,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    records = review.records(query)
    return {
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "records": [r.to_dict() for r in records],
        "review_summary": review.review_summary(),
    }


@router.post(
    "/audit/review",
    summary="Mark an audit record as pending/approved/rejected",
)
async def audit_review(
    body: AuditReviewRequest,
    request: Request,
) -> Dict[str, Any]:
    review = get_audit_review()
    principal = _principal_from_request(request)
    reviewer = principal.subject_id if principal else "system"
    try:
        record = review.mark(
            body.request_id,
            status=body.status,
            reviewer=reviewer,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="audit record not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"record": record.to_dict()}


@router.get(
    "/audit/export",
    summary="Export audit records (jsonl or csv)",
)
async def audit_export(
    format: str = Query(default="jsonl", pattern="^(jsonl|csv)$"),
    status_min: Optional[int] = None,
    status_max: Optional[int] = None,
) -> JSONResponse:
    review = get_audit_review()
    query = AuditQuery(status_min=status_min, status_max=status_max, limit=1000)
    if format == "jsonl":
        text = review.export_jsonl(query)
        return JSONResponse(
            content={"format": "jsonl", "text": text, "count": text.count("\n")},
        )
    text = review.export_csv(query)
    return JSONResponse(content={"format": "csv", "text": text, "count": text.count("\n")})


# ─── Threats ──────────────────────────────────────────────────────


@router.get(
    "/threats/recent",
    summary="List recent threat events",
)
async def threats_recent(limit: int = Query(default=50, ge=1, le=500)) -> Dict[str, Any]:
    detector = get_threat_detector()
    return {
        "stats": detector.stats(),
        "events": [e.to_dict() for e in detector.recent_events(limit)],
    }


@router.post(
    "/threats/inspect",
    summary="Run threat detection against a synthetic request",
)
async def threats_inspect(body: Dict[str, Any]) -> Dict[str, Any]:
    detector = get_threat_detector()
    events = detector.inspect_request(
        identity=str(body.get("identity", "anon")),
        method=str(body.get("method", "GET")),
        path=str(body.get("path", "/")),
        body_size=int(body.get("body_size", 0)),
        headers=dict(body.get("headers", {}) or {}),
    )
    return {"events": [e.to_dict() for e in events]}


# ─── Monitoring dashboard ──────────────────────────────────────────


@router.get(
    "/monitoring/dashboard",
    summary="Aggregate security dashboard",
)
async def monitoring_dashboard() -> Dict[str, Any]:
    return get_security_monitor().dashboard()


# ─── Self-check ────────────────────────────────────────────────────


@router.get(
    "/selftest",
    summary="Run a smoke test of the security primitives",
)
async def selftest() -> Dict[str, Any]:
    """Returns a small report of the in-process primitives — used by CI."""
    from app.main import _security_jwt_issuer  # type: ignore[attr-defined]

    issue_ok = False
    decode_ok = False
    try:
        pair = _security_jwt_issuer.issue("selftest", roles=[Role.VIEWER.value], scopes=[])
        principal = _security_jwt_issuer.verify(pair.access_token)
        issue_ok = True
        decode_ok = principal.sub == "selftest"
    except Exception as exc:  # pragma: no cover
        logger.warning("JWT selftest failed: %s", exc)

    detector = get_threat_detector()
    bad_ua_events = detector.inspect_request(
        identity="selftest",
        method="GET",
        path="/api/v1/admin",
        headers={"User-Agent": "sqlmap/1.5"},
    )

    secrets = get_secrets_manager()
    secrets_diag = secrets.diagnostics()

    return {
        "jwt_issue": issue_ok,
        "jwt_decode": decode_ok,
        "threat_detector_works": any(e.type.value == "suspicious_ua" for e in bad_ua_events),
        "secrets_manager_configured": bool(secrets_diag),
        "dashboard": get_security_monitor().dashboard(),
    }
