"""Unit tests for the M10.6 Security Platform.

Covers:
* JWT issue / verify / refresh, expiry, signature mismatch, audience, issuer
* RBAC role / permission resolution, decorators
* SecretsManager layered resolution (env → file → vault stub)
* API gateway: CORS strict-by-default, IP allow list, request signing
* Threat detection: brute force, suspicious UA, large payload, path probing
* AuditReview: filter, paginate, mark for review, export
* SecurityMonitor dashboard + alert thresholds
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.security.api_gateway import (
    APIGateway,
    CORSConfig,
    IPAllowList,
    RequestSigner,
)
from app.security.audit_review import (
    AuditQuery,
    AuditRecord,
    AuditReview,
)
from app.security.jwt_auth import (
    JWTConfig,
    JWTError,
    JWTExpiredError,
    JWTInvalidSignatureError,
    JWTMalformedError,
    JWTPrincipal,
    JWTIssuer,
    decode_jwt,
    generate_development_secret,
)
from app.security.monitoring import Alert, AlertSeverity, SecurityMonitor
from app.security.rbac import (
    Permission,
    Principal,
    Role,
    has_permission,
    require_permission,
    require_role,
    role_permissions,
)
from app.security.secrets import (
    SecretSource,
    SecretsManager,
    reset_secrets_manager,
)
from app.security.threat_detection import (
    ThreatDetector,
    ThreatEvent,
    ThreatLevel,
    ThreatType,
    reset_threat_detector,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def jwt_config() -> JWTConfig:
    return JWTConfig(secret="x" * 64)


@pytest.fixture
def issuer(jwt_config: JWTConfig) -> JWTIssuer:
    return JWTIssuer(jwt_config)


@pytest.fixture(autouse=True)
def _reset_singletons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_secrets_manager()
    reset_threat_detector()
    monkeypatch.delenv("REGINTEL_TEST_SECRET", raising=False)
    yield
    reset_secrets_manager()
    reset_threat_detector()


# ─── JWT ───────────────────────────────────────────────────────────


class TestJWT:
    def test_issue_and_verify(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice", roles=["admin"], scopes=["read:public"])
        principal = issuer.verify(pair.access_token)
        assert principal.sub == "alice"
        assert "admin" in principal.roles
        assert "read:public" in principal.scopes
        assert principal.expires_at is not None
        assert principal.issued_at is not None

    def test_decode_jwt_helper(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("bob")
        principal = decode_jwt(
            pair.access_token,
            secret=issuer.config.secret,
            issuer=issuer.config.issuer,
            audience=issuer.config.audience,
        )
        assert principal.sub == "bob"

    def test_signature_mismatch(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice")
        tampered = pair.access_token[:-3] + "AAA"
        with pytest.raises(JWTInvalidSignatureError):
            issuer.verify(tampered)

    def test_malformed_token(self, issuer: JWTIssuer) -> None:
        with pytest.raises(JWTMalformedError):
            issuer.verify("not-a-jwt")
        with pytest.raises(JWTMalformedError):
            issuer.verify("only.two")

    def test_expiry(self, jwt_config: JWTConfig) -> None:
        # Forge a token whose ``exp`` is in the past, then confirm that
        # ``decode_jwt`` raises :class:`JWTExpiredError`. We sign the token
        # by hand because :class:`JWTConfig` enforces a 60-second floor on
        # ``access_ttl_seconds`` — we want a token that has *already*
        # expired, which is impossible to mint through the issuer.
        import base64
        import hmac
        import hashlib
        import json
        import time

        secret_bytes = jwt_config.secret.encode("utf-8")
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time()) - 100
        payload = {
            "iss": jwt_config.issuer,
            "aud": jwt_config.audience,
            "sub": "alice",
            "iat": now,
            "exp": now + 50,
            "roles": [],
            "scopes": [],
        }

        def b64(d: bytes) -> str:
            return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")

        signing_input = (
            b64(json.dumps(header, separators=(",", ":")).encode())
            + "."
            + b64(json.dumps(payload, separators=(",", ":")).encode())
        )
        sig = hmac.new(secret_bytes, signing_input.encode(), hashlib.sha256).digest()
        token = signing_input + "." + b64(sig)
        with pytest.raises(JWTExpiredError):
            decode_jwt(
                token,
                secret=jwt_config.secret,
                issuer=jwt_config.issuer,
                audience=jwt_config.audience,
                clock_skew=0,
            )

    def test_refresh_round_trip(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice", roles=["admin"])
        new_pair = issuer.refresh(pair.refresh_token)
        principal = issuer.verify(new_pair.access_token)
        assert principal.sub == "alice"
        assert "admin" in principal.roles

    def test_refresh_rejects_access_token(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice")
        with pytest.raises(JWTError):
            issuer.refresh(pair.access_token)

    def test_audience_mismatch(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice")
        with pytest.raises(JWTError):
            issuer.verify(pair.access_token, expected_audience="some-other-audience")

    def test_issuer_mismatch(self, issuer: JWTIssuer) -> None:
        pair = issuer.issue("alice")
        # Build a fresh issuer with a different issuer claim but same secret.
        other = JWTIssuer(JWTConfig(secret=issuer.config.secret, issuer="not-regintel"))
        with pytest.raises(JWTError):
            other.verify(pair.access_token)

    def test_short_secret_rejected(self) -> None:
        with pytest.raises(Exception):
            JWTConfig(secret="short")

    def test_generate_development_secret(self) -> None:
        s = generate_development_secret()
        assert len(s) >= 32

    def test_decode_with_extra_audience_in_list(self, issuer: JWTIssuer) -> None:
        # Manually craft a token with aud=[a, b] and verify with "b" as the
        # expected audience. This exercises the "audience is a list" code
        # path in :func:`decode_jwt` while keeping the security check real.
        import base64
        import hmac
        import hashlib
        import json
        import time

        secret = issuer.config.secret.encode("utf-8")
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())
        payload = {
            "iss": issuer.config.issuer,
            "aud": ["a", "b"],
            "sub": "x",
            "iat": now,
            "exp": now + 60,
        }

        def b64(d: bytes) -> str:
            return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")

        s_in = (
            b64(json.dumps(header, separators=(",", ":")).encode())
            + "."
            + b64(json.dumps(payload, separators=(",", ":")).encode())
        )
        sig = hmac.new(secret, s_in.encode(), hashlib.sha256).digest()
        token = s_in + "." + b64(sig)
        principal = issuer.verify(token, expected_audience="b")
        assert principal.sub == "x"


# ─── RBAC ──────────────────────────────────────────────────────────


class TestRBAC:
    def test_default_role_grants(self) -> None:
        assert Permission.READ_PUBLIC in role_permissions(Role.VIEWER)
        assert Permission.WRITE_COPILOT in role_permissions(Role.ANALYST)
        assert Permission.EXECUTE_WORKFLOWS in role_permissions(Role.OPERATOR)
        assert Permission.REVIEW_AUDIT in role_permissions(Role.AUDITOR)
        assert Permission.MANAGE_USERS in role_permissions(Role.ADMIN)
        assert Permission.SERVICE_TICKET in role_permissions(Role.SERVICE)

    def test_admin_has_every_permission(self) -> None:
        admin = Principal(subject_id="root", roles=(Role.ADMIN,))
        for p in Permission:
            assert admin.has_permission(p)

    def test_viewer_cannot_write(self) -> None:
        viewer = Principal(subject_id="v", roles=(Role.VIEWER,))
        assert not viewer.has_permission(Permission.WRITE_DOCUMENTS)
        assert viewer.has_permission(Permission.READ_DOCUMENTS)

    def test_from_jwt_ignores_unknown_roles_and_scopes(self) -> None:
        # Unknown role names ("not-a-role") must be silently dropped to
        # prevent an attacker from injecting a string that looks privileged
        # but isn't in the role table. ADMIN is preserved and grants a
        # super-set of permissions; unknown scope names likewise do not
        # contribute implicit grants.
        jwt = JWTPrincipal(
            sub="x",
            roles=("not-a-role", "admin"),
            scopes=("not-a-perm", "read:public"),
        )
        principal = Principal.from_jwt(jwt)
        assert Role.ADMIN in principal.roles
        assert "not-a-role" not in {r.value for r in principal.roles}
        # "read:public" matches Permission.READ_PUBLIC's value, so the
        # explicit scope grants that permission. ADMIN additionally grants
        # WRITE_DOCUMENTS, which is what we verify below.
        assert principal.has_permission(Permission.READ_PUBLIC)
        assert principal.has_permission(Permission.WRITE_DOCUMENTS)
        # And a vanilla VIEWER with the same scope set does NOT have
        # WRITE_DOCUMENTS — proving the permission comes from ADMIN, not
        # from a stray scope string.
        viewer = Principal.from_jwt(
            JWTPrincipal(sub="y", roles=("viewer",), scopes=("read:public",))
        )
        assert not viewer.has_permission(Permission.WRITE_DOCUMENTS)

    def test_has_permission_helper(self) -> None:
        p = Principal(subject_id="x", roles=(Role.OPERATOR,))
        assert has_permission(p, Permission.EXECUTE_WORKFLOWS)
        assert not has_permission(p, Permission.MANAGE_USERS)

    @pytest.mark.asyncio
    async def test_require_role_decorator_passes(self) -> None:
        @require_role(Role.ADMIN)
        async def delete_user(*args: Any, **kwargs: Any) -> str:
            return "ok"

        principal = Principal(subject_id="r", roles=(Role.ADMIN,))
        assert await delete_user(principal=principal) == "ok"

    @pytest.mark.asyncio
    async def test_require_role_decorator_blocks(self) -> None:
        @require_role(Role.ADMIN)
        async def delete_user(*args: Any, **kwargs: Any) -> str:
            return "ok"

        principal = Principal(subject_id="r", roles=(Role.VIEWER,))
        with pytest.raises(PermissionError):
            await delete_user(principal=principal)

    @pytest.mark.asyncio
    async def test_require_permission_decorator_enforces_all(self) -> None:
        @require_permission(Permission.MANAGE_USERS, Permission.MANAGE_KEYS)
        async def reset(*args: Any, **kwargs: Any) -> str:
            return "ok"

        # Admin can do both.
        admin = Principal(subject_id="r", roles=(Role.ADMIN,))
        assert await reset(principal=admin) == "ok"
        # Auditor cannot.
        auditor = Principal(subject_id="r", roles=(Role.AUDITOR,))
        with pytest.raises(PermissionError):
            await reset(principal=auditor)

    @pytest.mark.asyncio
    async def test_decorator_rejects_missing_principal(self) -> None:
        @require_role(Role.ADMIN)
        async def reset(*args: Any, **kwargs: Any) -> str:
            return "ok"

        with pytest.raises(PermissionError):
            await reset()


# ─── Secrets ──────────────────────────────────────────────────────


class TestSecrets:
    def test_resolve_from_explicit_override(self) -> None:
        sm = SecretsManager()
        result = sm.get("my-secret", override="explicit-value")
        assert result.value == "explicit-value"
        assert result.source == SecretSource.EXPLICIT

    def test_resolve_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REGINTEL_DB_PASSWORD", "env-value")
        sm = SecretsManager()
        result = sm.get("db-password")
        assert result.value == "env-value"
        assert result.source == SecretSource.ENV

    def test_resolve_from_file(self, tmp_path: Path) -> None:
        (tmp_path / "api-key.txt").write_text(
            "API-KEY=from-file\nOTHER=ignored\n", encoding="utf-8"
        )
        sm = SecretsManager(file_root=tmp_path)
        result = sm.get("api-key")
        assert result.value == "from-file"
        assert result.source == SecretSource.FILE

    def test_resolve_from_json_file(self, tmp_path: Path) -> None:
        (tmp_path / "secrets.json").write_text(
            '{"openai": "sk-1234"}', encoding="utf-8"
        )
        sm = SecretsManager(file_root=tmp_path)
        result = sm.get("openai")
        assert result.value == "sk-1234"
        assert result.source == SecretSource.FILE

    def test_not_found_raises(self) -> None:
        sm = SecretsManager()
        with pytest.raises(KeyError):
            sm.get("missing-secret")

    def test_default_falls_back(self) -> None:
        sm = SecretsManager()
        result = sm.get("missing", default="fallback")
        assert result.value == "fallback"

    def test_precedence_override_beats_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGINTEL_X", "from-env")
        sm = SecretsManager()
        assert sm.get("x", override="from-override").value == "from-override"
        # Without override, env wins.
        assert sm.get("x").value == "from-env"

    def test_preview_does_not_leak_value(self) -> None:
        sm = SecretsManager()
        result = sm.get(
            "verylongsecretvalue", override="sk-1234567890ABCDEFabcdefghijklmnop"
        )
        preview = result.preview(visible=4)
        assert "1234567890" not in preview
        assert "***" in preview or "…" in preview

    def test_cache_ttl(self) -> None:
        # Values resolved from the long-lived sources (env / file / vault) are
        # cached for ``cache_ttl_seconds``. Within the TTL the cached value
        # wins, even if the underlying file changes; once the TTL expires
        # (or the cache is invalidated) the fresh value is picked up.
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "k.txt"
            file_path.write_text("k=v1\n", encoding="utf-8")
            sm = SecretsManager(file_root=Path(tmp), cache_ttl_seconds=60)
            assert sm.get("k", use_cache=True).value == "v1"

            # Mutate the file; cached value is still served.
            file_path.write_text("k=v2\n", encoding="utf-8")
            assert sm.get("k", use_cache=True).value == "v1"

            # Bypass the cache: the new value is read.
            assert sm.get("k", use_cache=False).value == "v2"

            # Invalidate: cache is cleared, the new value is returned.
            sm.invalidate("k")
            assert sm.get("k", use_cache=True).value == "v2"

            # Stored overrides always win over file / cache (they live in
            # their own side-channel).
            sm.set_override("k", "v3")
            assert sm.get("k", use_cache=True).value == "v3"
            # invalidate() clears both the override and the cache, so the
            # file (v2) is once again the source of truth.
            sm.invalidate("k")
            assert sm.get("k", use_cache=True).value == "v2"

    def test_diagnostics_redacts(self, tmp_path: Path) -> None:
        (tmp_path / "k.txt").write_text("k=hello-world\n", encoding="utf-8")
        sm = SecretsManager(file_root=tmp_path)
        sm.get("k")
        diag = sm.diagnostics()
        assert diag["file_root"] == str(tmp_path)
        assert diag["cache_size"] >= 1
        # The cached entry must contain only a preview, not the value.
        cached = diag["cached"]["k"]
        assert "preview" in cached
        assert cached["preview"] != "hello-world"

    def test_list_known_includes_env_and_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("REGINTEL_FOO", "bar")
        (tmp_path / "alpha.txt").write_text("alpha=1", encoding="utf-8")
        (tmp_path / "beta.txt").write_text("beta=2", encoding="utf-8")
        sm = SecretsManager(file_root=tmp_path)
        known = list(sm.list_known())
        assert "foo" in known
        assert "alpha" in known
        assert "beta" in known


# ─── API gateway ──────────────────────────────────────────────────


class TestAPIGateway:
    def test_cors_strict_by_default(self) -> None:
        cors = CORSConfig()
        assert cors.headers_for(None) == {}
        assert cors.headers_for("https://evil.example") == {}

    def test_cors_allows_configured_origin(self) -> None:
        cors = CORSConfig(allowed_origins=("https://app.regintel.ai",))
        headers = cors.headers_for("https://app.regintel.ai")
        assert headers["Access-Control-Allow-Origin"] == "https://app.regintel.ai"
        assert "Vary" in headers

    def test_cors_wildcard_rejected_with_credentials(self) -> None:
        cors = CORSConfig(allowed_origins=("*",), allow_credentials=True)
        # Wildcard + credentials is forbidden — must NOT echo back the origin.
        assert cors.headers_for("https://app.regintel.ai") == {}

    def test_ip_allowlist_exact(self) -> None:
        al = IPAllowList.from_cidrs(allowed_cidrs=("10.0.0.1",), default_allow=False)
        assert al.is_allowed("10.0.0.1")
        assert not al.is_allowed("10.0.0.2")

    def test_ip_allowlist_cidr(self) -> None:
        al = IPAllowList.from_cidrs(allowed_cidrs=("10.0.0.0/24",), default_allow=False)
        assert al.is_allowed("10.0.0.1")
        assert al.is_allowed("10.0.0.255")
        assert not al.is_allowed("10.0.1.1")

    def test_ip_allowlist_deny_overrides(self) -> None:
        al = IPAllowList.from_cidrs(
            allowed_cidrs=("10.0.0.0/24",),
            denied_cidrs=("10.0.0.5",),
        )
        assert al.is_allowed("10.0.0.1")
        assert not al.is_allowed("10.0.0.5")
        allowed, reason = al.decide("10.0.0.5")
        assert not allowed
        assert "denied" in reason

    def test_ip_allowlist_invalid_ip(self) -> None:
        al = IPAllowList()
        assert not al.is_allowed("not-an-ip")

    def test_request_signer_round_trip(self) -> None:
        signer = RequestSigner("a" * 32)
        body = b'{"x":1}'
        sig = signer.sign("POST", "/api/v1/x", body, timestamp=1000)
        assert signer.verify(
            "POST",
            "/api/v1/x",
            body,
            sig["X-Signature"],
            sig["X-Signature-Timestamp"],
            now=1000,
        )[0]

    def test_request_signer_rejects_tampered_body(self) -> None:
        signer = RequestSigner("a" * 32)
        sig = signer.sign("POST", "/api/v1/x", b"a", timestamp=1000)
        ok, reason = signer.verify(
            "POST",
            "/api/v1/x",
            b"b",
            sig["X-Signature"],
            sig["X-Signature-Timestamp"],
            now=1000,
        )
        assert not ok
        assert reason == "signature mismatch"

    def test_request_signer_rejects_expired_timestamp(self) -> None:
        signer = RequestSigner("a" * 32, max_skew_seconds=10)
        sig = signer.sign("POST", "/api/v1/x", b"", timestamp=1000)
        ok, reason = signer.verify(
            "POST",
            "/api/v1/x",
            b"",
            sig["X-Signature"],
            sig["X-Signature-Timestamp"],
            now=2000,
        )
        assert not ok
        assert "timestamp" in reason

    def test_request_signer_short_secret_rejected(self) -> None:
        with pytest.raises(ValueError):
            RequestSigner("short")

    def test_api_gateway_decision(self) -> None:
        gw = APIGateway(
            ip_allow=IPAllowList.from_cidrs(
                allowed_cidrs=("127.0.0.0/8",), default_allow=False
            ),
            require_signature_paths={"/api/v1/admin/keys"},
        )
        assert gw.check_ip("127.0.0.1")[0]
        assert not gw.check_ip("8.8.8.8")[0]
        # Path not requiring signature → ok regardless of signature
        ok, _ = gw.check_request_signature("GET", "/api/v1/x", b"", None, None)
        assert ok
        # Path requiring signature with no sig/ts at all → "missing signature"
        ok, reason = gw.check_request_signature(
            "GET", "/api/v1/admin/keys", b"", None, None
        )
        assert not ok
        assert "missing signature" in reason
        # Path requiring signature with sig/ts provided but no signer
        # configured → "signer not configured" (the more diagnostic failure
        # mode for operators).
        ok, reason = gw.check_request_signature(
            "GET", "/api/v1/admin/keys", b"", "deadbeef", "1234567890"
        )
        assert not ok
        assert "signer not configured" in reason

    def test_api_gateway_summary(self) -> None:
        gw = APIGateway()
        s = gw.summary()
        assert "cors_origins" in s
        assert "ip_allow_count" in s
        assert s["signer_configured"] is False


# ─── Threat detection ─────────────────────────────────────────────


class TestThreatDetection:
    def test_suspicious_user_agent(self) -> None:
        td = ThreatDetector()
        events = td.inspect_request(
            identity="ip:1.2.3.4",
            method="GET",
            path="/api/v1/x",
            headers={"user-agent": "sqlmap/1.5"},
        )
        assert any(e.type == ThreatType.SUSPICIOUS_UA for e in events)

    def test_large_payload_detected(self) -> None:
        td = ThreatDetector(max_payload_bytes=10)
        events = td.inspect_request(
            identity="ip:1.2.3.4",
            method="POST",
            path="/api/v1/x",
            body_size=11,
        )
        assert any(e.type == ThreatType.LARGE_PAYLOAD for e in events)

    def test_header_abuse_detected(self) -> None:
        td = ThreatDetector()
        events = td.inspect_request(
            identity="ip:1.2.3.4",
            method="GET",
            path="/api/v1/x",
            headers={"user-agent": "Mozilla"},
            # The detector also inspects User-Agent, so put the abuse elsewhere.
        )
        # Use a different header to avoid clashing with UA detection.
        events2 = td.inspect_request(
            identity="ip:1.2.3.4",
            method="GET",
            path="/api/v1/x",
            headers={"referer": "http://x/?q=UNION SELECT 1"},
        )
        assert any(e.type == ThreatType.HEADER_ABUSE for e in events2)
        assert not any(e.type == ThreatType.HEADER_ABUSE for e in events)  # clean UA

    def test_brute_force_rolls_up(self) -> None:
        td = ThreatDetector(brute_force_threshold=3, brute_force_window_seconds=60.0)
        for _ in range(3):
            td.inspect_response(
                identity="ip:1.2.3.4", status_code=401, path="/api/v1/x"
            )
        events = td.inspect_response(
            identity="ip:1.2.3.4", status_code=401, path="/api/v1/x"
        )
        assert any(e.type == ThreatType.BRUTE_FORCE for e in events)

    def test_brute_force_below_threshold(self) -> None:
        td = ThreatDetector(brute_force_threshold=5)
        for _ in range(2):
            td.inspect_response(
                identity="ip:1.2.3.4", status_code=401, path="/api/v1/x"
            )
        events = td.recent_events()
        assert not any(e.type == ThreatType.BRUTE_FORCE for e in events)

    def test_path_probing_rolls_up(self) -> None:
        td = ThreatDetector(path_probing_threshold=3, path_probing_window_seconds=60.0)
        for path in ["/admin/users", "/admin/keys", "/api/v1/security"]:
            td.inspect_request(identity="ip:1.2.3.4", method="GET", path=path)
        events = td.inspect_request(
            identity="ip:1.2.3.4", method="GET", path="/admin/audit"
        )
        assert any(e.type == ThreatType.PATH_PROBING for e in events)

    def test_recent_events_bounded(self) -> None:
        td = ThreatDetector(max_event_history=5)
        for _ in range(20):
            td.inspect_request(
                identity="ip:1.2.3.4",
                method="POST",
                path="/x",
                body_size=1_000_000,
            )
        assert len(td.recent_events(limit=1000)) <= 5

    def test_subscriber_called(self) -> None:
        td = ThreatDetector()
        captured: List[ThreatEvent] = []
        td.subscribe(captured.append)
        td.inspect_request(
            identity="x", method="GET", path="/x", headers={"user-agent": "nikto"}
        )
        assert captured
        assert captured[0].type == ThreatType.SUSPICIOUS_UA

    def test_stats_summary(self) -> None:
        td = ThreatDetector()
        td.inspect_request(
            identity="x", method="GET", path="/x", headers={"user-agent": "sqlmap"}
        )
        s = td.stats()
        assert s["total_events"] >= 1
        assert "suspicious_ua" in s["by_type"]


# ─── Audit review ─────────────────────────────────────────────────


class TestAuditReview:
    @pytest.fixture
    def sample_audit_log(self):
        from app.middleware import AuditLog, AuditLogEntry

        log = AuditLog()
        now = datetime.now(timezone.utc)
        for i, (status, method, path) in enumerate(
            [
                (200, "GET", "/api/v1/x"),
                (401, "POST", "/api/v1/auth"),
                (404, "GET", "/api/v1/missing"),
                (500, "POST", "/api/v1/y"),
            ]
        ):
            log.record(
                AuditLogEntry(
                    timestamp=now - timedelta(minutes=i),
                    request_id=f"req-{i}",
                    method=method,
                    path=path,
                    status_code=status,
                    duration_ms=10.0 + i,
                    api_key_id=None,
                    client_ip="10.0.0.1",
                    user_agent="test",
                )
            )
        return log

    def test_records_returns_all_by_default(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        assert len(review.records()) == 4

    def test_records_filter_by_status(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        q = AuditQuery(status_code=401)
        rs = review.records(q)
        assert len(rs) == 1
        assert rs[0].status_code == 401

    def test_records_filter_by_status_range(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        rs = review.records(AuditQuery(status_min=400, status_max=499))
        codes = sorted(r.status_code for r in rs)
        assert codes == [401, 404]

    def test_records_filter_by_path_prefix(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        rs = review.records(AuditQuery(path_prefix="/api/v1/auth"))
        assert len(rs) == 1
        assert rs[0].path == "/api/v1/auth"

    def test_records_pagination(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        page1 = review.records(AuditQuery(limit=2, offset=0))
        page2 = review.records(AuditQuery(limit=2, offset=2))
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r.request_id for r in page1}.isdisjoint({r.request_id for r in page2})

    def test_mark_for_review(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        record = review.mark("req-1", status="approved", reviewer="sec", notes="ok")
        assert record.review_status == "approved"
        assert record.reviewed_by == "sec"
        assert review.review_summary()["approved"] == 1

    def test_mark_rejects_bad_status(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        with pytest.raises(ValueError):
            review.mark("req-1", status="wat", reviewer="sec")

    def test_mark_unknown_request_id(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        with pytest.raises(KeyError):
            review.mark("does-not-exist", status="approved", reviewer="sec")

    def test_export_jsonl(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        text = review.export_jsonl()
        assert text.count("\n") == 4
        import json

        first = json.loads(text.splitlines()[0])
        assert "request_id" in first

    def test_export_csv(self, sample_audit_log) -> None:
        review = AuditReview(sample_audit_log)
        text = review.export_csv()
        lines = text.splitlines()
        assert len(lines) == 5  # 1 header + 4 rows

    def test_write_export_creates_file(self, sample_audit_log, tmp_path: Path) -> None:
        review = AuditReview(sample_audit_log)
        out = tmp_path / "audit.jsonl"
        written = review.write_export(out, format="jsonl")
        assert out.exists()
        assert written > 0


# ─── Security monitor ──────────────────────────────────────────────


class TestSecurityMonitor:
    def test_dashboard_includes_threats_secrets_audit(self) -> None:
        sm = SecurityMonitor()
        dash = sm.dashboard()
        assert "threats" in dash
        assert "secrets" in dash
        assert "audit" in dash
        assert "alerts" in dash

    def test_alert_threshold_critical(self) -> None:
        sm = SecurityMonitor(critical_threat_threshold=1)
        # Record one critical threat event manually
        sm.record(
            Alert(
                name="manual",
                severity=AlertSeverity.CRITICAL,
                message="manual",
                timestamp=datetime.now(timezone.utc),
            )
        )
        # Dashboard re-check should not crash and may record more alerts.
        dash = sm.dashboard()
        assert dash["alerts"]["counts"]["critical"] >= 1

    def test_alert_counts_and_recent(self) -> None:
        sm = SecurityMonitor()
        sm.record(
            Alert(
                name="a",
                severity=AlertSeverity.INFO,
                message="x",
                timestamp=datetime.now(timezone.utc),
            )
        )
        sm.record(
            Alert(
                name="b",
                severity=AlertSeverity.WARNING,
                message="y",
                timestamp=datetime.now(timezone.utc),
            )
        )
        assert sm.alert_counts()["warning"] == 1
        assert sm.alert_counts()["info"] == 1
        assert len(sm.recent_alerts(10)) == 2
