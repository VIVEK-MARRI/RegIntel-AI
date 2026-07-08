"""Tests for Module 8.8 — Enterprise Administration Dashboard."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.admin import (
    BuiltInRole,
    Permission,
    PlatformSettingUpdateRequest,
    RoleCreateRequest,
    RoleFilter,
    UserCreateRequest,
    UserFilter,
    UserStatus,
    UserUpdateRequest,
)
from app.services.admin import (
    AdminService,
    InMemoryAdminStore,
    RoleManager,
    UserManagement,
    build_default_admin_service,
)


# ─── Service fixtures ────────────────────────────────────────


@pytest.fixture
def store() -> InMemoryAdminStore:
    return InMemoryAdminStore()


@pytest.fixture
def service(store: InMemoryAdminStore) -> AdminService:
    return AdminService(store)


# ─── Built-in roles seed ────────────────────────────────────


class TestBuiltInRoles:
    def test_all_seven_built_in_roles_present(self, service: AdminService) -> None:
        flt = RoleFilter(page=1, page_size=100)
        out = service.list_roles(flt)
        names = {r.name for r in out.items}
        for r in BuiltInRole:
            assert r.value in names

    def test_admin_role_has_wildcard(self, service: AdminService) -> None:
        admin = service.get_role_by_name(BuiltInRole.ADMIN.value)
        assert admin is not None
        codes = [p.code for p in admin.permissions]
        assert "*" in codes

    def test_viewer_role_lacks_write(self, service: AdminService) -> None:
        viewer = service.get_role_by_name(BuiltInRole.VIEWER.value)
        assert viewer is not None
        codes = [p.code for p in viewer.permissions]
        assert "dashboard.read" in codes
        assert "compliance.write" not in codes

    def test_built_in_roles_cannot_be_deleted(self, service: AdminService) -> None:
        admin = service.get_role_by_name(BuiltInRole.ADMIN.value)
        assert service.delete_role(admin.role_id) is False


# ─── User management ────────────────────────────────────────


class TestUserManagement:
    def test_create_and_get(self, service: AdminService) -> None:
        u = service.create_user(
            UserCreateRequest(username="alice", email="alice@example.com")
        )
        assert u.username == "alice"
        assert service.get_user(u.user_id).email == "alice@example.com"

    def test_get_by_username(self, service: AdminService) -> None:
        u = service.create_user(UserCreateRequest(username="bob", email="bob@x.com"))
        assert service.store.get_user_by_username("bob").user_id == u.user_id

    def test_update(self, service: AdminService) -> None:
        u = service.create_user(UserCreateRequest(username="u1", email="u1@x.com"))
        upd = service.update_user(
            u.user_id,
            UserUpdateRequest(
                email="new@x.com",
                status=UserStatus.SUSPENDED,
            ),
        )
        assert upd.email == "new@x.com"
        assert upd.status == UserStatus.SUSPENDED

    def test_update_missing_returns_none(self, service: AdminService) -> None:
        assert (
            service.update_user(
                "missing",
                UserUpdateRequest(email="x@x.com"),
            )
            is None
        )

    def test_delete(self, service: AdminService) -> None:
        u = service.create_user(UserCreateRequest(username="u", email="u@x.com"))
        assert service.delete_user(u.user_id) is True
        assert service.delete_user(u.user_id) is False

    def test_record_login(self, service: AdminService) -> None:
        u = service.create_user(UserCreateRequest(username="u", email="u@x.com"))
        u2 = service.record_login(u.user_id)
        assert u2 is not None
        assert u2.last_login_at is not None

    def test_list_filter(self, service: AdminService) -> None:
        for n in ["alice", "bob", "carol"]:
            service.create_user(UserCreateRequest(username=n, email=f"{n}@x.com"))
        out = service.list_users(UserFilter(text_query="alice", page=1, page_size=10))
        assert out.total == 1
        assert out.items[0].username == "alice"


# ─── Role management ────────────────────────────────────────


class TestRoleManagement:
    def test_create_role(self, service: AdminService) -> None:
        r = service.create_role(
            RoleCreateRequest(
                name="custom",
                permissions=[
                    Permission(code="x.read"),
                    Permission(code="x.write"),
                ],
            )
        )
        assert r.name == "custom"
        assert not r.built_in

    def test_update_permissions(self, service: AdminService) -> None:
        r = service.create_role(RoleCreateRequest(name="x", permissions=[]))
        upd = service.update_role_permissions(r.role_id, [Permission(code="x.read")])
        assert upd is not None
        assert len(upd.permissions) == 1

    def test_delete_custom_role(self, service: AdminService) -> None:
        r = service.create_role(RoleCreateRequest(name="custom", permissions=[]))
        assert service.delete_role(r.role_id) is True

    def test_grant_and_revoke(self, service: AdminService) -> None:
        u = service.create_user(UserCreateRequest(username="u", email="u@x.com"))
        r = service.create_role(RoleCreateRequest(name="r", permissions=[]))
        u2 = service.grant_role(u.user_id, r.role_id)
        assert r.role_id in u2.role_ids
        u3 = service.revoke_role(u.user_id, r.role_id)
        assert r.role_id not in u3.role_ids


# ─── RBAC ───────────────────────────────────────────────────


class TestRBAC:
    def test_admin_has_wildcard(self, service: AdminService) -> None:
        admin_role = service.get_role_by_name(BuiltInRole.ADMIN.value)
        u = service.create_user(
            UserCreateRequest(
                username="u",
                email="u@x.com",
                role_ids=[admin_role.role_id],
            )
        )
        check = service.rbac_check(u.user_id, "anything.at_all")
        assert check.allowed is True

    def test_viewer_cannot_audit(self, service: AdminService) -> None:
        viewer = service.get_role_by_name(BuiltInRole.VIEWER.value)
        u = service.create_user(
            UserCreateRequest(
                username="v",
                email="v@x.com",
                role_ids=[viewer.role_id],
            )
        )
        check = service.rbac_check(u.user_id, "audit.read")
        assert check.allowed is False

    def test_inactive_user_denied(self, service: AdminService) -> None:
        admin_role = service.get_role_by_name(BuiltInRole.ADMIN.value)
        u = service.create_user(
            UserCreateRequest(
                username="s",
                email="s@x.com",
                role_ids=[admin_role.role_id],
                status=UserStatus.SUSPENDED,
            )
        )
        check = service.rbac_check(u.user_id, "anything")
        assert check.allowed is False
        assert "suspended" in check.reason

    def test_unknown_user_denied(self, service: AdminService) -> None:
        check = service.rbac_check("missing-user", "x.read")
        assert check.allowed is False
        assert "not found" in check.reason


# ─── Platform settings ─────────────────────────────────────


class TestPlatformSettings:
    def test_set_and_get(self, service: AdminService) -> None:
        s = service.set_setting(
            "rate_limit",
            PlatformSettingUpdateRequest(value=100, description="per minute"),
        )
        assert s.value == 100
        assert s.value_type == "int"
        got = service.get_setting("rate_limit")
        assert got is not None

    def test_set_updates_existing(self, service: AdminService) -> None:
        service.set_setting("x", PlatformSettingUpdateRequest(value=1))
        s2 = service.set_setting("x", PlatformSettingUpdateRequest(value=2))
        assert s2.value == 2

    def test_set_string_type(self, service: AdminService) -> None:
        s = service.set_setting("name", PlatformSettingUpdateRequest(value="acme"))
        assert s.value_type == "string"

    def test_set_bool_type(self, service: AdminService) -> None:
        s = service.set_setting("enabled", PlatformSettingUpdateRequest(value=True))
        assert s.value_type == "bool"

    def test_set_json_type(self, service: AdminService) -> None:
        s = service.set_setting("config", PlatformSettingUpdateRequest(value={"a": 1}))
        assert s.value_type == "json"

    def test_delete_setting(self, service: AdminService) -> None:
        service.set_setting("x", PlatformSettingUpdateRequest(value=1))
        assert service.delete_setting("x") is True
        assert service.delete_setting("x") is False

    def test_list_by_category(self, service: AdminService) -> None:
        service.set_setting(
            "x",
            PlatformSettingUpdateRequest(value=1, category="security"),
        )
        items = service.settings_manager.list_by_category("security")
        assert any(s.key == "x" for s in items)


# ─── Dashboards ────────────────────────────────────────────


class TestDashboards:
    def test_overview(self, service: AdminService) -> None:
        o = service.overview()
        assert o.total_users >= 0
        assert o.total_roles >= 7  # built-in
        assert o.compliance_rate == 0.0  # no governance wired

    def test_governance_dashboard(self, service: AdminService) -> None:
        g = service.governance_dashboard()
        assert g.compliance_rate == 0.0
        assert isinstance(g.by_severity, dict)

    def test_audit_dashboard(self, service: AdminService) -> None:
        # Bind an audit service and verify the dashboard picks it up
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import AuditRecordCreateRequest, AuditAction

        aus = AuditService(InMemoryAuditStore())
        aus.create_record(
            AuditRecordCreateRequest(actor="x", action=AuditAction.CREATE)
        )
        service.dashboard.bind(audit_service=aus)
        d = service.audit_dashboard()
        assert d.total_records == 1
        assert d.chain_integrity is True
        assert d.last_chain_hash != ""

    def test_compliance_dashboard_no_audit(self, service: AdminService) -> None:
        c = service.compliance_dashboard()
        assert c.total_reports == 0

    def test_compliance_dashboard_with_reports(self, service: AdminService) -> None:
        from app.services.audit import AuditService, InMemoryAuditStore
        from app.schemas.audit import (
            AuditRecordCreateRequest,
            AuditAction,
            ComplianceReportCreateRequest,
        )

        aus = AuditService(InMemoryAuditStore())
        aus.create_record(
            AuditRecordCreateRequest(actor="x", action=AuditAction.CREATE)
        )
        aus.generate_report(ComplianceReportCreateRequest(title="R1"))
        service.dashboard.bind(audit_service=aus)
        c = service.compliance_dashboard()
        assert c.total_reports == 1
        assert c.reports_complete == 1
        assert c.average_report_sections > 0

    def test_stats(self, service: AdminService) -> None:
        s = service.stats()
        assert s.total_roles >= 7
        assert s.built_in_roles >= 7


# ─── API tests ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "metrics" in body


@pytest.mark.asyncio
async def test_api_overview(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/overview")
    assert r.status_code == 200
    body = r.json()
    assert "total_users" in body
    assert "compliance_rate" in body


@pytest.mark.asyncio
async def test_api_governance_dashboard(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/governance")
    assert r.status_code == 200
    body = r.json()
    assert "compliance_rate" in body


@pytest.mark.asyncio
async def test_api_audit_dashboard(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/audit")
    assert r.status_code == 200
    body = r.json()
    assert "chain_length" in body


@pytest.mark.asyncio
async def test_api_compliance_dashboard(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/compliance")
    assert r.status_code == 200
    body = r.json()
    assert "total_reports" in body


@pytest.mark.asyncio
async def test_api_stats(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert "built_in_roles" in body
    assert body["built_in_roles"] >= 7


@pytest.mark.asyncio
async def test_api_users_crud(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/admin/users",
        json={"username": "alice", "email": "alice@x.com"},
    )
    assert r.status_code == 201
    body = r.json()
    uid = body["user_id"]
    r2 = await client.get(f"/api/v1/admin/users/{uid}")
    assert r2.status_code == 200
    r3 = await client.patch(
        f"/api/v1/admin/users/{uid}",
        json={"email": "new@x.com"},
    )
    assert r3.status_code == 200
    assert r3.json()["email"] == "new@x.com"
    r4 = await client.post(f"/api/v1/admin/users/{uid}/login")
    assert r4.status_code == 200
    assert r4.json()["last_login_at"] is not None
    r5 = await client.delete(f"/api/v1/admin/users/{uid}")
    assert r5.status_code == 204


@pytest.mark.asyncio
async def test_api_roles_crud(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/admin/roles",
        json={
            "name": "custom-test",
            "permissions": [{"code": "x.read"}],
        },
    )
    assert r.status_code == 201
    rid = r.json()["role_id"]
    r2 = await client.get(f"/api/v1/admin/roles/{rid}")
    assert r2.status_code == 200
    r3 = await client.patch(
        f"/api/v1/admin/roles/{rid}/permissions",
        json=[{"code": "x.read"}, {"code": "x.write"}],
    )
    assert r3.status_code == 200
    assert len(r3.json()["permissions"]) == 2
    r4 = await client.delete(f"/api/v1/admin/roles/{rid}")
    assert r4.status_code == 204


@pytest.mark.asyncio
async def test_api_list_built_in_roles(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/roles?built_in=true")
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["built_in"] for i in items)
    assert len(items) >= 7


@pytest.mark.asyncio
async def test_api_rbac_check(
    client: AsyncClient,
) -> None:
    # Create a user with the viewer role
    r = await client.get("/api/v1/admin/roles")
    viewer = next(i for i in r.json()["items"] if i["name"] == "viewer")
    r2 = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "vw",
            "email": "vw@x.com",
            "role_ids": [viewer["role_id"]],
        },
    )
    uid = r2.json()["user_id"]
    r3 = await client.get(f"/api/v1/admin/rbac/{uid}?permission=audit.read")
    assert r3.status_code == 200
    assert r3.json()["allowed"] is False
    r4 = await client.get(f"/api/v1/admin/rbac/{uid}?permission=dashboard.read")
    assert r4.status_code == 200
    assert r4.json()["allowed"] is True


@pytest.mark.asyncio
async def test_api_grant_and_revoke_role(
    client: AsyncClient,
) -> None:
    # Create a custom role
    r = await client.post(
        "/api/v1/admin/roles",
        json={"name": "extra", "permissions": []},
    )
    rid = r.json()["role_id"]
    # Create a user
    r2 = await client.post(
        "/api/v1/admin/users",
        json={"username": "x", "email": "x@x.com"},
    )
    uid = r2.json()["user_id"]
    # Grant
    r3 = await client.post(f"/api/v1/admin/users/{uid}/roles/{rid}")
    assert r3.status_code == 200
    assert rid in r3.json()["role_ids"]
    # Revoke
    r4 = await client.delete(f"/api/v1/admin/users/{uid}/roles/{rid}")
    assert r4.status_code == 204


@pytest.mark.asyncio
async def test_api_settings_crud(
    client: AsyncClient,
) -> None:
    r = await client.put(
        "/api/v1/admin/settings/rate_limit",
        json={"value": 100, "description": "per minute"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == 100
    assert body["value_type"] == "int"
    r2 = await client.get("/api/v1/admin/settings")
    assert r2.status_code == 200
    assert any(s["key"] == "rate_limit" for s in r2.json())
    r3 = await client.get("/api/v1/admin/settings/rate_limit")
    assert r3.status_code == 200
    r4 = await client.delete("/api/v1/admin/settings/rate_limit")
    assert r4.status_code == 204
    r5 = await client.delete("/api/v1/admin/settings/rate_limit")
    assert r5.status_code == 404


@pytest.mark.asyncio
async def test_api_user_not_found(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/users/missing-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_role_not_found(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/roles/missing-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_built_in_role_cannot_be_deleted(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/admin/roles?built_in=true")
    admin = next(i for i in r.json()["items"] if i["name"] == "admin")
    r2 = await client.delete(f"/api/v1/admin/roles/{admin['role_id']}")
    assert r2.status_code == 404
