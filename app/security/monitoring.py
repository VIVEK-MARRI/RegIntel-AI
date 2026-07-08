"""Security monitoring (M10.6).

Aggregates signals from the threat detector, the audit log, and the
secrets manager into a single dashboard. Produces alerts when signals
cross configurable thresholds.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)


# ─── Types ───────────────────────────────────────────────────────────


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    """A single security alert."""

    name: str
    severity: AlertSeverity
    message: str
    timestamp: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─── Monitor ─────────────────────────────────────────────────────────


class SecurityMonitor:
    """In-process security dashboard.

    Pulls signals from:
    * :class:`app.security.threat_detection.ThreatDetector`
    * :class:`app.security.audit_review.AuditReview`
    * :class:`app.security.secrets.SecretsManager` (cache state)

    Exposes an aggregate dashboard via :meth:`dashboard` and emits
    :class:`Alert` records when configurable thresholds are exceeded.
    """

    def __init__(
        self,
        *,
        threat_detector: Any = None,
        audit_review: Any = None,
        secrets_manager: Any = None,
        high_threat_threshold: int = 5,
        critical_threat_threshold: int = 1,
        max_alerts: int = 200,
    ) -> None:
        self._threat = threat_detector
        self._audit = audit_review
        self._secrets = secrets_manager
        self._high_threat_threshold = high_threat_threshold
        self._critical_threat_threshold = critical_threat_threshold
        self._alerts: Deque[Alert] = deque(maxlen=max_alerts)
        self._lock = threading.RLock()

    # ─── Alert surface ────────────────────────────────────────────

    def record(self, alert: Alert) -> None:
        with self._lock:
            self._alerts.append(alert)

    def recent_alerts(self, limit: int = 50) -> List[Alert]:
        with self._lock:
            return list(self._alerts)[-limit:]

    def alert_counts(self) -> Dict[str, int]:
        with self._lock:
            counts = {s.value: 0 for s in AlertSeverity}
            for alert in self._alerts:
                counts[alert.severity.value] = counts.get(alert.severity.value, 0) + 1
            return counts

    # ─── Aggregate dashboard ─────────────────────────────────────

    def dashboard(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        threat_stats = self._threat.stats() if self._threat is not None else {}
        threat_recent = [
            e.to_dict()
            for e in (self._threat.recent_events(10) if self._threat else [])
        ]
        audit_summary = self._audit.review_summary() if self._audit is not None else {}
        secrets_diag = self._secrets.diagnostics() if self._secrets is not None else {}

        # Threat severity roll-up
        sev_counter: Counter = Counter()
        type_counter: Counter = Counter()
        if self._threat is not None:
            for event in self._threat.recent_events(100):
                sev_counter[event.level.value] += 1
                type_counter[event.type.value] += 1

        # Decide whether to emit fresh alerts based on the rollup.
        if sev_counter.get("critical", 0) >= self._critical_threat_threshold:
            self.record(
                Alert(
                    name="critical_threats",
                    severity=AlertSeverity.CRITICAL,
                    message=f"{sev_counter['critical']} critical threat(s) in window",
                    timestamp=now,
                    metadata={"by_type": dict(type_counter)},
                )
            )
        if sev_counter.get("high", 0) >= self._high_threat_threshold:
            self.record(
                Alert(
                    name="high_threats",
                    severity=AlertSeverity.WARNING,
                    message=f"{sev_counter['high']} high-severity threat(s) in window",
                    timestamp=now,
                    metadata={"by_type": dict(type_counter)},
                )
            )

        return {
            "generated_at": now.isoformat(),
            "threats": {
                "stats": threat_stats,
                "recent": threat_recent,
                "by_level": dict(sev_counter),
                "by_type": dict(type_counter),
            },
            "audit": {
                "review_summary": audit_summary,
            },
            "secrets": secrets_diag,
            "alerts": {
                "counts": self.alert_counts(),
                "recent": [a.to_dict() for a in self.recent_alerts(10)],
            },
        }


# ─── Singleton wiring ───────────────────────────────────────────────

_monitor_singleton: Optional[SecurityMonitor] = None
_monitor_lock = threading.Lock()


def get_security_monitor() -> SecurityMonitor:
    global _monitor_singleton
    with _monitor_lock:
        if _monitor_singleton is None:
            from app.security.audit_review import get_audit_review
            from app.security.secrets import get_secrets_manager
            from app.security.threat_detection import get_threat_detector

            _monitor_singleton = SecurityMonitor(
                threat_detector=get_threat_detector(),
                audit_review=get_audit_review(),
                secrets_manager=get_secrets_manager(),
            )
        return _monitor_singleton


def reset_security_monitor() -> None:
    """Test helper."""
    global _monitor_singleton
    _monitor_singleton = None


def set_security_monitor(monitor: SecurityMonitor) -> None:
    """Test helper: install a specific monitor instance."""
    global _monitor_singleton
    _monitor_singleton = monitor
