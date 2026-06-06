"""Module 8.8 — Enterprise Administration Dashboard API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.schemas.admin import (
    AdminOverview,
    AdminStats,
    AuditDashboard,
    ComplianceDashboard,
    GovernanceDashboard,
    PaginatedRoles,
    PaginatedUsers,
    Permission,
    PlatformSetting,
    PlatformSettingUpdateRequest,
    RBACCheck,
    Role,
    RoleCreateRequest,
    RoleFilter,
    User,
    UserCreateRequest,
    UserFilter,
    UserStatus,
    UserUpdateRequest,
)
from app.services.admin import AdminService
from app.services.observability import get_admin_metrics

router = APIRouter(prefix="/admin", tags=["admin"])


def _service_dep():
    from app.api.dependencies import get_admin_service

    return Depends(get_admin_service)


# ─── Health / Stats ────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_admin_metrics()
    return {
        "status": "ok",
        "module": "admin",
        "metrics": metrics.snapshot(),
    }


@router.get("/stats", response_model=AdminStats)
async def stats(svc: AdminService = _service_dep()) -> AdminStats:
    get_admin_metrics().record_dashboard_view()
    return svc.stats()


# ─── Top-level dashboards ─────────────────────────────────────


@router.get("/overview", response_model=AdminOverview)
async def overview(svc: AdminService = _service_dep()) -> AdminOverview:
    get_admin_metrics().record_dashboard_view()
    return svc.overview()


@router.get("/governance", response_model=GovernanceDashboard)
async def governance_dashboard(
    svc: AdminService = _service_dep(),
) -> GovernanceDashboard:
    get_admin_metrics().record_dashboard_view()
    return svc.governance_dashboard()


@router.get("/audit", response_model=AuditDashboard)
async def audit_dashboard(
    svc: AdminService = _service_dep(),
) -> AuditDashboard:
    get_admin_metrics().record_dashboard_view()
    return svc.audit_dashboard()


@router.get("/compliance", response_model=ComplianceDashboard)
async def compliance_dashboard(
    svc: AdminService = _service_dep(),
) -> ComplianceDashboard:
    get_admin_metrics().record_dashboard_view()
    return svc.compliance_dashboard()


# ─── Users ────────────────────────────────────────────────────


@router.post(
    "/users",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: UserCreateRequest, svc: AdminService = _service_dep()
) -> User:
    return svc.create_user(request)


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    status_filter: Optional[str] = None,
    role_id: Optional[str] = None,
    department: Optional[str] = None,
    text_query: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: AdminService = _service_dep(),
) -> PaginatedUsers:
    flt = UserFilter(
        status=UserStatus(status_filter) if status_filter else None,
        role_id=role_id or None,
        department=department or None,
        text_query=text_query or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.list_users(flt)


@router.get("/users/{user_id}", response_model=User)
async def get_user(
    user_id: str, svc: AdminService = _service_dep()
) -> User:
    u = svc.get_user(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    return u


@router.patch("/users/{user_id}", response_model=User)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    svc: AdminService = _service_dep(),
) -> User:
    u = svc.update_user(user_id, request)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    return u


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str, svc: AdminService = _service_dep()
) -> Response:
    if not svc.delete_user(user_id):
        raise HTTPException(status_code=404, detail="user not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/login", response_model=User)
async def record_login(
    user_id: str, svc: AdminService = _service_dep()
) -> User:
    u = svc.record_login(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    get_admin_metrics().record_login()
    return u


# ─── Roles ────────────────────────────────────────────────────


@router.post(
    "/roles",
    response_model=Role,
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    request: RoleCreateRequest, svc: AdminService = _service_dep()
) -> Role:
    return svc.create_role(request)


@router.get("/roles", response_model=PaginatedRoles)
async def list_roles(
    built_in: Optional[bool] = None,
    text_query: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: AdminService = _service_dep(),
) -> PaginatedRoles:
    flt = RoleFilter(
        built_in=built_in,
        text_query=text_query or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.list_roles(flt)


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(
    role_id: str, svc: AdminService = _service_dep()
) -> Role:
    r = svc.get_role(role_id)
    if r is None:
        raise HTTPException(status_code=404, detail="role not found")
    return r


@router.patch("/roles/{role_id}/permissions", response_model=Role)
async def update_role_permissions(
    role_id: str,
    permissions: List[Permission],
    svc: AdminService = _service_dep(),
) -> Role:
    r = svc.update_role_permissions(role_id, permissions)
    if r is None:
        raise HTTPException(status_code=404, detail="role not found")
    return r


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str, svc: AdminService = _service_dep()
) -> Response:
    if not svc.delete_role(role_id):
        raise HTTPException(
            status_code=404, detail="role not found or built-in"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── RBAC ────────────────────────────────────────────────────


@router.post(
    "/users/{user_id}/roles/{role_id}",
    response_model=User,
)
async def grant_role(
    user_id: str,
    role_id: str,
    svc: AdminService = _service_dep(),
) -> User:
    u = svc.grant_role(user_id, role_id)
    if u is None:
        raise HTTPException(status_code=404, detail="user or role not found")
    return u


@router.delete(
    "/users/{user_id}/roles/{role_id}",
)
async def revoke_role(
    user_id: str,
    role_id: str,
    svc: AdminService = _service_dep(),
) -> Response:
    u = svc.revoke_role(user_id, role_id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/rbac/{user_id}", response_model=RBACCheck)
async def rbac_check(
    user_id: str,
    permission: str,
    svc: AdminService = _service_dep(),
) -> RBACCheck:
    check = svc.rbac_check(user_id, permission)
    get_admin_metrics().record_rbac_check(allowed=check.allowed)
    return check


# ─── Platform settings ───────────────────────────────────────


@router.get("/settings", response_model=List[PlatformSetting])
async def list_settings(
    svc: AdminService = _service_dep(),
) -> List[PlatformSetting]:
    return svc.list_settings()


@router.get("/settings/{key}", response_model=PlatformSetting)
async def get_setting(
    key: str, svc: AdminService = _service_dep()
) -> PlatformSetting:
    s = svc.get_setting(key)
    if s is None:
        raise HTTPException(status_code=404, detail="setting not found")
    return s


@router.put("/settings/{key}", response_model=PlatformSetting)
async def set_setting(
    key: str,
    request: PlatformSettingUpdateRequest,
    svc: AdminService = _service_dep(),
) -> PlatformSetting:
    return svc.set_setting(key, request)


@router.delete("/settings/{key}")
async def delete_setting(
    key: str, svc: AdminService = _service_dep()
) -> Response:
    if not svc.delete_setting(key):
        raise HTTPException(status_code=404, detail="setting not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
