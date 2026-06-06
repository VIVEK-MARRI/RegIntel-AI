"""Module 8.8 — Enterprise Administration Dashboard contracts.

Pydantic v2 with ``extra="forbid"`` for all models. The Admin module
brings together user management, role-based access control (RBAC),
platform configuration, and the four top-level dashboards that
enterprise operators interact with.

Public surface
--------------
* ``UserStatus`` / ``User`` / ``Permission`` / ``Role``
* ``UserCreateRequest`` / ``UserUpdateRequest`` / ``RoleCreateRequest``
* ``PlatformSetting`` / ``PlatformSettingUpdateRequest``
* ``AdminOverview`` / ``GovernanceDashboard`` / ``AuditDashboard``
  / ``ComplianceDashboard``
* ``UserFilter`` / ``PaginatedUsers`` / ``RoleFilter`` / ``PaginatedRoles``
* ``AdminStats``
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────────


class UserStatus(str, Enum):
    """Lifecycle states for a :class:`User`."""

    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class BuiltInRole(str, Enum):
    """Built-in RBAC roles seeded by the platform."""

    ADMIN = "admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    RISK_MANAGER = "risk_manager"
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    AUDITOR = "auditor"
    VIEWER = "viewer"


# ─── Permissions and roles ───────────────────────────────────────


class Permission(BaseModel):
    """A single permission on a resource."""

    model_config = ConfigDict(extra="forbid")

    permission_id: str = Field(
        default_factory=lambda: f"prm-{secrets.token_hex(4)}"
    )
    code: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    resource: str = ""
    action: str = ""  # "read" | "write" | "delete" | "execute" | ...


class Role(BaseModel):
    """A role that bundles a set of permissions."""

    model_config = ConfigDict(extra="forbid")

    role_id: str = Field(
        default_factory=lambda: f"role-{uuid.uuid4().hex[:12]}"
    )
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    built_in: bool = False
    permissions: List[Permission] = Field(default_factory=list)
    user_count: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    tags: List[str] = Field(default_factory=list)


# ─── Users ────────────────────────────────────────────────────────


class User(BaseModel):
    """A platform user."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(
        default_factory=lambda: f"usr-{uuid.uuid4().hex[:12]}"
    )
    username: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=300)
    full_name: str = ""
    role_ids: List[str] = Field(default_factory=list)
    status: UserStatus = UserStatus.ACTIVE
    department: str = ""
    last_login_at: Optional[float] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserCreateRequest(BaseModel):
    """Request to create a new user."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=300)
    full_name: str = ""
    role_ids: List[str] = Field(default_factory=list)
    department: str = ""
    status: UserStatus = UserStatus.ACTIVE
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserUpdateRequest(BaseModel):
    """Request to update an existing user."""

    model_config = ConfigDict(extra="forbid")

    email: Optional[str] = None
    full_name: Optional[str] = None
    role_ids: Optional[List[str]] = None
    department: Optional[str] = None
    status: Optional[UserStatus] = None
    metadata: Optional[Dict[str, Any]] = None


class UserFilter(BaseModel):
    """Query filter for users."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[UserStatus] = None
    role_id: Optional[str] = None
    department: Optional[str] = None
    text_query: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedUsers(BaseModel):
    """A page of users."""

    model_config = ConfigDict(extra="forbid")

    items: List[User] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# ─── Roles (CRUD payloads) ───────────────────────────────────────


class RoleCreateRequest(BaseModel):
    """Request to create a new role."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    permissions: List[Permission] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class RoleFilter(BaseModel):
    """Query filter for roles."""

    model_config = ConfigDict(extra="forbid")

    built_in: Optional[bool] = None
    text_query: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedRoles(BaseModel):
    """A page of roles."""

    model_config = ConfigDict(extra="forbid")

    items: List[Role] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# ─── Platform settings ───────────────────────────────────────────


class PlatformSetting(BaseModel):
    """A single key/value platform setting with provenance."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=200)
    value: Any = None
    description: str = ""
    category: str = "general"
    updated_at: float = Field(default_factory=time.time)
    updated_by: str = "system"
    is_secret: bool = False
    value_type: str = "string"  # "string" | "int" | "float" | "bool" | "json"


class PlatformSettingUpdateRequest(BaseModel):
    """Request to update a platform setting."""

    model_config = ConfigDict(extra="forbid")

    value: Any
    description: Optional[str] = None
    updated_by: str = "system"
    category: Optional[str] = None


# ─── Dashboards ───────────────────────────────────────────────────


class AdminOverview(BaseModel):
    """Top-level admin overview card."""

    model_config = ConfigDict(extra="forbid")

    total_users: int = 0
    active_users: int = 0
    total_roles: int = 0
    total_policies: int = 0
    total_decisions: int = 0
    total_audit_records: int = 0
    total_reports: int = 0
    total_workflows: int = 0
    total_reviews: int = 0
    compliance_rate: float = 0.0
    approval_rate: float = 0.0
    generated_at: float = Field(default_factory=time.time)


class GovernanceDashboard(BaseModel):
    """Governance-focused dashboard metrics."""

    model_config = ConfigDict(extra="forbid")

    total_policies: int = 0
    enabled_policies: int = 0
    total_rules: int = 0
    total_decisions: int = 0
    compliant_decisions: int = 0
    non_compliant_decisions: int = 0
    total_violations: int = 0
    blocking_violations: int = 0
    compliance_rate: float = 0.0
    average_violations_per_decision: float = 0.0
    by_decision_type: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_action: Dict[str, int] = Field(default_factory=dict)
    by_model: Dict[str, int] = Field(default_factory=dict)
    top_violated_rules: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: float = Field(default_factory=time.time)


class AuditDashboard(BaseModel):
    """Audit-focused dashboard metrics."""

    model_config = ConfigDict(extra="forbid")

    total_records: int = 0
    chain_length: int = 0
    chain_integrity: bool = True
    last_chain_hash: str = ""
    by_action: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_actor: Dict[str, int] = Field(default_factory=dict)
    by_module: Dict[str, int] = Field(default_factory=dict)
    by_subject_type: Dict[str, int] = Field(default_factory=dict)
    top_actors: List[Dict[str, Any]] = Field(default_factory=list)
    last_record_at: Optional[float] = None
    oldest_record_at: Optional[float] = None
    generated_at: float = Field(default_factory=time.time)


class ComplianceDashboard(BaseModel):
    """Compliance-focused dashboard metrics."""

    model_config = ConfigDict(extra="forbid")

    total_reports: int = 0
    reports_complete: int = 0
    reports_in_progress: int = 0
    reports_failed: int = 0
    reports_archived: int = 0
    by_kind: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_regulator: Dict[str, int] = Field(default_factory=dict)
    total_evidence: int = 0
    total_lineages: int = 0
    average_report_sections: float = 0.0
    last_report_at: Optional[float] = None
    generated_at: float = Field(default_factory=time.time)


class AdminStats(BaseModel):
    """High-level admin stats card."""

    model_config = ConfigDict(extra="forbid")

    total_users: int = 0
    active_users: int = 0
    suspended_users: int = 0
    total_roles: int = 0
    built_in_roles: int = 0
    total_permissions: int = 0
    total_settings: int = 0
    secret_settings: int = 0
    by_role: Dict[str, int] = Field(default_factory=dict)
    by_user_status: Dict[str, int] = Field(default_factory=dict)
    generated_at: float = Field(default_factory=time.time)


# ─── RBAC result ─────────────────────────────────────────────────


class RBACCheck(BaseModel):
    """The verdict of a permission check."""

    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(
        default_factory=lambda: f"rbac-{secrets.token_hex(4)}"
    )
    user_id: str
    permission_code: str
    allowed: bool = False
    reason: str = ""
    matched_roles: List[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


__all__ = [
    "UserStatus",
    "BuiltInRole",
    "Permission",
    "Role",
    "User",
    "UserCreateRequest",
    "UserUpdateRequest",
    "UserFilter",
    "PaginatedUsers",
    "RoleCreateRequest",
    "RoleFilter",
    "PaginatedRoles",
    "PlatformSetting",
    "PlatformSettingUpdateRequest",
    "AdminOverview",
    "GovernanceDashboard",
    "AuditDashboard",
    "ComplianceDashboard",
    "AdminStats",
    "RBACCheck",
]
