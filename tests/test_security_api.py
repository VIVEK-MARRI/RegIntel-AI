"""HTTP-level tests for the M10.6 Security Platform.

Exercises every public route under ``/api/v1/security`` via FastAPI's
``TestClient``. Uses the real ``app.main`` app but installs a known-good
JWT issuer + secrets manager + audit log in module-level globals before
the first request, so the test is deterministic and does not depend on
the resolved environment.

We do *not* monkey-patch the router; we install the singletons via the
test helpers exported from each module so the wiring is identical to
production startup.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.middleware import AuditLog, AuditLogEntry
from app.security.audit_review import (
    AuditReview,
    get_audit_review,
    reset_audit_review,
    set_audit_review,
)
from app.security.jwt_auth import JWTConfig, JWTIssuer
from app.security.monitoring import SecurityMonitor, reset_security_monitor, set_security_monitor
from app.security.secrets import SecretsManager, reset_secrets_manager, set_secrets_manager
from app.security.threat_detection import (
    ThreatDetector,
    get_threat_detector,
    reset_threat_detector,
    set_threat_detector,
)


# ─── Bootstrapping ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Return a ``TestClient`` with deterministic security wiring."""
    os.environ.setdefault("SECURITY_DEV_TOKEN_ENDPOINT", "true")
    os.environ.setdefault("REGINTEL_JWT_SECRET", "x" * 48)

    import app.main as main_module
    importlib.reload(main_module)

    # Replace the module-level JWT issuer with one whose secret we know.
    issuer = JWTIssuer(
        JWTConfig(
            secret=os.environ["REGINTEL_JWT_SECRET"],
            issuer="regintel-ai",
            audience="regintel-api",
            access_ttl_seconds=120,
            refresh_ttl_seconds=600,
            min_secret_length=32,
        )
    )
    main_module._security_jwt_issuer = issuer  # type: ignore[attr-defined]

    # Wire a fresh, in-memory audit review.
    audit_log = AuditLog()
    sample_entries = [
        AuditLogEntry(
            timestamp=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
            request_id="req-1",
            method="GET",
            path="/api/v1/health",
            status_code=200,
            duration_ms=12.3,
            api_key_id="key-a",
            client_ip="127.0.0.1",
            user_agent="curl/8.0",
        ),
        AuditLogEntry(
            timestamp=datetime(2026, 6, 6, 12, 0, 5, tzinfo=timezone.utc),
            request_id="req-2",
            method="POST",
            path="/api/v1/retrieval/search",
            status_code=200,
            duration_ms=120.0,
            api_key_id="key-b",
            client_ip="10.0.0.5",
            user_agent="regintel-client/1.0",
        ),
        AuditLogEntry(
            timestamp=datetime(2026, 6, 6, 12, 0, 10, tzinfo=timezone.utc),
            request_id="req-3",
            method="GET",
            path="/api/v1/admin/keys",
            status_code=403,
            duration_ms=3.5,
            api_key_id="key-c",
            client_ip="203.0.113.4",
            user_agent="sqlmap/1.5",
        ),
        AuditLogEntry(
            timestamp=datetime(2026, 6, 6, 12, 0, 15, tzinfo=timezone.utc),
            request_id="req-4",
            method="POST",
            path="/api/v1/governance/decisions",
            status_code=500,
            duration_ms=200.0,
            api_key_id="key-b",
            client_ip="10.0.0.5",
            user_agent="regintel-client/1.0",
            error="database timeout",
        ),
    ]
    for entry in sample_entries:
        audit_log.record(entry)
    set_audit_review(AuditReview(audit_log))
    main_module._audit_log = audit_log  # type: ignore[attr-defined]

    # Fresh secrets manager with one override + one env value.
    secrets = SecretsManager(env_prefix="REGINTEL_")
    secrets.set_override("api-key", "from-override")
    set_secrets_manager(secrets)

    # Fresh threat detector (used by ``/selftest`` and ``/threats/inspect``).
    set_threat_detector(ThreatDetector())

    # Fresh monitor wired to the singletons above.
    set_security_monitor(
        SecurityMonitor(
            audit_review=get_audit_review(),
            threat_detector=get_threat_detector(),
            secrets_manager=secrets,
        )
    )

    yield TestClient(main_module.app)

    # Reset module-level singletons so other test modules start clean.
    reset_audit_review()
    reset_threat_detector()
    reset_security_monitor()
    reset_secrets_manager()


# ─── Health ────────────────────────────────────────────────────────


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["module"] == "security"
        assert "dashboard" in body


# ─── Auth ──────────────────────────────────────────────────────────


class TestAuth:
    def test_issue_and_me_round_trip(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/auth/token",
            json={"subject": "alice", "roles": ["viewer"], "scopes": ["read:public"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "Bearer"
        access = body["access_token"]
        refresh = body["refresh_token"]
        assert body["expires_in"] >= 60

        me = client.get(
            "/api/v1/security/auth/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert me.status_code == 200, me.text
        me_body = me.json()
        assert me_body["subject_id"] == "alice"
        assert "viewer" in me_body["roles"]
        assert "read:public" in me_body["scopes"]
        assert "read:public" in me_body["permissions"]

        # Refresh issues a fresh pair.
        r2 = client.post(
            "/api/v1/security/auth/refresh", json={"refresh_token": refresh}
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["access_token"] != access

    def test_refresh_rejects_missing_token(self, client: TestClient) -> None:
        r = client.post("/api/v1/security/auth/refresh", json={})
        assert r.status_code == 400

    def test_refresh_rejects_garbage(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/auth/refresh", json={"refresh_token": "not-a-jwt"}
        )
        assert r.status_code == 401

    def test_me_without_token_rejected(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/auth/me")
        assert r.status_code == 401

    def test_issue_validation_ttl_minimum(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/auth/token",
            json={"subject": "x", "ttl_seconds": 30},
        )
        assert r.status_code == 422

    def test_issue_subject_required(self, client: TestClient) -> None:
        r = client.post("/api/v1/security/auth/token", json={"roles": []})
        assert r.status_code == 422


# ─── Roles & API gateway ──────────────────────────────────────────


class TestRoles:
    def test_roles_payload_complete(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/roles")
        assert r.status_code == 200
        body = r.json()
        for role in ("viewer", "analyst", "operator", "auditor", "admin", "service"):
            assert role in body["roles"]
        # Admin must have a non-trivial grant.
        assert "manage:users" in body["roles"]["admin"]

    def test_api_gateway_summary(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/api-gateway/summary")
        assert r.status_code == 200
        body = r.json()
        assert "cors_origins" in body
        assert "ip_default_allow" in body
        assert "signature_required_paths" in body


# ─── Secrets ──────────────────────────────────────────────────────


class TestSecrets:
    def test_secrets_diagnostics_redacts(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/secrets")
        assert r.status_code == 200
        body = r.json()
        # The cached entry must never contain the raw value.
        cached = body.get("cached", {})
        if cached:
            for name, entry in cached.items():
                assert "value" not in entry
                assert "preview" in entry

    def test_secrets_list(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/secrets/list")
        assert r.status_code == 200
        body = r.json()
        assert "known" in body
        assert "diagnostics" in body


# ─── Audit review ─────────────────────────────────────────────────


class TestAudit:
    def test_records_list(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/audit/records")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 4
        assert body["limit"] == 100
        assert body["offset"] == 0
        assert all("request_id" in rec for rec in body["records"])
        # Review summary is also returned.
        assert body["review_summary"]["pending"] == 4

    def test_records_filter_by_status(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/audit/records", params={"status_min": 400})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2  # req-3 (403) and req-4 (500)

    def test_records_pagination(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/security/audit/records", params={"limit": 2, "offset": 0})
        r2 = client.get("/api/v1/security/audit/records", params={"limit": 2, "offset": 2})
        assert r1.status_code == 200
        assert r2.status_code == 200
        ids_1 = [rec["request_id"] for rec in r1.json()["records"]]
        ids_2 = [rec["request_id"] for rec in r2.json()["records"]]
        assert len(ids_1) == 2 and len(ids_2) == 2
        assert set(ids_1).isdisjoint(set(ids_2))

    def test_review_mark_approved(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/audit/review",
            json={"request_id": "req-1", "status": "approved", "notes": "ok"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["record"]["review_status"] == "approved"
        assert body["record"]["reviewed_by"] in {"system", "alice"}  # no auth → "system"

    def test_review_rejects_bad_status(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/audit/review",
            json={"request_id": "req-1", "status": "maybe"},
        )
        assert r.status_code == 422  # Pydantic pattern validation

    def test_review_unknown_request_id(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/audit/review",
            json={"request_id": "req-DOES-NOT-EXIST", "status": "approved"},
        )
        assert r.status_code == 404

    def test_export_jsonl(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/audit/export", params={"format": "jsonl"})
        assert r.status_code == 200
        body = r.json()
        assert body["format"] == "jsonl"
        assert body["count"] == 4
        lines = [ln for ln in body["text"].split("\n") if ln]
        assert len(lines) == 4
        # Each line is a valid JSON object.
        import json

        for line in lines:
            obj = json.loads(line)
            assert "request_id" in obj

    def test_export_csv(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/audit/export", params={"format": "csv"})
        assert r.status_code == 200
        body = r.json()
        assert body["format"] == "csv"
        # The DictWriter uses the first record's keys (insertion order) for
        # the header row. ``request_id`` is the second field on AuditRecord.
        first_line = body["text"].splitlines()[0]
        assert "request_id" in first_line
        assert "method" in first_line
        assert "path" in first_line
        assert "timestamp" in first_line


# ─── Threats ──────────────────────────────────────────────────────


class TestThreats:
    def test_recent_empty(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/threats/recent")
        assert r.status_code == 200
        body = r.json()
        assert "stats" in body
        assert "events" in body

    def test_inspect_suspicious_ua(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/threats/inspect",
            json={
                "identity": "attacker",
                "method": "GET",
                "path": "/api/v1/admin",
                "headers": {"User-Agent": "sqlmap/1.5"},
            },
        )
        assert r.status_code == 200
        events = r.json()["events"]
        assert any(e["type"] == "suspicious_ua" for e in events)

    def test_inspect_large_body(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/threats/inspect",
            json={
                "identity": "anon",
                "method": "POST",
                "path": "/api/v1/x",
                "body_size": 100 * 1024 * 1024,  # 100 MB
            },
        )
        assert r.status_code == 200
        events = r.json()["events"]
        assert any(e["type"] == "large_payload" for e in events)

    def test_inspect_clean_request(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/security/threats/inspect",
            json={
                "identity": "normal-user",
                "method": "GET",
                "path": "/api/v1/retrieval/search",
                "body_size": 256,
                "headers": {"User-Agent": "regintel-client/1.0"},
            },
        )
        assert r.status_code == 200
        assert r.json()["events"] == []


# ─── Monitoring ───────────────────────────────────────────────────


class TestMonitoring:
    def test_dashboard_aggregate(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/monitoring/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "audit" in body
        assert "threats" in body
        assert "secrets" in body
        assert "alerts" in body
        # Audit section includes a review summary keyed by status.
        assert "review_summary" in body["audit"]
        # Threats section has stats + a severity roll-up.
        assert "stats" in body["threats"]
        assert "by_level" in body["threats"]


# ─── Self-test ────────────────────────────────────────────────────


class TestSelfTest:
    def test_selftest_passes(self, client: TestClient) -> None:
        r = client.get("/api/v1/security/selftest")
        assert r.status_code == 200
        body = r.json()
        assert body["jwt_issue"] is True
        assert body["jwt_decode"] is True
        assert body["threat_detector_works"] is True
        assert body["secrets_manager_configured"] is True
