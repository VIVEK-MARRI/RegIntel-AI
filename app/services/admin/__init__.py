"""Module 8.8 — Enterprise Administration Dashboard.

Public surface
--------------
* ``UserManagement``          — CRUD over :class:`User`
* ``RoleManager``             — CRUD over :class:`Role` + RBAC checks
* ``PlatformSettingsManager`` — typed key/value settings
* ``AdminDashboardService``   — top-level dashboard aggregation
* ``AdminStore`` (ABC) + ``InMemoryAdminStore``
* ``AdminService``            — DI facade
* ``build_default_admin_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.admin import (
    AdminOverview,
    AdminStats,
    AuditDashboard,
    BuiltInRole,
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
from app.services.observability import (
    get_admin_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Permission catalog (built-in role → permission codes) ────


_BUILT_IN_PERMISSIONS: Dict[str, List[str]] = {
    BuiltInRole.ADMIN.value: ["*"],  # wildcard
    BuiltInRole.COMPLIANCE_OFFICER.value: [
        "governance.read",
        "governance.write",
        "audit.read",
        "compliance.read",
        "compliance.write",
        "risk.read",
        "review.read",
        "review.write",
    ],
    BuiltInRole.RISK_MANAGER.value: [
        "governance.read",
        "risk.read",
        "risk.write",
        "forecast.read",
        "review.read",
    ],
    BuiltInRole.REVIEWER.value: [
        "review.read",
        "review.write",
        "workflow.read",
    ],
    BuiltInRole.ANALYST.value: [
        "governance.read",
        "risk.read",
        "forecast.read",
        "workflow.read",
        "dashboard.read",
    ],
    BuiltInRole.AUDITOR.value: [
        "audit.read",
        "compliance.read",
        "governance.read",
    ],
    BuiltInRole.VIEWER.value: [
        "dashboard.read",
    ],
}


_BUILT_IN_ROLE_DESCRIPTIONS: Dict[str, str] = {
    BuiltInRole.ADMIN.value: "Full administrative access to all resources.",
    BuiltInRole.COMPLIANCE_OFFICER.value: (
        "Owns policies, audit, and compliance reporting."
    ),
    BuiltInRole.RISK_MANAGER.value: (
        "Manages risk assessments, forecasts, and risk-related reviews."
    ),
    BuiltInRole.REVIEWER.value: (
        "Performs human-in-the-loop reviews and workflow tasks."
    ),
    BuiltInRole.ANALYST.value: (
        "Read-only access to governance, risk, forecast and dashboard data."
    ),
    BuiltInRole.AUDITOR.value: (
        "Read-only access to audit logs and compliance reports."
    ),
    BuiltInRole.VIEWER.value: "Read-only access to dashboards.",
}


_BUILT_IN_ROLE_TAGS: Dict[str, List[str]] = {
    BuiltInRole.ADMIN.value: ["built-in", "privileged"],
    BuiltInRole.COMPLIANCE_OFFICER.value: ["built-in", "compliance"],
    BuiltInRole.RISK_MANAGER.value: ["built-in", "risk"],
    BuiltInRole.REVIEWER.value: ["built-in", "operations"],
    BuiltInRole.ANALYST.value: ["built-in", "analytics"],
    BuiltInRole.AUDITOR.value: ["built-in", "audit"],
    BuiltInRole.VIEWER.value: ["built-in", "read-only"],
}


# ─── UserManagement ─────────────────────────────────────────────


class UserManagement:
    """CRUD over :class:`User` records."""

    def __init__(self, store: "InMemoryAdminStore") -> None:
        self._store = store

    def create(
        self, request: UserCreateRequest, actor: str = "system"
    ) -> User:
        with track_request(
            endpoint="/api/v1/admin/users/create",
            strategy="user_create",
        ):
            user = User(
                username=request.username,
                email=request.email,
                full_name=request.full_name,
                role_ids=request.role_ids,
                status=request.status,
                department=request.department,
                metadata=request.metadata,
            )
            self._store.add_user(user)
            get_admin_metrics().record_user_created(request.status.value)
            return user

    def get(self, user_id: str) -> Optional[User]:
        return self._store.get_user(user_id)

    def get_by_username(self, username: str) -> Optional[User]:
        return self._store.get_user_by_username(username)

    def list(self, flt: UserFilter) -> PaginatedUsers:
        items = self._store.list_users(flt)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedUsers(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def list_all(self) -> List[User]:
        return self._store.list_users_unfiltered()

    def update(
        self, user_id: str, request: UserUpdateRequest
    ) -> Optional[User]:
        user = self._store.get_user(user_id)
        if user is None:
            return None
        if request.email is not None:
            user.email = request.email
        if request.full_name is not None:
            user.full_name = request.full_name
        if request.role_ids is not None:
            user.role_ids = request.role_ids
        if request.department is not None:
            user.department = request.department
        if request.status is not None:
            user.status = request.status
        if request.metadata is not None:
            user.metadata = request.metadata
        user.updated_at = time.time()
        self._store.update_user(user)
        get_admin_metrics().record_user_updated(request.status.value if request.status else "unchanged")
        return user

    def record_login(self, user_id: str) -> Optional[User]:
        user = self._store.get_user(user_id)
        if user is None:
            return None
        user.last_login_at = time.time()
        self._store.update_user(user)
        return user

    def delete(self, user_id: str) -> bool:
        return self._store.delete_user(user_id)


# ─── RoleManager ────────────────────────────────────────────────


class RoleManager:
    """CRUD over :class:`Role` and RBAC checks."""

    def __init__(self, store: "InMemoryAdminStore") -> None:
        self._store = store

    def create(
        self, request: RoleCreateRequest, actor: str = "system"
    ) -> Role:
        with track_request(
            endpoint="/api/v1/admin/roles/create",
            strategy="role_create",
        ):
            role = Role(
                name=request.name,
                description=request.description,
                permissions=request.permissions,
                tags=request.tags,
            )
            self._store.add_role(role)
            get_admin_metrics().record_role_created(permission_count=len(request.permissions))
            return role

    def get(self, role_id: str) -> Optional[Role]:
        return self._store.get_role(role_id)

    def get_by_name(self, name: str) -> Optional[Role]:
        return self._store.get_role_by_name(name)

    def list(self, flt: RoleFilter) -> PaginatedRoles:
        items = self._store.list_roles(flt)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedRoles(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def list_all(self) -> List[Role]:
        return self._store.list_roles_unfiltered()

    def update_permissions(
        self, role_id: str, permissions: List[Permission]
    ) -> Optional[Role]:
        role = self._store.get_role(role_id)
        if role is None:
            return None
        role.permissions = permissions
        role.updated_at = time.time()
        self._store.update_role(role)
        return role

    def delete(self, role_id: str) -> bool:
        role = self._store.get_role(role_id)
        if role is None:
            return False
        if role.built_in:
            return False
        return self._store.delete_role(role_id)

    # ─── RBAC ──────────────────────────────────────────────

    def permissions_for_user(self, user: User) -> List[str]:
        """Aggregate permission codes granted to ``user`` via their roles."""
        codes: List[str] = []
        for rid in user.role_ids:
            role = self._store.get_role(rid)
            if role is None:
                continue
            for p in role.permissions:
                if p.code not in codes:
                    codes.append(p.code)
        return codes

    def check(
        self,
        user_id: str,
        permission_code: str,
    ) -> RBACCheck:
        """Check whether ``user_id`` has ``permission_code``."""
        user = self._store.get_user(user_id)
        if user is None:
            return RBACCheck(
                user_id=user_id,
                permission_code=permission_code,
                allowed=False,
                reason="user not found",
            )
        if user.status != UserStatus.ACTIVE:
            return RBACCheck(
                user_id=user_id,
                permission_code=permission_code,
                allowed=False,
                reason=f"user status is {user.status.value}",
            )
        codes = self.permissions_for_user(user)
        matched_roles = [
            rid for rid in user.role_ids
            if any(p.code == permission_code or p.code == "*"
                   for p in (self._store.get_role(rid).permissions
                             if self._store.get_role(rid) else []))
        ]
        allowed = "*" in codes or permission_code in codes
        return RBACCheck(
            user_id=user_id,
            permission_code=permission_code,
            allowed=allowed,
            reason="" if allowed else "permission not granted",
            matched_roles=matched_roles,
        )

    def grant_role(self, user_id: str, role_id: str) -> Optional[User]:
        user = self._store.get_user(user_id)
        role = self._store.get_role(role_id)
        if user is None or role is None:
            return None
        if role_id not in user.role_ids:
            user.role_ids.append(role_id)
            user.updated_at = time.time()
            self._store.update_user(user)
        return user

    def revoke_role(self, user_id: str, role_id: str) -> Optional[User]:
        user = self._store.get_user(user_id)
        if user is None:
            return None
        if role_id in user.role_ids:
            user.role_ids.remove(role_id)
            user.updated_at = time.time()
            self._store.update_user(user)
        return user


# ─── PlatformSettingsManager ──────────────────────────────────


class PlatformSettingsManager:
    """Typed key/value platform configuration."""

    def __init__(self, store: "InMemoryAdminStore") -> None:
        self._store = store

    def get(self, key: str) -> Optional[PlatformSetting]:
        return self._store.get_setting(key)

    def list_all(self) -> List[PlatformSetting]:
        return self._store.list_settings()

    def list_by_category(self, category: str) -> List[PlatformSetting]:
        return [s for s in self._store.list_settings() if s.category == category]

    def set(
        self, request: PlatformSettingUpdateRequest, *, key: str
    ) -> PlatformSetting:
        with track_request(
            endpoint="/api/v1/admin/settings/set",
            strategy="setting_set",
        ):
            existing = self._store.get_setting(key)
            value_type = self._infer_type(request.value)
            if existing is not None:
                existing.value = request.value
                existing.value_type = value_type
                if request.description is not None:
                    existing.description = request.description
                if request.category is not None:
                    existing.category = request.category
                existing.updated_at = time.time()
                existing.updated_by = request.updated_by
                self._store.update_setting(existing)
                setting = existing
            else:
                setting = PlatformSetting(
                    key=key,
                    value=request.value,
                    description=request.description or "",
                    category=request.category or "general",
                    updated_at=time.time(),
                    updated_by=request.updated_by,
                    value_type=value_type,
                )
                self._store.add_setting(setting)
            get_admin_metrics().record_setting_change(setting.category)
            return setting

    @staticmethod
    def _infer_type(value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, (dict, list)):
            return "json"
        return "string"

    def delete(self, key: str) -> bool:
        return self._store.delete_setting(key)


# ─── AdminDashboardService ────────────────────────────────────


class AdminDashboardService:
    """Top-level dashboard aggregation across all modules."""

    def __init__(
        self,
        store: "InMemoryAdminStore",
        *,
        governance_service: Any = None,
        audit_service: Any = None,
        workflow_service: Any = None,
        review_service: Any = None,
    ) -> None:
        self._store = store
        self.governance_service = governance_service
        self.audit_service = audit_service
        self.workflow_service = workflow_service
        self.review_service = review_service

    def bind(
        self,
        *,
        governance_service: Any = None,
        audit_service: Any = None,
        workflow_service: Any = None,
        review_service: Any = None,
    ) -> None:
        """Late-bind (or update) cross-module service references."""
        if governance_service is not None:
            self.governance_service = governance_service
        if audit_service is not None:
            self.audit_service = audit_service
        if workflow_service is not None:
            self.workflow_service = workflow_service
        if review_service is not None:
            self.review_service = review_service

    # ─── overview ─────────────────────────────────────────

    def overview(self) -> AdminOverview:
        users = self._store.list_users_unfiltered()
        roles = self._store.list_roles_unfiltered()
        settings_list = self._store.list_settings()

        total_policies = total_decisions = total_audit = total_reports = 0
        compliance_rate = approval_rate = 0.0

        if self.governance_service is not None:
            try:
                gov_stats = self.governance_service.stats()
                total_policies = gov_stats.total_policies
                total_decisions = gov_stats.total_decisions
                compliance_rate = gov_stats.compliance_rate
            except Exception:  # pragma: no cover
                pass
        if self.audit_service is not None:
            try:
                audit_stats = self.audit_service.stats()
                total_audit = audit_stats.total_records
                total_reports = len(self.audit_service.list_reports())
            except Exception:  # pragma: no cover
                pass
        if self.review_service is not None:
            try:
                rev_stats = self.review_service.stats()
                approval_rate = rev_stats.approval_rate
            except Exception:  # pragma: no cover
                pass

        total_workflows = total_reviews = 0
        if self.workflow_service is not None:
            try:
                wf_stats = self.workflow_service.stats()
                total_workflows = wf_stats.total_workflows
            except Exception:  # pragma: no cover
                pass
        if self.review_service is not None:
            try:
                rev_stats = self.review_service.stats()
                total_reviews = rev_stats.total_reviews
            except Exception:  # pragma: no cover
                pass

        return AdminOverview(
            total_users=len(users),
            active_users=sum(1 for u in users if u.status == UserStatus.ACTIVE),
            total_roles=len(roles),
            total_policies=total_policies,
            total_decisions=total_decisions,
            total_audit_records=total_audit,
            total_reports=total_reports,
            total_workflows=total_workflows,
            total_reviews=total_reviews,
            compliance_rate=compliance_rate,
            approval_rate=approval_rate,
        )

    # ─── governance dashboard ──────────────────────────────

    def governance_dashboard(self) -> GovernanceDashboard:
        if self.governance_service is None:
            return GovernanceDashboard()
        s = self.governance_service.stats()
        return GovernanceDashboard(
            total_policies=s.total_policies,
            enabled_policies=s.total_policies,
            total_rules=s.total_rules,
            total_decisions=s.total_decisions,
            compliant_decisions=s.compliant_decisions,
            non_compliant_decisions=s.non_compliant_decisions,
            total_violations=s.total_violations,
            blocking_violations=s.blocking_violations,
            compliance_rate=s.compliance_rate,
            average_violations_per_decision=s.average_violations_per_decision,
            by_decision_type=s.by_decision_type,
            by_severity=s.by_severity,
            by_action=s.by_action,
            by_model=s.by_model,
        )

    # ─── audit dashboard ───────────────────────────────────

    def audit_dashboard(self) -> AuditDashboard:
        if self.audit_service is None:
            return AuditDashboard()
        s = self.audit_service.stats()
        # Build "top actors" list
        top_actors = [
            {"actor": actor, "count": count}
            for actor, count in sorted(
                s.by_actor.items(), key=lambda kv: kv[1], reverse=True
            )[:5]
        ]
        return AuditDashboard(
            total_records=s.total_records,
            chain_length=s.chain_length,
            chain_integrity=s.chain_integrity,
            last_chain_hash=s.last_chain_hash,
            by_action=s.by_action,
            by_severity=s.by_severity,
            by_actor=s.by_actor,
            by_module=s.by_module,
            by_subject_type=s.by_subject_type,
            top_actors=top_actors,
            last_record_at=s.last_record_at,
            oldest_record_at=s.oldest_record_at,
        )

    # ─── compliance dashboard ──────────────────────────────

    def compliance_dashboard(self) -> ComplianceDashboard:
        if self.audit_service is None:
            return ComplianceDashboard()
        reports = self.audit_service.list_reports()
        by_kind: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        by_regulator: Dict[str, int] = {}
        total_sections = 0
        for r in reports:
            by_kind[r.kind.value] = by_kind.get(r.kind.value, 0) + 1
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
            if r.regulator:
                by_regulator[r.regulator] = (
                    by_regulator.get(r.regulator, 0) + 1
                )
            total_sections += len(r.sections)
        average_sections = total_sections / max(1, len(reports))
        # Evidence totals
        total_evidence = 0
        try:
            total_evidence = len(self.audit_service.list_evidence())
        except Exception:  # pragma: no cover
            pass
        return ComplianceDashboard(
            total_reports=len(reports),
            reports_complete=by_status.get("complete", 0),
            reports_in_progress=by_status.get("generating", 0),
            reports_failed=by_status.get("failed", 0),
            reports_archived=by_status.get("archived", 0),
            by_kind=by_kind,
            by_status=by_status,
            by_regulator=by_regulator,
            total_evidence=total_evidence,
            average_report_sections=round(average_sections, 3),
            last_report_at=max(
                (r.generated_at for r in reports), default=None
            ),
        )

    # ─── admin stats ───────────────────────────────────────

    def stats(self) -> AdminStats:
        users = self._store.list_users_unfiltered()
        roles = self._store.list_roles_unfiltered()
        settings = self._store.list_settings()
        by_role: Dict[str, int] = {}
        for u in users:
            for rid in u.role_ids:
                by_role[rid] = by_role.get(rid, 0) + 1
        by_status: Dict[str, int] = {}
        for u in users:
            by_status[u.status.value] = (
                by_status.get(u.status.value, 0) + 1
            )
        return AdminStats(
            total_users=len(users),
            active_users=by_status.get("active", 0),
            suspended_users=by_status.get("suspended", 0)
            + by_status.get("disabled", 0),
            total_roles=len(roles),
            built_in_roles=sum(1 for r in roles if r.built_in),
            total_permissions=sum(len(r.permissions) for r in roles),
            total_settings=len(settings),
            secret_settings=sum(1 for s in settings if s.is_secret),
            by_role=by_role,
            by_user_status=by_status,
        )


# ─── InMemoryAdminStore ────────────────────────────────────────


class AdminStore(ABC):
    """Abstract storage for admin data."""

    @abstractmethod
    def add_user(self, user: User) -> None: ...
    @abstractmethod
    def get_user(self, user_id: str) -> Optional[User]: ...
    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[User]: ...
    @abstractmethod
    def list_users(self, flt: UserFilter) -> List[User]: ...
    @abstractmethod
    def list_users_unfiltered(self) -> List[User]: ...
    @abstractmethod
    def update_user(self, user: User) -> None: ...
    @abstractmethod
    def delete_user(self, user_id: str) -> bool: ...

    @abstractmethod
    def add_role(self, role: Role) -> None: ...
    @abstractmethod
    def get_role(self, role_id: str) -> Optional[Role]: ...
    @abstractmethod
    def get_role_by_name(self, name: str) -> Optional[Role]: ...
    @abstractmethod
    def list_roles(self, flt: RoleFilter) -> List[Role]: ...
    @abstractmethod
    def list_roles_unfiltered(self) -> List[Role]: ...
    @abstractmethod
    def update_role(self, role: Role) -> None: ...
    @abstractmethod
    def delete_role(self, role_id: str) -> bool: ...

    @abstractmethod
    def add_setting(self, setting: PlatformSetting) -> None: ...
    @abstractmethod
    def get_setting(self, key: str) -> Optional[PlatformSetting]: ...
    @abstractmethod
    def list_settings(self) -> List[PlatformSetting]: ...
    @abstractmethod
    def update_setting(self, setting: PlatformSetting) -> None: ...
    @abstractmethod
    def delete_setting(self, key: str) -> bool: ...


class InMemoryAdminStore(AdminStore):
    """Thread-safe in-memory admin store with optional JSONL persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._users: Dict[str, User] = {}
        self._users_by_username: Dict[str, str] = {}
        self._roles: Dict[str, Role] = {}
        self._roles_by_name: Dict[str, str] = {}
        self._settings: Dict[str, PlatformSetting] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if persist_path:
            self._load()
        else:
            self._seed_built_in_roles()

    # ─── users ────────────────────────────────────────────

    def add_user(self, user: User) -> None:
        with self._lock:
            self._users[user.user_id] = user
            self._users_by_username[user.username] = user.user_id
            self._persist()

    def get_user(self, user_id: str) -> Optional[User]:
        with self._lock:
            return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._lock:
            uid = self._users_by_username.get(username)
            return self._users.get(uid) if uid else None

    def list_users(self, flt: UserFilter) -> List[User]:
        with self._lock:
            items = list(self._users.values())
        if flt.status is not None:
            items = [u for u in items if u.status == flt.status]
        if flt.role_id is not None:
            items = [u for u in items if flt.role_id in u.role_ids]
        if flt.department is not None:
            items = [u for u in items if u.department == flt.department]
        if flt.text_query:
            q = flt.text_query.lower()
            items = [
                u for u in items
                if q in u.username.lower()
                or q in u.email.lower()
                or q in u.full_name.lower()
            ]
        return sorted(items, key=lambda u: u.created_at)

    def list_users_unfiltered(self) -> List[User]:
        with self._lock:
            items = list(self._users.values())
        return sorted(items, key=lambda u: u.created_at)

    def update_user(self, user: User) -> None:
        with self._lock:
            self._users[user.user_id] = user
            self._users_by_username[user.username] = user.user_id
            self._persist()

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            user = self._users.pop(user_id, None)
            if user is None:
                return False
            self._users_by_username.pop(user.username, None)
            self._persist()
            return True

    # ─── roles ────────────────────────────────────────────

    def add_role(self, role: Role) -> None:
        with self._lock:
            self._roles[role.role_id] = role
            self._roles_by_name[role.name] = role.role_id
            self._persist()

    def get_role(self, role_id: str) -> Optional[Role]:
        with self._lock:
            return self._roles.get(role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        with self._lock:
            rid = self._roles_by_name.get(name)
            return self._roles.get(rid) if rid else None

    def list_roles(self, flt: RoleFilter) -> List[Role]:
        with self._lock:
            items = list(self._roles.values())
        if flt.built_in is not None:
            items = [r for r in items if r.built_in == flt.built_in]
        if flt.text_query:
            q = flt.text_query.lower()
            items = [
                r for r in items
                if q in r.name.lower() or q in r.description.lower()
            ]
        return sorted(items, key=lambda r: r.created_at)

    def list_roles_unfiltered(self) -> List[Role]:
        with self._lock:
            items = list(self._roles.values())
        return sorted(items, key=lambda r: r.created_at)

    def update_role(self, role: Role) -> None:
        with self._lock:
            self._roles[role.role_id] = role
            self._roles_by_name[role.name] = role.role_id
            self._persist()

    def delete_role(self, role_id: str) -> bool:
        with self._lock:
            role = self._roles.pop(role_id, None)
            if role is None:
                return False
            self._roles_by_name.pop(role.name, None)
            self._persist()
            return True

    # ─── settings ─────────────────────────────────────────

    def add_setting(self, setting: PlatformSetting) -> None:
        with self._lock:
            self._settings[setting.key] = setting
            self._persist()

    def get_setting(self, key: str) -> Optional[PlatformSetting]:
        with self._lock:
            return self._settings.get(key)

    def list_settings(self) -> List[PlatformSetting]:
        with self._lock:
            return sorted(
                self._settings.values(), key=lambda s: s.key
            )

    def update_setting(self, setting: PlatformSetting) -> None:
        with self._lock:
            self._settings[setting.key] = setting
            self._persist()

    def delete_setting(self, key: str) -> bool:
        with self._lock:
            existed = key in self._settings
            self._settings.pop(key, None)
            self._persist()
            return existed

    # ─── seed ─────────────────────────────────────────────

    def _seed_built_in_roles(self) -> None:
        """Populate the seven built-in roles with their default permissions."""
        for role_name, perm_codes in _BUILT_IN_PERMISSIONS.items():
            if self._roles_by_name.get(role_name):
                continue
            permissions = [
                Permission(
                    code=code,
                    description=(
                        "Wildcard — full access to all resources."
                        if code == "*"
                        else f"Permission code: {code}"
                    ),
                    resource=code.split(".")[0] if "." in code else "*",
                    action=code.split(".")[-1] if "." in code else "*",
                )
                for code in perm_codes
            ]
            role = Role(
                name=role_name,
                description=_BUILT_IN_ROLE_DESCRIPTIONS.get(role_name, ""),
                built_in=True,
                permissions=permissions,
                tags=_BUILT_IN_ROLE_TAGS.get(role_name, ["built-in"]),
            )
            self._roles[role.role_id] = role
            self._roles_by_name[role.name] = role.role_id

    # ─── persistence ──────────────────────────────────────

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            payload = {
                "users": [
                    json.loads(u.model_dump_json())
                    for u in self._users.values()
                ],
                "roles": [
                    json.loads(r.model_dump_json())
                    for r in self._roles.values()
                ],
                "settings": [
                    json.loads(s.model_dump_json())
                    for s in self._settings.values()
                ],
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception:  # pragma: no cover
            logger.exception("Failed to persist admin store")

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            self._seed_built_in_roles()
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            for raw in payload.get("users", []):
                u = User(**raw)
                self._users[u.user_id] = u
                self._users_by_username[u.username] = u.user_id
            for raw in payload.get("roles", []):
                r = Role(**raw)
                self._roles[r.role_id] = r
                self._roles_by_name[r.name] = r.role_id
            for raw in payload.get("settings", []):
                s = PlatformSetting(**raw)
                self._settings[s.key] = s
            # Make sure the built-in roles always exist
            self._seed_built_in_roles()
        except Exception:  # pragma: no cover
            logger.exception("Failed to load admin store")
            self._seed_built_in_roles()


# ─── AdminService (DI facade) ─────────────────────────────────


class AdminService:
    """Single point of entry for admin operations."""

    def __init__(self, store: InMemoryAdminStore) -> None:
        self.store = store
        self.user_management = UserManagement(store)
        self.role_manager = RoleManager(store)
        self.settings_manager = PlatformSettingsManager(store)
        self.dashboard = AdminDashboardService(store)

    # ─── wiring of cross-module references ────────────────

    def bind(
        self,
        *,
        governance_service: Any = None,
        audit_service: Any = None,
        workflow_service: Any = None,
        review_service: Any = None,
    ) -> None:
        """Late-bind cross-module services for dashboard aggregation."""
        self.dashboard.governance_service = governance_service
        self.dashboard.audit_service = audit_service
        self.dashboard.workflow_service = workflow_service
        self.dashboard.review_service = review_service

    # ─── users ────────────────────────────────────────────

    def create_user(
        self, request: UserCreateRequest
    ) -> User:
        return self.user_management.create(request)

    def get_user(self, user_id: str) -> Optional[User]:
        return self.user_management.get(user_id)

    def list_users(self, flt: UserFilter) -> PaginatedUsers:
        return self.user_management.list(flt)

    def update_user(
        self, user_id: str, request: UserUpdateRequest
    ) -> Optional[User]:
        return self.user_management.update(user_id, request)

    def delete_user(self, user_id: str) -> bool:
        return self.user_management.delete(user_id)

    def record_login(self, user_id: str) -> Optional[User]:
        return self.user_management.record_login(user_id)

    # ─── roles ────────────────────────────────────────────

    def create_role(
        self, request: RoleCreateRequest
    ) -> Role:
        return self.role_manager.create(request)

    def get_role(self, role_id: str) -> Optional[Role]:
        return self.role_manager.get(role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        return self.role_manager.get_by_name(name)

    def list_roles(self, flt: RoleFilter) -> PaginatedRoles:
        return self.role_manager.list(flt)

    def update_role_permissions(
        self, role_id: str, permissions: List[Permission]
    ) -> Optional[Role]:
        return self.role_manager.update_permissions(role_id, permissions)

    def delete_role(self, role_id: str) -> bool:
        return self.role_manager.delete(role_id)

    def grant_role(self, user_id: str, role_id: str) -> Optional[User]:
        return self.role_manager.grant_role(user_id, role_id)

    def revoke_role(self, user_id: str, role_id: str) -> Optional[User]:
        return self.role_manager.revoke_role(user_id, role_id)

    def rbac_check(
        self, user_id: str, permission_code: str
    ) -> RBACCheck:
        return self.role_manager.check(user_id, permission_code)

    # ─── settings ────────────────────────────────────────

    def get_setting(self, key: str) -> Optional[PlatformSetting]:
        return self.settings_manager.get(key)

    def set_setting(
        self, key: str, request: PlatformSettingUpdateRequest
    ) -> PlatformSetting:
        return self.settings_manager.set(request, key=key)

    def list_settings(self) -> List[PlatformSetting]:
        return self.settings_manager.list_all()

    def delete_setting(self, key: str) -> bool:
        return self.settings_manager.delete(key)

    # ─── dashboards ───────────────────────────────────────

    def overview(self) -> AdminOverview:
        return self.dashboard.overview()

    def governance_dashboard(self) -> GovernanceDashboard:
        return self.dashboard.governance_dashboard()

    def audit_dashboard(self) -> AuditDashboard:
        return self.dashboard.audit_dashboard()

    def compliance_dashboard(self) -> ComplianceDashboard:
        return self.dashboard.compliance_dashboard()

    def stats(self) -> AdminStats:
        return self.dashboard.stats()


# ─── Default factory ────────────────────────────────────────────


def build_default_admin_service() -> AdminService:
    """Build a default :class:`AdminService` with a JSONL-backed store."""
    persist_path = os.path.join(
        settings.STORAGE_ROOT, "admin", "admin.jsonl"
    )
    store = InMemoryAdminStore(persist_path=persist_path)
    return AdminService(store)


__all__ = [
    "UserManagement",
    "RoleManager",
    "PlatformSettingsManager",
    "AdminDashboardService",
    "AdminStore",
    "InMemoryAdminStore",
    "AdminService",
    "build_default_admin_service",
    "BuiltInRole",
    "_BUILT_IN_PERMISSIONS",
]
