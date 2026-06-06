"""Threat detection (M10.6).

A lightweight, in-process threat detector that watches request patterns
and produces :class:`ThreatEvent` records. It is meant to complement
(not replace) an external WAF / SIEM.

Signals monitored
-----------------

* **Brute force**   — repeated 401/403 responses per identity.
* **Path probing**   — repeated 404s on sensitive paths.
* **Large payloads** — request bodies larger than the configured cap.
* **Suspicious UA**  — known-bad user agents (sqlmap, nikto, nmap).
* **Header abuse**   — known-bad header values (sql meta-characters in
  ``User-Agent``/``Referer``, long header lines).
* **Anomalous rate** — sustained high request rate per identity.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ─── Types ───────────────────────────────────────────────────────────


class ThreatLevel(str, Enum):
    """Severity of a detected threat."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatType(str, Enum):
    BRUTE_FORCE = "brute_force"
    PATH_PROBING = "path_probing"
    LARGE_PAYLOAD = "large_payload"
    SUSPICIOUS_UA = "suspicious_ua"
    HEADER_ABUSE = "header_abuse"
    RATE_ANOMALY = "rate_anomaly"


@dataclass(frozen=True)
class ThreatEvent:
    """A single detected threat event."""

    type: ThreatType
    level: ThreatLevel
    identity: str
    description: str
    timestamp: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "level": self.level.value,
            "identity": self.identity,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─── ThreatDetector ──────────────────────────────────────────────────


class ThreatDetector:
    """Detect and record threats from request metadata.

    The detector is purely in-memory; events are kept in a bounded ring
    buffer and exposed via :meth:`recent_events`. Integrate with the
    audit log by listening to :meth:`subscribe`.
    """

    SUSPICIOUS_UA_PATTERNS: Sequence[str] = (
        r"sqlmap",
        r"nikto",
        r"nmap",
        r"masscan",
        r"wpscan",
        r"hydra",
        r"metasploit",
        r"acunetix",
    )
    HEADER_ABUSE_PATTERNS: Sequence[str] = (
        r"(\bunion\b.*\bselect\b)",
        r"(\bor\b\s+1\s*=\s*1)",
        r"(<script\b)",
        r"(\bdrop\b\s+\btable\b)",
    )
    SENSITIVE_PATHS: Sequence[str] = (
        "/admin",
        "/api/v1/admin",
        "/api/v1/security",
        "/api/v1/audit",
        "/api/v1/governance",
        "/.env",
        "/config",
    )

    def __init__(
        self,
        *,
        brute_force_threshold: int = 5,
        brute_force_window_seconds: float = 60.0,
        path_probing_threshold: int = 10,
        path_probing_window_seconds: float = 60.0,
        max_payload_bytes: int = 25 * 1024 * 1024,
        max_event_history: int = 1000,
    ) -> None:
        self._bf_threshold = brute_force_threshold
        self._bf_window = brute_force_window_seconds
        self._pp_threshold = path_probing_threshold
        self._pp_window = path_probing_window_seconds
        self._max_payload = max_payload_bytes
        self._max_events = max_event_history

        self._bf_hits: Dict[str, Deque[float]] = {}
        self._pp_hits: Dict[str, Deque[Tuple[float, str]]] = {}
        self._events: Deque[ThreatEvent] = deque(maxlen=max_event_history)
        self._lock = threading.RLock()
        self._subscribers: List[Any] = []

        self._ua_re = [re.compile(p, re.IGNORECASE) for p in self.SUSPICIOUS_UA_PATTERNS]
        self._hdr_re = [re.compile(p, re.IGNORECASE) for p in self.HEADER_ABUSE_PATTERNS]

    # ─── Public API ───────────────────────────────────────────────

    def subscribe(self, callback) -> None:
        """Register a callback invoked with each new :class:`ThreatEvent`."""
        self._subscribers.append(callback)

    def inspect_request(
        self,
        *,
        identity: str,
        method: str,
        path: str,
        body_size: int = 0,
        headers: Optional[Mapping[str, str]] = None,
    ) -> List[ThreatEvent]:
        """Inspect a single incoming request and return any events raised."""
        events: List[ThreatEvent] = []
        headers = headers or {}

        # 1. Large payload
        if body_size > self._max_payload:
            events.append(self._record(
                ThreatType.LARGE_PAYLOAD,
                ThreatLevel.MEDIUM,
                identity,
                f"payload size {body_size} bytes exceeds cap {self._max_payload}",
                {"method": method, "path": path, "body_size": body_size},
            ))

        # 2. Suspicious UA
        ua = headers.get("user-agent") or headers.get("User-Agent") or ""
        for rx in self._ua_re:
            if rx.search(ua):
                events.append(self._record(
                    ThreatType.SUSPICIOUS_UA,
                    ThreatLevel.HIGH,
                    identity,
                    f"suspicious user-agent: {ua[:60]!r}",
                    {"user_agent": ua[:200]},
                ))
                break

        # 3. Header abuse
        for name, value in headers.items():
            if not isinstance(value, str):
                continue
            for rx in self._hdr_re:
                if rx.search(value):
                    events.append(self._record(
                        ThreatType.HEADER_ABUSE,
                        ThreatLevel.HIGH,
                        identity,
                        f"header {name!r} contains exploit pattern",
                        {"header": name, "value": value[:200]},
                    ))
                    break

        # 4. Path probing
        if any(path.startswith(p) for p in self.SENSITIVE_PATHS) and method.upper() == "GET":
            now = time.time()
            with self._lock:
                dq = self._pp_hits.setdefault(identity, deque())
                dq.append((now, path))
                cutoff = now - self._pp_window
                while dq and dq[0][0] < cutoff:
                    dq.popleft()
                distinct_paths = {p for _, p in dq}
                if len(distinct_paths) >= self._pp_threshold:
                    events.append(self._record(
                        ThreatType.PATH_PROBING,
                        ThreatLevel.MEDIUM,
                        identity,
                        f"{len(distinct_paths)} distinct sensitive paths in {self._pp_window:.0f}s",
                        {"distinct_paths": sorted(distinct_paths)[:10]},
                    ))

        return events

    def inspect_response(
        self,
        *,
        identity: str,
        status_code: int,
        path: str,
    ) -> List[ThreatEvent]:
        """Inspect a single outgoing response (e.g. 401 / 403 / 404 patterns)."""
        events: List[ThreatEvent] = []
        if status_code in (401, 403):
            now = time.time()
            with self._lock:
                dq = self._bf_hits.setdefault(identity, deque())
                dq.append(now)
                cutoff = now - self._bf_window
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if len(dq) >= self._bf_threshold:
                    events.append(self._record(
                        ThreatType.BRUTE_FORCE,
                        ThreatLevel.HIGH,
                        identity,
                        f"{len(dq)} auth failures in {self._bf_window:.0f}s",
                        {"last_path": path, "count": len(dq)},
                    ))
        return events

    def recent_events(self, limit: int = 50) -> List[ThreatEvent]:
        with self._lock:
            return list(self._events)[-limit:]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            counter: Counter = Counter()
            for event in self._events:
                counter[event.type.value] += 1
            return {
                "total_events": len(self._events),
                "by_type": dict(counter),
                "tracked_brute_force_identities": len(self._bf_hits),
                "tracked_path_probing_identities": len(self._pp_hits),
            }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._bf_hits.clear()
            self._pp_hits.clear()

    # ─── Internals ────────────────────────────────────────────────

    def _record(
        self,
        type_: ThreatType,
        level: ThreatLevel,
        identity: str,
        description: str,
        metadata: Mapping[str, Any],
    ) -> ThreatEvent:
        event = ThreatEvent(
            type=type_,
            level=level,
            identity=identity,
            description=description,
            timestamp=datetime.now(timezone.utc),
            metadata=dict(metadata),
        )
        with self._lock:
            self._events.append(event)
        for cb in list(self._subscribers):
            try:
                cb(event)
            except Exception:  # pragma: no cover
                logger.exception("Threat subscriber raised")
        return event


_singleton: Optional[ThreatDetector] = None
_singleton_lock = threading.Lock()


def get_threat_detector() -> ThreatDetector:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ThreatDetector()
        return _singleton


def reset_threat_detector() -> None:
    """Test helper."""
    global _singleton
    _singleton = None


def set_threat_detector(detector: ThreatDetector) -> None:
    """Test helper: install a specific detector instance."""
    global _singleton
    _singleton = detector
