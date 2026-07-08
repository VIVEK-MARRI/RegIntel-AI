"""Module 7.5 — Regulatory Alerting System.

Public surface
--------------
* Pluggable ``EmailSenderProtocol`` / ``WebhookSenderProtocol``
* ``InMemoryEmailSender`` / ``InMemoryWebhookSender`` defaults
* ``AlertStore`` (ABC) + ``InMemoryAlertStore`` (JSONL)
* ``AlertManager``         — create / dedup / process pending
* ``NotificationDispatcher`` — deliver via channel
* ``DigestGenerator``      — daily / weekly digests
* ``SubscriptionService``  — subscribe / match
* ``AlertService``         — DI facade
* ``build_default_alert_service``
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from app.core.config import settings
from app.schemas.alerts import (
    Alert,
    AlertChannel,
    AlertCreateRequest,
    AlertFilter,
    AlertSeverity,
    AlertStats,
    AlertStatus,
    AlertSubscription,
    Digest,
    DigestItem,
    DigestPeriod,
    DigestRequest,
    NotificationDelivery,
    PaginatedAlerts,
    SubscriptionCreateRequest,
    SubscriptionFrequency,
)
from app.services.observability import (
    get_alert_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Sender Protocols (pluggable) ────────────────────────────────────


@runtime_checkable
class EmailSenderProtocol(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> bool: ...


@runtime_checkable
class WebhookSenderProtocol(Protocol):
    async def send(self, *, url: str, payload: Dict[str, Any]) -> bool: ...


# ─── Default in-memory senders ───────────────────────────────────────


class InMemoryEmailSender:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._log: List[Dict[str, Any]] = []
        self._fail_next = 0  # set > 0 to make the next N sends fail

    def fail_next(self, n: int) -> None:
        with self._lock:
            self._fail_next = n

    async def send(self, *, to: str, subject: str, body: str) -> bool:
        with self._lock:
            if self._fail_next > 0:
                self._fail_next -= 1
                self._log.append({"to": to, "subject": subject, "status": "failed"})
                return False
            self._log.append(
                {"to": to, "subject": subject, "body_len": len(body), "status": "sent"}
            )
            return True

    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._log)


class InMemoryWebhookSender:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._log: List[Dict[str, Any]] = []
        self._fail_next = 0

    def fail_next(self, n: int) -> None:
        with self._lock:
            self._fail_next = n

    async def send(self, *, url: str, payload: Dict[str, Any]) -> bool:
        with self._lock:
            if self._fail_next > 0:
                self._fail_next -= 1
                self._log.append({"url": url, "status": "failed"})
                return False
            self._log.append(
                {"url": url, "payload_keys": list(payload.keys()), "status": "sent"}
            )
            return True

    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._log)


# ─── Alert store ────────────────────────────────────────────────────


class AlertStore(ABC):
    @abstractmethod
    def add_alert(self, alert: Alert) -> None: ...

    @abstractmethod
    def get_alert(self, alert_id: str) -> Optional[Alert]: ...

    @abstractmethod
    def list_alerts(self) -> List[Alert]: ...

    @abstractmethod
    def add_subscription(self, sub: AlertSubscription) -> None: ...

    @abstractmethod
    def get_subscription(self, sub_id: str) -> Optional[AlertSubscription]: ...

    @abstractmethod
    def remove_subscription(self, sub_id: str) -> bool: ...

    @abstractmethod
    def list_subscriptions(self) -> List[AlertSubscription]: ...

    @abstractmethod
    def add_delivery(self, d: NotificationDelivery) -> None: ...

    @abstractmethod
    def list_deliveries(
        self, alert_id: Optional[str] = None
    ) -> List[NotificationDelivery]: ...

    @abstractmethod
    def add_digest(self, d: Digest) -> None: ...

    @abstractmethod
    def list_digests(self) -> List[Digest]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryAlertStore(AlertStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._alerts: Dict[str, Alert] = {}
        self._subs: Dict[str, AlertSubscription] = {}
        self._deliveries: Dict[str, NotificationDelivery] = {}
        self._digests: Dict[str, Digest] = {}
        self._persist_path = persist_path
        if self._persist_path and os.path.exists(self._persist_path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        kind = data.get("kind")
                        if kind == "alert":
                            a = Alert(**data["payload"])
                            self._alerts[a.alert_id] = a
                        elif kind == "subscription":
                            s = AlertSubscription(**data["payload"])
                            self._subs[s.subscription_id] = s
                        elif kind == "delivery":
                            d = NotificationDelivery(**data["payload"])
                            self._deliveries[d.delivery_id] = d
                        elif kind == "digest":
                            d = Digest(**data["payload"])
                            self._digests[d.digest_id] = d
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, kind: str, payload: Dict[str, Any]) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": kind, "payload": payload}) + "\n")
        except Exception:  # pragma: no cover
            pass

    def add_alert(self, alert: Alert) -> None:
        with self._lock:
            self._alerts[alert.alert_id] = alert
        self._persist("alert", alert.model_dump(mode="json"))

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        with self._lock:
            return self._alerts.get(alert_id)

    def list_alerts(self) -> List[Alert]:
        with self._lock:
            return list(self._alerts.values())

    def add_subscription(self, sub: AlertSubscription) -> None:
        with self._lock:
            self._subs[sub.subscription_id] = sub
        self._persist("subscription", sub.model_dump(mode="json"))

    def get_subscription(self, sub_id: str) -> Optional[AlertSubscription]:
        with self._lock:
            return self._subs.get(sub_id)

    def remove_subscription(self, sub_id: str) -> bool:
        with self._lock:
            if sub_id in self._subs:
                del self._subs[sub_id]
                return True
            return False

    def list_subscriptions(self) -> List[AlertSubscription]:
        with self._lock:
            return list(self._subs.values())

    def add_delivery(self, d: NotificationDelivery) -> None:
        with self._lock:
            self._deliveries[d.delivery_id] = d
        self._persist("delivery", d.model_dump(mode="json"))

    def list_deliveries(
        self, alert_id: Optional[str] = None
    ) -> List[NotificationDelivery]:
        with self._lock:
            if alert_id is None:
                return list(self._deliveries.values())
            return [d for d in self._deliveries.values() if d.alert_id == alert_id]

    def add_digest(self, d: Digest) -> None:
        with self._lock:
            self._digests[d.digest_id] = d
        self._persist("digest", d.model_dump(mode="json"))

    def list_digests(self) -> List[Digest]:
        with self._lock:
            return list(self._digests.values())

    def reset(self) -> None:
        with self._lock:
            self._alerts.clear()
            self._subs.clear()
            self._deliveries.clear()
            self._digests.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Notification dispatcher ─────────────────────────────────────────


class NotificationDispatcher:
    """Deliver alerts to channels; records NotificationDelivery entries."""

    def __init__(
        self,
        store: AlertStore,
        email_sender: Optional[EmailSenderProtocol] = None,
        webhook_sender: Optional[WebhookSenderProtocol] = None,
    ) -> None:
        self._store = store
        self._email = email_sender or InMemoryEmailSender()
        self._webhook = webhook_sender or InMemoryWebhookSender()

    @property
    def email_sender(self) -> EmailSenderProtocol:
        return self._email

    @property
    def webhook_sender(self) -> WebhookSenderProtocol:
        return self._webhook

    async def dispatch(
        self,
        alert: Alert,
        *,
        target: Optional[str] = None,
    ) -> List[NotificationDelivery]:
        deliveries: List[NotificationDelivery] = []
        channels = alert.channels or [AlertChannel.IN_APP]
        tgt = target or alert.target or "default@local"
        for ch in channels:
            start = time.time()
            d = NotificationDelivery(
                alert_id=alert.alert_id,
                channel=ch,
                target=tgt,
                status=AlertStatus.PENDING,
            )
            ok = False
            try:
                if ch == AlertChannel.EMAIL:
                    ok = await self._email.send(
                        to=tgt, subject=alert.title, body=alert.message
                    )
                elif ch == AlertChannel.WEBHOOK:
                    ok = await self._webhook.send(
                        url=tgt, payload=alert.model_dump(mode="json")
                    )
                else:  # IN_APP
                    ok = True
            except Exception as exc:  # pragma: no cover
                d.error = str(exc)
                ok = False
            d.attempts = 1
            d.last_attempt_at = time.time()
            d.latency_ms = round((time.time() - start) * 1000.0, 3)
            d.status = (
                (AlertStatus.DELIVERED if ok else AlertStatus.FAILED)
                if ch != AlertChannel.IN_APP
                else AlertStatus.DELIVERED
            )
            self._store.add_delivery(d)
            get_alert_metrics().record_delivery(
                ch.value, success=ok, latency_ms=d.latency_ms
            )
            deliveries.append(d)
        return deliveries


# ─── Alert manager ───────────────────────────────────────────────────


class AlertManager:
    """Create alerts, dedup, route to subscribers, record metrics."""

    def __init__(
        self,
        store: AlertStore,
        dispatcher: NotificationDispatcher,
        dedup_window_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._dedup_window = dedup_window_seconds

    def create_alert(self, req: AlertCreateRequest) -> Alert:
        alert = Alert(
            title=req.title,
            message=req.message,
            source=req.source,
            severity=req.severity,
            channels=req.channels or [AlertChannel.IN_APP],
            status=AlertStatus.PENDING,
            created_at=time.time(),
            document_id=req.document_id,
            diff_id=req.diff_id,
            impact_report_id=req.impact_report_id,
            target=req.target,
            metadata=req.metadata,
            tags=req.tags,
        )
        if self._is_duplicate(alert):
            alert.status = AlertStatus.SKIPPED
            self._store.add_alert(alert)
            return alert
        self._store.add_alert(alert)
        get_alert_metrics().record_alert(alert)
        return alert

    def _is_duplicate(self, alert: Alert) -> bool:
        cutoff = alert.created_at - self._dedup_window
        for existing in self._store.list_alerts():
            if (
                existing.source == alert.source
                and existing.title == alert.title
                and existing.created_at >= cutoff
            ):
                return True
        return False

    async def process_pending(self) -> List[Alert]:
        processed: List[Alert] = []
        for alert in self._store.list_alerts():
            if alert.status != AlertStatus.PENDING:
                continue
            # Find matching subscribers
            targets = [alert.target] if alert.target else []
            for sub in self._store.list_subscriptions():
                if not sub.active:
                    continue
                if not self._matches(alert, sub):
                    continue
                tgt = sub.email or sub.webhook_url
                if tgt:
                    targets.append(tgt)
            if not targets:
                targets = ["default@local"]
            any_ok = False
            for tgt in targets:
                deliveries = await self._dispatcher.dispatch(alert, target=tgt)
                if any(d.status == AlertStatus.DELIVERED for d in deliveries):
                    any_ok = True
            alert.sent_at = time.time()
            if any_ok:
                alert.status = AlertStatus.DELIVERED
                alert.delivered_at = time.time()
            else:
                alert.status = AlertStatus.FAILED
            self._store.add_alert(alert)
            processed.append(alert)
        return processed

    @staticmethod
    def _matches(alert: Alert, sub: AlertSubscription) -> bool:
        if sub.severities and alert.severity not in sub.severities:
            return False
        if sub.sources and alert.source not in sub.sources:
            return False
        return True


# ─── Digest generator ───────────────────────────────────────────────


class DigestGenerator:
    def __init__(self, store: AlertStore) -> None:
        self._store = store

    def generate(self, req: DigestRequest) -> Digest:
        with track_request(
            endpoint=f"/api/v1/alerts/digest/{req.period.value}",
            strategy="digest",
        ):
            alerts = self._store.list_alerts()
            now = time.time()
            if req.period == DigestPeriod.DAILY:
                window = 24 * 3600
            else:
                window = 7 * 24 * 3600
            after = req.after if req.after is not None else now - window
            before = req.before if req.before is not None else now
            items: List[DigestItem] = []
            for a in alerts:
                if a.created_at < after or a.created_at > before:
                    continue
                if req.source and a.source != req.source:
                    continue
                items.append(
                    DigestItem(
                        alert_id=a.alert_id,
                        title=a.title,
                        severity=a.severity,
                        source=a.source,
                        created_at=a.created_at,
                    )
                )
            items.sort(key=lambda i: i.created_at, reverse=True)
            summary: Dict[str, int] = {}
            for i in items:
                sev = i.severity.value
                summary[sev] = summary.get(sev, 0) + 1
            body = self._render_body(req.period, items, summary)
            d = Digest(
                period=req.period,
                items=items,
                generated_at=now,
                body=body,
                summary=summary,
            )
            self._store.add_digest(d)
            get_alert_metrics().record_digest()
            return d

    @staticmethod
    def _render_body(
        period: DigestPeriod, items: List[DigestItem], summary: Dict[str, int]
    ) -> str:
        if not items:
            return f"No alerts in the {period.value} period."
        lines = [f"{period.value.title()} regulatory digest:"]
        for sev, count in sorted(summary.items()):
            lines.append(f"  - {sev}: {count}")
        for i in items[:10]:
            lines.append(f"  • [{i.severity.value}] {i.title} (source={i.source})")
        if len(items) > 10:
            lines.append(f"  ... and {len(items) - 10} more")
        return "\n".join(lines)


# ─── Subscription service ────────────────────────────────────────────


class SubscriptionService:
    def __init__(self, store: AlertStore) -> None:
        self._store = store

    def create(self, req: SubscriptionCreateRequest) -> AlertSubscription:
        sub = AlertSubscription(
            user_id=req.user_id,
            email=req.email,
            webhook_url=req.webhook_url,
            channels=req.channels,
            severities=req.severities,
            sources=req.sources,
            frequency=req.frequency,
            active=True,
            created_at=time.time(),
            metadata=req.metadata,
        )
        self._store.add_subscription(sub)
        return sub

    def get(self, sub_id: str) -> Optional[AlertSubscription]:
        return self._store.get_subscription(sub_id)

    def list(self) -> List[AlertSubscription]:
        return self._store.list_subscriptions()

    def remove(self, sub_id: str) -> bool:
        return self._store.remove_subscription(sub_id)

    def match(self, alert: Alert) -> List[AlertSubscription]:
        out: List[AlertSubscription] = []
        for s in self._store.list_subscriptions():
            if not s.active:
                continue
            if s.severities and alert.severity not in s.severities:
                continue
            if s.sources and alert.source not in s.sources:
                continue
            out.append(s)
        return out


# ─── Alert service (DI facade) ──────────────────────────────────────


class AlertService:
    def __init__(
        self,
        store: AlertStore,
        email_sender: Optional[EmailSenderProtocol] = None,
        webhook_sender: Optional[WebhookSenderProtocol] = None,
    ) -> None:
        self.store = store
        self.dispatcher = NotificationDispatcher(
            store=store, email_sender=email_sender, webhook_sender=webhook_sender
        )
        self.manager = AlertManager(store=store, dispatcher=self.dispatcher)
        self.digests = DigestGenerator(store=store)
        self.subscriptions = SubscriptionService(store=store)

    # ── alerts ────────────────────────────────────────────────────

    def create_alert(self, req: AlertCreateRequest) -> Alert:
        return self.manager.create_alert(req)

    async def process_pending(self) -> List[Alert]:
        return await self.manager.process_pending()

    def get(self, alert_id: str) -> Optional[Alert]:
        return self.store.get_alert(alert_id)

    def search(self, flt: AlertFilter) -> PaginatedAlerts:
        items = self.store.list_alerts()
        if flt.source:
            items = [a for a in items if a.source == flt.source]
        if flt.severity:
            items = [a for a in items if a.severity == flt.severity]
        if flt.status:
            items = [a for a in items if a.status == flt.status]
        if flt.after is not None:
            items = [a for a in items if a.created_at >= flt.after]
        if flt.before is not None:
            items = [a for a in items if a.created_at <= flt.before]
        items.sort(key=lambda a: a.created_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedAlerts(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> AlertStats:
        all_alerts = self.store.list_alerts()
        s = AlertStats(total_alerts=len(all_alerts))
        for a in all_alerts:
            st = a.status.value
            s.by_status[st] = s.by_status.get(st, 0) + 1
            sev = a.severity.value
            s.by_severity[sev] = s.by_severity.get(sev, 0) + 1
            s.by_source[a.source] = s.by_source.get(a.source, 0) + 1
            if a.status == AlertStatus.PENDING:
                s.pending_alerts += 1
            elif a.status == AlertStatus.SENT:
                s.sent_alerts += 1
            elif a.status == AlertStatus.DELIVERED:
                s.delivered_alerts += 1
            elif a.status == AlertStatus.FAILED:
                s.failed_alerts += 1
            elif a.status == AlertStatus.SKIPPED:
                s.skipped_alerts += 1
        for d in self.store.list_digests():
            s.digests_generated += 1
        return s

    # ── digests ──────────────────────────────────────────────────

    def generate_digest(self, req: DigestRequest) -> Digest:
        return self.digests.generate(req)

    # ── subscriptions ────────────────────────────────────────────

    def create_subscription(self, req: SubscriptionCreateRequest) -> AlertSubscription:
        return self.subscriptions.create(req)

    def get_subscription(self, sub_id: str) -> Optional[AlertSubscription]:
        return self.subscriptions.get(sub_id)

    def list_subscriptions(self) -> List[AlertSubscription]:
        return self.subscriptions.list()

    def remove_subscription(self, sub_id: str) -> bool:
        return self.subscriptions.remove(sub_id)

    # ── misc ─────────────────────────────────────────────────────

    def deliveries_for(self, alert_id: str) -> List[NotificationDelivery]:
        return self.store.list_deliveries(alert_id=alert_id)


# ─── Factory ────────────────────────────────────────────────────────


def build_default_alert_service() -> AlertService:
    persist = os.path.join(settings.STORAGE_ROOT, "alerts", "alerts.jsonl")
    store = InMemoryAlertStore(persist_path=persist)
    return AlertService(store=store)


__all__ = [
    "EmailSenderProtocol",
    "WebhookSenderProtocol",
    "InMemoryEmailSender",
    "InMemoryWebhookSender",
    "AlertStore",
    "InMemoryAlertStore",
    "NotificationDispatcher",
    "AlertManager",
    "DigestGenerator",
    "SubscriptionService",
    "AlertService",
    "build_default_alert_service",
]
