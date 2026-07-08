"""Module 8.3 — Risk Forecasting Engine contracts.

Pydantic v2 with ``extra="forbid"`` for all models. Risk levels are taken
from :mod:`app.schemas.risk` to maintain a single source of truth.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.risk import RiskLevel


class ScenarioType(str, Enum):
    BEST_CASE = "best_case"
    BASELINE = "baseline"
    WORST_CASE = "worst_case"


class HistoryPoint(BaseModel):
    """One point in a historical risk-score series."""

    model_config = ConfigDict(extra="forbid")

    timestamp: float = Field(default_factory=time.time)
    value: float = Field(ge=0.0, le=1.0)


class ForecastPoint(BaseModel):
    """One projected point in the forecast horizon."""

    model_config = ConfigDict(extra="forbid")

    timestamp: float
    predicted_score: float = Field(ge=0.0, le=1.0)
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class TimeSeries(BaseModel):
    """A named time-series of forecast points."""

    model_config = ConfigDict(extra="forbid")

    name: str
    points: List[ForecastPoint] = Field(default_factory=list)


class ForecastScenario(BaseModel):
    """Single scenario projection."""

    model_config = ConfigDict(extra="forbid")

    name: str
    adjustments: Dict[str, float] = Field(default_factory=dict)
    predicted_score: float = Field(ge=0.0, le=1.0)
    predicted_level: RiskLevel


class RiskForecast(BaseModel):
    """A point-in-time risk forecast for a document/stream."""

    model_config = ConfigDict(extra="forbid")

    forecast_id: str = Field(
        default_factory=lambda: f"fcast-{uuid.uuid4().hex[:12]}"
    )
    horizon_days: int = Field(ge=1, le=365)
    predicted_risk_score: float = Field(ge=0.0, le=1.0)
    predicted_risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    method: str = "linear_regression"
    generated_at: float = Field(default_factory=time.time)
    document_id: Optional[str] = None
    points: List[ForecastPoint] = Field(default_factory=list)
    series: Optional[TimeSeries] = None
    drift_detected: bool = False


class ForecastRequest(BaseModel):
    """Request to run a forecast."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    horizon_days: int = Field(default=30, ge=1, le=365)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    history: List[HistoryPoint] = Field(default_factory=list)


class ScenarioRequest(BaseModel):
    """Request to simulate what-if scenarios."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    baseline_score: float = Field(ge=0.0, le=1.0, default=0.5)
    scenario_types: List[ScenarioType] = Field(
        default_factory=lambda: [
            ScenarioType.BEST_CASE,
            ScenarioType.BASELINE,
            ScenarioType.WORST_CASE,
        ]
    )


class ForecastStats(BaseModel):
    """Aggregated forecast statistics."""

    model_config = ConfigDict(extra="forbid")

    total_forecasts: int = 0
    average_horizon_days: float = 0.0
    drift_detected: int = 0
    drift_rate: float = 0.0
    last_forecast_at: Optional[float] = None


__all__ = [
    "ScenarioType",
    "HistoryPoint",
    "ForecastPoint",
    "TimeSeries",
    "ForecastScenario",
    "RiskForecast",
    "ForecastRequest",
    "ScenarioRequest",
    "ForecastStats",
]
