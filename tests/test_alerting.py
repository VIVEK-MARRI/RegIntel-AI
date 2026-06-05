"""Tests for Module 7.5 — Regulatory Alerting System."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_alert_service, reset_alert_service
from app.main import app
from app.schemas.alerts import (
    Alert,
    AlertChannel,
    AlertCreateRequest,
    AlertFilter,
    AlertSeverity,
    AlertStatus,
    AlertSubscription,
    DigestPeriod,
    DigestRequest,
    SubscriptionCreateRequest,
    SubscriptionFrequency,
)
from app.services.alerting import (
    AlertManager,
    AlertService,
    AlertStore,
    DigestGenerator,
    InMemoryAlertStore,
    InMemoryEmailSender,
    InMemoryWebhookSender,
    NotificationDispatcher,
    SubscriptionService,
    build_default_alert_service,
)
from app.services.observability import reset_alert_metrics


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_alert_service()
    reset_alert_metrics()
    yield
    reset_alert_service()
    reset_alert_metrics()


@pytest.fixture
def tmp_store(tmp_path):
    return InMemoryAlertStore(persist_path=Path(tmp_path) / "alerts.jsonl")


@pytest.fixture
def service(tmp_store):
    return AlertService(store=tmp_store)


def _alert_req(
    *,
    severity: AlertSeverity = AlertSeverity.HIGH,
    source: str = "RBI",
    title: str = "New circular",
    message: str = "Details of the circular",
    channels: List[AlertChannel] = None,
    target: str = None,
) -> AlertCreateRequest:
    return AlertCreateRequest(
        title=title,
        message=message,
        source=source,
        severity=severity,
        channels=channels or [AlertChannel.EMAIL],
        target=target or "user@example.com",
    )


# ─── In-memory senders ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_email_sender_success():
    s = InMemoryEmailSender()
    ok = await s.send(to="x@y.z", subject="subj", body="body")
    assert ok is True
    assert len(s.history()) == 1


@pytest.mark.asyncio
async def test_email_sender_failure():
    s = InMemoryEmailSender()
    s.fail_next(2)
    assert (await s.send(to="x", subject="s", body="b")) is False
    assert (await s.send(to="x", subject="s", body="b")) is False
    assert (await s.send(to="x", subject="s", body="b")) is True


@pytest.mark.asyncio
async def test_webhook_sender_success():
    s = InMemoryWebhookSender()
    ok = await s.send(url="https://x", payload={"a": 1})
    assert ok is True
    assert len(s.history()) == 1


@pytest.mark.asyncio
async def test_webhook_sender_failure():
    s = InMemoryWebhookSender()
    s.fail_next(1)
    assert (await s.send(url="https://x", payload={"a": 1})) is False
    assert (await s.send(url="https://x", payload={"a": 1})) is True


# ─── Dispatcher ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_email_success(tmp_store):
    sender = InMemoryEmailSender()
    d = NotificationDispatcher(store=tmp_store, email_sender=sender)
    a = Alert(
        title="t", message="m", source="RBI", severity=AlertSeverity.HIGH,
        channels=[AlertChannel.EMAIL], target="x@y.z",
    )
    out = await d.dispatch(a)
    assert len(out) == 1
    assert out[0].status == AlertStatus.DELIVERED
    assert out[0].channel == AlertChannel.EMAIL


@pytest.mark.asyncio
async def test_dispatcher_webhook_failure(tmp_store):
    sender = InMemoryWebhookSender()
    sender.fail_next(1)
    d = NotificationDispatcher(store=tmp_store, webhook_sender=sender)
    a = Alert(
        title="t", message="m", source="RBI", severity=AlertSeverity.HIGH,
        channels=[AlertChannel.WEBHOOK], target="https://x",
    )
    out = await d.dispatch(a)
    assert out[0].status == AlertStatus.FAILED


@pytest.mark.asyncio
async def test_dispatcher_in_app(tmp_store):
    d = NotificationDispatcher(store=tmp_store)
    a = Alert(
        title="t", message="m", source="RBI", severity=AlertSeverity.HIGH,
        channels=[AlertChannel.IN_APP], target="in_app",
    )
    out = await d.dispatch(a)
    assert out[0].status == AlertStatus.DELIVERED


# ─── Alert manager ────────────────────────────────────────────────────


def test_manager_creates_alert(tmp_store):
    mgr = AlertManager(store=tmp_store, dispatcher=NotificationDispatcher(store=tmp_store))
    a = mgr.create_alert(_alert_req())
    assert a.alert_id in [x.alert_id for x in tmp_store.list_alerts()]
    assert a.status == AlertStatus.PENDING


def test_manager_dedup_within_window(tmp_store):
    mgr = AlertManager(store=tmp_store, dispatcher=NotificationDispatcher(store=tmp_store))
    a1 = mgr.create_alert(_alert_req(title="dup"))
    a2 = mgr.create_alert(_alert_req(title="dup"))
    assert a1.status == AlertStatus.PENDING
    assert a2.status == AlertStatus.SKIPPED


@pytest.mark.asyncio
async def test_manager_processes_pending(tmp_store):
    mgr = AlertManager(store=tmp_store, dispatcher=NotificationDispatcher(store=tmp_store))
    mgr.create_alert(_alert_req())
    processed = await mgr.process_pending()
    assert len(processed) == 1
    assert processed[0].status == AlertStatus.DELIVERED


@pytest.mark.asyncio
async def test_manager_routes_to_subscribers(tmp_store):
    mgr = AlertManager(store=tmp_store, dispatcher=NotificationDispatcher(store=tmp_store))
    sub = AlertSubscription(
        user_id="u1",
        email="u1@example.com",
        channels=[AlertChannel.EMAIL],
        severities=[AlertSeverity.HIGH],
        sources=["RBI"],
    )
    tmp_store.add_subscription(sub)
    mgr.create_alert(_alert_req(severity=AlertSeverity.HIGH, target=None))
    processed = await mgr.process_pending()
    assert len(processed) == 1
    assert processed[0].status == AlertStatus.DELIVERED


@pytest.mark.asyncio
async def test_manager_no_match_subscriber_severity(tmp_store):
    mgr = AlertManager(store=tmp_store, dispatcher=NotificationDispatcher(store=tmp_store))
    sub = AlertSubscription(
        user_id="u1",
        email="u1@example.com",
        channels=[AlertChannel.EMAIL],
        severities=[AlertSeverity.CRITICAL],
        sources=["RBI"],
    )
    tmp_store.add_subscription(sub)
    mgr.create_alert(_alert_req(severity=AlertSeverity.LOW))
    processed = await mgr.process_pending()
    # No matching subscriber -> falls back to default target
    assert processed[0].status in (
        AlertStatus.DELIVERED,
        AlertStatus.FAILED,
    )


# ─── Digest generator ────────────────────────────────────────────────


def test_digest_daily_empty(tmp_store):
    g = DigestGenerator(store=tmp_store)
    d = g.generate(DigestRequest(period=DigestPeriod.DAILY))
    assert d.items == []
    assert "No alerts" in d.body


def test_digest_daily_with_items(tmp_store):
    import time
    a = Alert(
        title="Critical update",
        message="m",
        source="RBI",
        severity=AlertSeverity.CRITICAL,
        created_at=time.time(),
    )
    tmp_store.add_alert(a)
    g = DigestGenerator(store=tmp_store)
    d = g.generate(DigestRequest(period=DigestPeriod.DAILY))
    assert len(d.items) == 1
    assert d.summary.get("critical") == 1


def test_digest_weekly_filters_after(tmp_store):
    a = Alert(
        title="x", message="m", source="RBI", severity=AlertSeverity.LOW,
        created_at=100.0,
    )
    tmp_store.add_alert(a)
    g = DigestGenerator(store=tmp_store)
    d = g.generate(DigestRequest(period=DigestPeriod.WEEKLY, after=1000.0))
    assert d.items == []


def test_digest_source_filter(tmp_store):
    import time
    now = time.time()
    a1 = Alert(title="x", message="m", source="RBI", severity=AlertSeverity.LOW, created_at=now)
    a2 = Alert(title="y", message="m", source="SEBI", severity=AlertSeverity.LOW, created_at=now)
    tmp_store.add_alert(a1)
    tmp_store.add_alert(a2)
    g = DigestGenerator(store=tmp_store)
    d = g.generate(DigestRequest(period=DigestPeriod.DAILY, source="RBI"))
    assert len(d.items) == 1


# ─── Subscription service ────────────────────────────────────────────


def test_subscription_create(tmp_store):
    s = SubscriptionService(store=tmp_store)
    req = SubscriptionCreateRequest(
        user_id="u1", email="u@x.com",
        channels=[AlertChannel.EMAIL],
    )
    sub = s.create(req)
    assert sub.subscription_id
    assert sub.active is True


def test_subscription_remove(tmp_store):
    s = SubscriptionService(store=tmp_store)
    req = SubscriptionCreateRequest(
        user_id="u1", email="u@x.com", channels=[AlertChannel.EMAIL],
    )
    sub = s.create(req)
    assert s.remove(sub.subscription_id) is True
    assert s.remove(sub.subscription_id) is False


def test_subscription_match_severity_and_source(tmp_store):
    s = SubscriptionService(store=tmp_store)
    a = Alert(
        title="x", message="m", source="RBI", severity=AlertSeverity.HIGH,
    )
    s.create(SubscriptionCreateRequest(
        user_id="u1", email="u@x.com",
        channels=[AlertChannel.EMAIL],
        severities=[AlertSeverity.CRITICAL],
    ))
    s.create(SubscriptionCreateRequest(
        user_id="u2", email="u2@x.com",
        channels=[AlertChannel.EMAIL],
        sources=["RBI"],
    ))
    matches = s.match(a)
    assert len(matches) == 1
    assert matches[0].user_id == "u2"


def test_subscription_inactive_excluded(tmp_store):
    s = SubscriptionService(store=tmp_store)
    sub = s.create(SubscriptionCreateRequest(
        user_id="u1", email="u@x.com", channels=[AlertChannel.EMAIL],
    ))
    sub.active = False
    tmp_store.add_subscription(sub)
    a = Alert(title="x", message="m", source="RBI", severity=AlertSeverity.HIGH)
    assert s.match(a) == []


# ─── Store persistence ───────────────────────────────────────────────


def test_store_persists_alerts(tmp_path):
    p = Path(tmp_path) / "alerts.jsonl"
    s1 = InMemoryAlertStore(persist_path=p)
    a = Alert(
        title="x", message="m", source="RBI", severity=AlertSeverity.HIGH,
    )
    s1.add_alert(a)
    s2 = InMemoryAlertStore(persist_path=p)
    out = s2.get_alert(a.alert_id)
    assert out is not None
    assert out.title == "x"


def test_store_persists_subscriptions(tmp_path):
    p = Path(tmp_path) / "alerts.jsonl"
    s1 = InMemoryAlertStore(persist_path=p)
    sub = AlertSubscription(
        user_id="u1", email="u@x.com", channels=[AlertChannel.EMAIL],
    )
    s1.add_subscription(sub)
    s2 = InMemoryAlertStore(persist_path=p)
    out = s2.get_subscription(sub.subscription_id)
    assert out is not None
    assert out.user_id == "u1"


def test_store_get_missing(tmp_store):
    assert tmp_store.get_alert("nope") is None
    assert tmp_store.get_subscription("nope") is None


def test_store_reset(tmp_store):
    a = Alert(title="x", message="m", source="RBI", severity=AlertSeverity.HIGH)
    tmp_store.add_alert(a)
    assert len(tmp_store.list_alerts()) == 1
    tmp_store.reset()
    assert tmp_store.list_alerts() == []


# ─── Service ──────────────────────────────────────────────────────────


def test_service_create_and_get(service):
    a = service.create_alert(_alert_req(title="T1"))
    assert a.alert_id
    fetched = service.get(a.alert_id)
    assert fetched is not None
    assert fetched.title == "T1"


def test_service_get_missing(service):
    assert service.get("nope") is None


def test_service_search_filter_severity(service):
    service.create_alert(_alert_req(severity=AlertSeverity.LOW, title="low"))
    service.create_alert(_alert_req(severity=AlertSeverity.CRITICAL, title="crit"))
    res = service.search(AlertFilter(severity=AlertSeverity.CRITICAL))
    assert all(a.severity == AlertSeverity.CRITICAL for a in res.items)
    assert res.total >= 1


def test_service_search_pagination(service):
    for i in range(5):
        service.create_alert(_alert_req(title=f"t{i}"))
    res = service.search(AlertFilter(page=1, page_size=2))
    assert res.has_more is True
    assert len(res.items) == 2


def test_service_stats(service):
    service.create_alert(_alert_req(severity=AlertSeverity.HIGH))
    s = service.stats()
    assert s.total_alerts >= 1
    assert "high" in s.by_severity


def test_service_subscription_create_get_remove(service):
    req = SubscriptionCreateRequest(
        user_id="u1", email="u@x.com", channels=[AlertChannel.EMAIL],
    )
    sub = service.create_subscription(req)
    assert service.get_subscription(sub.subscription_id) is not None
    assert len(service.list_subscriptions()) == 1
    assert service.remove_subscription(sub.subscription_id) is True
    assert service.remove_subscription(sub.subscription_id) is False


def test_service_generate_digest(service):
    service.create_alert(_alert_req(title="x"))
    d = service.generate_digest(DigestRequest(period=DigestPeriod.DAILY))
    assert d.items is not None


def test_service_deliveries_for(service):
    a = service.create_alert(_alert_req())
    deliveries = service.deliveries_for(a.alert_id)
    assert isinstance(deliveries, list)


@pytest.mark.asyncio
async def test_service_process_pending(service):
    service.create_alert(_alert_req())
    out = await service.process_pending()
    assert len(out) >= 1


def test_build_default_service(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    svc = build_default_alert_service()
    assert isinstance(svc, AlertService)


# ─── API integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/alerts/health")
        assert r.status_code == 200
        assert r.json()["module"] == "alerting"


@pytest.mark.asyncio
async def test_api_create_alert(tmp_store):
    app.dependency_overrides[get_alert_service] = lambda: AlertService(store=tmp_store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/alerts",
                json={
                    "title": "Test",
                    "message": "Body",
                    "source": "RBI",
                    "severity": "high",
                    "channels": ["email"],
                    "target": "u@x.com",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["title"] == "Test"
            assert body["severity"] == "high"
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_list_alerts(tmp_store):
    svc = AlertService(store=tmp_store)
    svc.create_alert(_alert_req(title="T1"))
    app.dependency_overrides[get_alert_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/alerts?page=1&page_size=10")
            assert r.status_code == 200
            body = r.json()
            assert "items" in body
            assert body["total"] >= 1
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_get_alert_404(tmp_store):
    app.dependency_overrides[get_alert_service] = lambda: AlertService(store=tmp_store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/alerts/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_stats(tmp_store):
    app.dependency_overrides[get_alert_service] = lambda: AlertService(store=tmp_store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/alerts/stats")
            assert r.status_code == 200
            body = r.json()
            assert "total_alerts" in body
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_subscription_create_get_delete(tmp_store):
    app.dependency_overrides[get_alert_service] = lambda: AlertService(store=tmp_store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/alerts/subscriptions",
                json={
                    "user_id": "u1",
                    "email": "u@x.com",
                    "channels": ["email"],
                },
            )
            assert r.status_code == 200, r.text
            sub_id = r.json()["subscription_id"]

            r = await c.get("/api/v1/alerts/subscriptions")
            assert r.status_code == 200
            assert any(s["subscription_id"] == sub_id for s in r.json()["items"])

            r = await c.get(f"/api/v1/alerts/subscriptions/{sub_id}")
            assert r.status_code == 200
            assert r.json()["user_id"] == "u1"

            r = await c.delete(f"/api/v1/alerts/subscriptions/{sub_id}")
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_subscription_delete_404(tmp_store):
    app.dependency_overrides[get_alert_service] = lambda: AlertService(store=tmp_store)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete("/api/v1/alerts/subscriptions/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_digest_daily(tmp_store):
    svc = AlertService(store=tmp_store)
    svc.create_alert(_alert_req(title="T1"))
    app.dependency_overrides[get_alert_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/alerts/digest/daily")
            assert r.status_code == 200
            body = r.json()
            assert body["period"] == "daily"
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_digest_weekly(tmp_store):
    svc = AlertService(store=tmp_store)
    svc.create_alert(_alert_req(title="T1"))
    app.dependency_overrides[get_alert_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/alerts/digest/weekly")
            assert r.status_code == 200
            body = r.json()
            assert body["period"] == "weekly"
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_process_pending(tmp_store):
    svc = AlertService(store=tmp_store)
    svc.create_alert(_alert_req(title="T1"))
    app.dependency_overrides[get_alert_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/alerts/process")
            assert r.status_code == 200
            body = r.json()
            assert body["processed_count"] >= 1
    finally:
        app.dependency_overrides.pop(get_alert_service, None)


@pytest.mark.asyncio
async def test_api_alert_deliveries(tmp_store):
    svc = AlertService(store=tmp_store)
    a = svc.create_alert(_alert_req(title="T1"))
    app.dependency_overrides[get_alert_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/v1/alerts/{a.alert_id}/deliveries")
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_alert_service, None)
