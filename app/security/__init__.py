"""RegIntel AI — Security Platform (M10.6).

Public surface:

* :class:`JWTIssuer` / :func:`decode_jwt` — RFC 7519 compliant HS256 JWTs.
* :class:`Role` / :class:`Permission` / :func:`require_permission` — RBAC.
* :class:`SecretsManager` — multi-source secret resolution.
* :class:`APIGateway` — CORS, IP allowlist, request signing.
* :class:`ThreatDetector` — suspicious pattern + brute-force detection.
* :class:`AuditReview` — query / filter / export the audit log.
* :class:`SecurityMonitor` — security metrics + alerts.
"""

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
    get_audit_review,
)
from app.security.jwt_auth import (
    JWTConfig,
    JWTIssuer,
    JWTPrincipal,
    TokenPair,
    decode_jwt,
)
from app.security.monitoring import (
    Alert,
    AlertSeverity,
    SecurityMonitor,
    get_security_monitor,
)
from app.security.rbac import (
    Permission,
    Principal,
    Role,
    has_permission,
    require_permission,
    require_role,
)
from app.security.secrets import (
    SecretSource,
    SecretsManager,
    get_secrets_manager,
)
from app.security.threat_detection import (
    ThreatDetector,
    ThreatEvent,
    ThreatLevel,
    ThreatType,
    get_threat_detector,
)

__all__ = [
    "APIGateway",
    "Alert",
    "AlertSeverity",
    "AuditQuery",
    "AuditRecord",
    "AuditReview",
    "CORSConfig",
    "IPAllowList",
    "JWTConfig",
    "JWTIssuer",
    "JWTPrincipal",
    "Permission",
    "Principal",
    "RequestSigner",
    "Role",
    "SecretSource",
    "SecretsManager",
    "SecurityMonitor",
    "ThreatDetector",
    "ThreatEvent",
    "ThreatLevel",
    "ThreatType",
    "TokenPair",
    "decode_jwt",
    "get_audit_review",
    "get_secrets_manager",
    "get_security_monitor",
    "get_threat_detector",
    "has_permission",
    "require_permission",
    "require_role",
]
