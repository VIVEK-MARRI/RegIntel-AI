"""Module 7.5 — Regulatory Alerting System schemas."""

from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────


class AlertSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    IN_APP = "in_app"


class AlertStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class DigestPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class SubscriptionFrequency(str, Enum):
    REALTIME = "realtime"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


# ─── Core models ─────────────────────────────────────────────────────


class Alert(BaseModel):
    """A single regulatory alert."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(default_factory=lambda: f"alt-{secrets.token_hex(6)}")
    title: str = Field(..., min_length=1, max_length=300)
    message: str = Field(..., min_length=1, max_length=4000)
    source: str = Field(..., min_length=1, max_length=100)
    severity: AlertSeverity
    channels: List[AlertChannel] = Field(default_factory=list)
    status: AlertStatus = AlertStatus.PENDING
    priority: int = Field(3, ge=1, le=5)
    created_at: float = 0.0
    sent_at: Optional[float] = None
    delivered_at: Optional[float] = None
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    target: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class NotificationDelivery(BaseModel):
    """A single (channel, target) delivery attempt for an alert."""

    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(default_factory=lambda: f"dlv-{secrets.token_hex(6)}")
    alert_id: str
    channel: AlertChannel
    target: str
    status: AlertStatus
    attempts: int = 0
    last_attempt_at: Optional[float] = None
    error: str = ""
    latency_ms: float = 0.0


class AlertSubscription(BaseModel):
    """A user's subscription to alerts (channels, severity filter, sources)."""

    model_config = ConfigDict(extra="forbid")

    subscription_id: str = Field(default_factory=lambda: f"sub-{secrets.token_hex(6)}")
    user_id: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = None
    webhook_url: Optional[str] = None
    channels: List[AlertChannel] = Field(default_factory=list)
    severities: List[AlertSeverity] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    frequency: SubscriptionFrequency = SubscriptionFrequency.REALTIME
    active: bool = True
    created_at: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("channels")
    @classmethod
    def _at_least_one_channel(cls, v: List[AlertChannel]) -> List[AlertChannel]:
        if not v:
            raise ValueError("at least one channel required")
        return v


class DigestItem(BaseModel):
    """A single line item in a digest."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    title: str
    severity: AlertSeverity
    source: str
    created_at: float


class Digest(BaseModel):
    """A rolled-up digest for a period."""

    model_config = ConfigDict(extra="forbid")

    digest_id: str = Field(default_factory=lambda: f"dig-{secrets.token_hex(6)}")
    period: DigestPeriod
    items: List[DigestItem] = Field(default_factory=list)
    generated_at: float = 0.0
    body: str = ""
    summary: Dict[str, int] = Field(default_factory=dict)


# ─── Request / Response ──────────────────────────────────────────────


class AlertCreateRequest(BaseModel):
    """Request payload to create an alert."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=300)
    message: str = Field(..., min_length=1, max_length=4000)
    source: str = Field(..., min_length=1, max_length=100)
    severity: AlertSeverity
    channels: List[AlertChannel] = Field(default_factory=list)
    target: Optional[str] = None
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    impact_report_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SubscriptionCreateRequest(BaseModel):
    """Request payload to create a subscription."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = None
    webhook_url: Optional[str] = None
    channels: List[AlertChannel] = Field(default_factory=list)
    severities: List[AlertSeverity] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    frequency: SubscriptionFrequency = SubscriptionFrequency.REALTIME
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("channels")
    @classmethod
    def _at_least_one_channel(cls, v: List[AlertChannel]) -> List[AlertChannel]:
        if not v:
            raise ValueError("at least one channel required")
        return v


class AlertFilter(BaseModel):
    """Query filter for stored alerts."""

    model_config = ConfigDict(extra="forbid")

    source: Optional[str] = None
    severity: Optional[AlertSeverity] = None
    status: Optional[AlertStatus] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedAlerts(BaseModel):
    """Page of alerts."""

    model_config = ConfigDict(extra="forbid")

    items: List[Alert] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class AlertStats(BaseModel):
    """Aggregate alert statistics."""

    model_config = ConfigDict(extra="forbid")

    total_alerts: int = 0
    pending_alerts: int = 0
    sent_alerts: int = 0
    delivered_alerts: int = 0
    failed_alerts: int = 0
    skipped_alerts: int = 0
    digests_generated: int = 0
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_channel: Dict[str, int] = Field(default_factory=dict)
    by_source: Dict[str, int] = Field(default_factory=dict)


class DigestRequest(BaseModel):
    """Request payload for digest generation."""

    model_config = ConfigDict(extra="forbid")

    period: DigestPeriod
    source: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
