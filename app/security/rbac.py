"""Role-Based Access Control (M10.6).

Defines :class:`Role`, :class:`Permission`, and a couple of decorator
helpers used by the FastAPI security layer to enforce authorization.

Default roles (least-privilege defaults):

* ``viewer``     — read-only access to public endpoints
* ``analyst``    — read + invoke copilot + run research / compliance
* ``operator``   — analyst + workflow execution + monitoring
* ``auditor``    — read-only access to audit, governance, compliance
* ``admin``      — full system access (user / role management)
* ``service``    — service-to-service auth for backplane / workers
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Mapping, Set, Tuple

from app.security.jwt_auth import JWTPrincipal


# ─── Enums ───────────────────────────────────────────────────────────


class Permission(str, Enum):
    """The permission scopes understood by the platform.

    New permissions MUST be added here (and only here) so that the
    validator, the audit layer, and the documentation stay in sync.
    """

    # Read scopes
    READ_PUBLIC = "read:public"
    READ_DOCUMENTS = "read:documents"
    READ_COPILOT = "read:copilot"
    READ_RESEARCH = "read:research"
    READ_COMPLIANCE = "read:compliance"
    READ_RISK = "read:risk"
    READ_KNOWLEDGE_GRAPH = "read:knowledge_graph"
    READ_AGENTS = "read:agents"
    READ_ANALYTICS = "read:analytics"
    READ_GOVERNANCE = "read:governance"
    READ_AUDIT = "read:audit"
    READ_ADMIN = "read:admin"
    READ_SECURITY = "read:security"

    # Write scopes
    WRITE_DOCUMENTS = "write:documents"
    WRITE_COPILOT = "write:copilot"
    WRITE_RESEARCH = "write:research"
    WRITE_COMPLIANCE = "write:compliance"
    WRITE_RISK = "write:risk"
    WRITE_KNOWLEDGE_GRAPH = "write:knowledge_graph"
    WRITE_AGENTS = "write:agents"
    WRITE_GOVERNANCE = "write:governance"
    WRITE_AUDIT = "write:audit"
    WRITE_ADMIN = "write:admin"
    WRITE_SECURITY = "write:security"

    # Operational scopes
    EXECUTE_WORKFLOWS = "exec:workflows"
    EXECUTE_AGENTS = "exec:agents"
    EXECUTE_INGESTION = "exec:ingestion"
    EXECUTE_BENCHMARKS = "exec:benchmarks"
    MANAGE_USERS = "manage:users"
    MANAGE_KEYS = "manage:keys"
    MANAGE_SECRETS = "manage:secrets"
    MANAGE_THREATS = "manage:threats"
    REVIEW_AUDIT = "review:audit"

    # Special
    SERVICE_TICKET = "service:ticket"


class Role(str, Enum):
    """Built-in roles. Add new roles here."""

    VIEWER = "viewer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    ADMIN = "admin"
    SERVICE = "service"


# ─── Default role → permission map ───────────────────────────────────


_ROLE_PERMISSIONS: Mapping[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.READ_PUBLIC,
        Permission.READ_DOCUMENTS,
        Permission.READ_COPILOT,
        Permission.READ_RESEARCH,
        Permission.READ_COMPLIANCE,
        Permission.READ_RISK,
        Permission.READ_KNOWLEDGE_GRAPH,
        Permission.READ_AGENTS,
        Permission.READ_ANALYTICS,
    },
    Role.ANALYST: {
        Permission.READ_PUBLIC,
        Permission.READ_DOCUMENTS,
        Permission.READ_COPILOT,
        Permission.WRITE_COPILOT,
        Permission.READ_RESEARCH,
        Permission.WRITE_RESEARCH,
        Permission.READ_COMPLIANCE,
        Permission.READ_RISK,
        Permission.READ_KNOWLEDGE_GRAPH,
        Permission.READ_AGENTS,
        Permission.READ_ANALYTICS,
        Permission.EXECUTE_AGENTS,
    },
    Role.OPERATOR: {
        # Inherits everything analyst can do plus operational scopes.
        Permission.READ_PUBLIC,
        Permission.READ_DOCUMENTS,
        Permission.WRITE_DOCUMENTS,
        Permission.READ_COPILOT,
        Permission.WRITE_COPILOT,
        Permission.READ_RESEARCH,
        Permission.WRITE_RESEARCH,
        Permission.READ_COMPLIANCE,
        Permission.WRITE_COMPLIANCE,
        Permission.READ_RISK,
        Permission.WRITE_RISK,
        Permission.READ_KNOWLEDGE_GRAPH,
        Permission.WRITE_KNOWLEDGE_GRAPH,
        Permission.READ_AGENTS,
        Permission.WRITE_AGENTS,
        Permission.READ_ANALYTICS,
        Permission.READ_GOVERNANCE,
        Permission.READ_AUDIT,
        Permission.EXECUTE_WORKFLOWS,
        Permission.EXECUTE_AGENTS,
        Permission.EXECUTE_INGESTION,
        Permission.EXECUTE_BENCHMARKS,
    },
    Role.AUDITOR: {
        Permission.READ_PUBLIC,
        Permission.READ_DOCUMENTS,
        Permission.READ_COPILOT,
        Permission.READ_RESEARCH,
        Permission.READ_COMPLIANCE,
        Permission.READ_RISK,
        Permission.READ_KNOWLEDGE_GRAPH,
        Permission.READ_AGENTS,
        Permission.READ_ANALYTICS,
        Permission.READ_GOVERNANCE,
        Permission.READ_AUDIT,
        Permission.REVIEW_AUDIT,
    },
    Role.ADMIN: set(Permission),  # full access
    Role.SERVICE: {
        Permission.READ_PUBLIC,
        Permission.READ_DOCUMENTS,
        Permission.READ_COPILOT,
        Permission.WRITE_COPILOT,
        Permission.READ_AGENTS,
        Permission.WRITE_AGENTS,
        Permission.EXECUTE_AGENTS,
        Permission.EXECUTE_WORKFLOWS,
        Permission.EXECUTE_INGESTION,
        Permission.SERVICE_TICKET,
    },
}


# ─── Principal + helper ─────────────────────────────────────────────


@dataclass(frozen=True)
class Principal:
    """A resolved authorization subject."""

    subject_id: str
    roles: Tuple[Role, ...] = ()
    scopes: Tuple[Permission, ...] = ()
    extra_claims: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_jwt(cls, principal: JWTPrincipal) -> "Principal":
        roles: List[Role] = []
        for r in principal.roles:
            try:
                roles.append(Role(r))
            except ValueError:
                # Unknown role → silently ignore to avoid privilege escalation
                continue
        scopes: List[Permission] = []
        for s in principal.scopes:
            try:
                scopes.append(Permission(s))
            except ValueError:
                continue
        return cls(
            subject_id=principal.sub,
            roles=tuple(roles),
            scopes=tuple(scopes),
            extra_claims=principal.raw_claims,
        )

    def permissions(self) -> Set[Permission]:
        perms: Set[Permission] = set(self.scopes)
        for role in self.roles:
            perms.update(_ROLE_PERMISSIONS.get(role, set()))
        return perms

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions()


# ─── Public helpers ──────────────────────────────────────────────────


def has_permission(principal: Principal, permission: Permission) -> bool:
    return principal.has_permission(permission)


def role_permissions(role: Role) -> Set[Permission]:
    return set(_ROLE_PERMISSIONS.get(role, set()))


# ─── Decorators ──────────────────────────────────────────────────────


def require_role(*roles: Role) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: reject the call unless the principal has at least one of ``roles``."""
    required = set(roles)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = kwargs.get("principal")
            if principal is None or not isinstance(principal, Principal):
                raise PermissionError("missing principal")
            if not (set(principal.roles) & required):
                raise PermissionError(
                    f"role required: {sorted(r.value for r in required)}"
                )
            return await fn(*args, **kwargs)

        wrapper.__required_roles__ = required  # type: ignore[attr-defined]
        return wrapper

    return decorator


def require_permission(*permissions: Permission) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: reject the call unless the principal has all listed permissions."""
    required = set(permissions)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = kwargs.get("principal")
            if principal is None or not isinstance(principal, Principal):
                raise PermissionError("missing principal")
            granted = principal.permissions()
            missing = required - granted
            if missing:
                raise PermissionError(
                    f"missing permissions: {sorted(p.value for p in missing)}"
                )
            return await fn(*args, **kwargs)

        wrapper.__required_permissions__ = required  # type: ignore[attr-defined]
        return wrapper

    return decorator
