"""Module 8.3 — Risk Forecasting Engine.

Public surface
--------------
* ``ForecastModel`` (ABC) + ``LinearRegressionForecastModel`` +
  ``ExponentialSmoothingForecastModel``
* ``TrendPredictor``              — derive 0..1 score from history
* ``ScenarioAnalyzer``            — best/baseline/worst case
* ``RiskForecastingEngine``       — combines models
* ``ForecastingStore`` (ABC) + ``InMemoryForecastingStore``
* ``ForecastingService``          — DI facade
* ``build_default_forecasting_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.schemas.forecasting import (
    ForecastPoint,
    ForecastRequest,
    ForecastScenario,
    RiskForecast,
    ScenarioRequest,
    ScenarioType,
    TimeSeries,
)
from app.schemas.risk import RiskLevel
from app.services.observability import (
    get_forecasting_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Forecast models ───────────────────────────────────────────────


class ForecastModel(ABC):
    name: str = "abstract"

    @abstractmethod
    def fit(self, series: Sequence[float]) -> None: ...

    @abstractmethod
    def predict(
        self, horizon: int, confidence: float = 0.5
    ) -> List[ForecastPoint]: ...


class LinearRegressionForecastModel(ForecastModel):
    name = "linear_regression"

    def __init__(self) -> None:
        self._slope: float = 0.0
        self._intercept: float = 0.0
        self._residual_std: float = 0.0

    def fit(self, series: Sequence[float]) -> None:
        n = len(series)
        if n == 0:
            self._slope = 0.0
            self._intercept = 0.0
            self._residual_std = 0.0
            return
        if n == 1:
            self._slope = 0.0
            self._intercept = float(series[0])
            self._residual_std = 0.0
            return
        x_mean = (n - 1) / 2.0
        y_mean = sum(series) / n
        num = 0.0
        den = 0.0
        for i, y in enumerate(series):
            num += (i - x_mean) * (y - y_mean)
            den += (i - x_mean) ** 2
        self._slope = num / den if den else 0.0
        self._intercept = y_mean - self._slope * x_mean
        residuals: List[float] = []
        for i, y in enumerate(series):
            pred = self._intercept + self._slope * i
            residuals.append((y - pred) ** 2)
        self._residual_std = (
            (sum(residuals) / max(1, n - 2)) ** 0.5
        )

    def predict(
        self, horizon: int, confidence: float = 0.5
    ) -> List[ForecastPoint]:
        if self._slope == 0.0 and self._intercept == 0.0 and self._residual_std == 0.0:
            return []
        now = time.time()
        z = {0.5: 0.67, 0.8: 1.28, 0.95: 1.96}.get(
            round(confidence, 2), 0.67
        )
        out: List[ForecastPoint] = []
        for h in range(1, horizon + 1):
            x = len(range(horizon)) + h - 1
            point = self._intercept + self._slope * x
            margin = z * self._residual_std * (1 + h / max(1, horizon))
            score = max(0.0, min(1.0, point))
            out.append(
                ForecastPoint(
                    timestamp=now + h * 86400.0,
                    predicted_score=score,
                    lower_bound=max(0.0, min(1.0, point - margin)),
                    upper_bound=max(0.0, min(1.0, point + margin)),
                    confidence=confidence,
                )
            )
        return out


class ExponentialSmoothingForecastModel(ForecastModel):
    name = "exponential_smoothing"

    def __init__(self, alpha: float = 0.4) -> None:
        self._alpha = alpha
        self._level: float = 0.0
        self._fitted: bool = False

    def fit(self, series: Sequence[float]) -> None:
        if not series:
            return
        self._level = float(series[0])
        for y in series[1:]:
            self._level = self._alpha * float(y) + (1 - self._alpha) * self._level
        self._fitted = True

    def predict(
        self, horizon: int, confidence: float = 0.5
    ) -> List[ForecastPoint]:
        if not self._fitted:
            return []
        now = time.time()
        out: List[ForecastPoint] = []
        for h in range(1, horizon + 1):
            decay = (1 - self._alpha) ** h
            margin = 0.1 * h * decay
            out.append(
                ForecastPoint(
                    timestamp=now + h * 86400.0,
                    predicted_score=max(0.0, min(1.0, self._level)),
                    lower_bound=max(0.0, self._level - margin),
                    upper_bound=min(1.0, self._level + margin),
                    confidence=confidence,
                )
            )
        return out


# ─── Trend predictor ───────────────────────────────────────────────


class TrendPredictor:
    """Derive a 0..1 score from history (latest + delta)."""

    def predict(self, history: Sequence[float]) -> Tuple[float, str]:
        if not history:
            return 0.0, "flat"
        latest = history[-1]
        if len(history) < 2:
            return max(0.0, min(1.0, latest)), "flat"
        prev = history[-2]
        delta = latest - prev
        if delta > 0.05:
            direction = "up"
        elif delta < -0.05:
            direction = "down"
        else:
            direction = "flat"
        return max(0.0, min(1.0, latest)), direction


# ─── Scenario analyzer ─────────────────────────────────────────────


class ScenarioAnalyzer:
    _DELTAS: Dict[ScenarioType, float] = {
        ScenarioType.BEST_CASE: -0.15,
        ScenarioType.BASELINE: 0.0,
        ScenarioType.WORST_CASE: 0.20,
    }

    def analyze(
        self,
        baseline_score: float,
        scenarios: Sequence[ScenarioType],
    ) -> List[ForecastScenario]:
        out: List[ForecastScenario] = []
        for s in scenarios:
            delta = self._DELTAS.get(s, 0.0)
            adj = max(0.0, min(1.0, baseline_score + delta))
            out.append(
                ForecastScenario(
                    name=s.value,
                    adjustments={"delta": delta},
                    predicted_score=adj,
                    predicted_level=_score_to_level(adj),
                )
            )
        return out


def _score_to_level(score: float) -> RiskLevel:
    if score >= 0.85:
        return RiskLevel.CRITICAL
    if score >= 0.65:
        return RiskLevel.HIGH
    if score >= 0.4:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ─── Engine ────────────────────────────────────────────────────────


class RiskForecastingEngine:
    def __init__(self) -> None:
        self._primary = LinearRegressionForecastModel()
        self._secondary = ExponentialSmoothingForecastModel()
        self._trend = TrendPredictor()
        self._scenario = ScenarioAnalyzer()
        self._last_forecast_score: Optional[float] = None

    def _select_history(self, request: ForecastRequest) -> List[float]:
        return [p.value for p in request.history]

    def forecast(self, request: ForecastRequest) -> RiskForecast:
        with track_request(
            endpoint="/api/v1/forecasting/forecast",
            strategy="forecast",
        ):
            history = self._select_history(request)
            self._primary.fit(history)
            self._secondary.fit(history)
            points = self._primary.predict(
                request.horizon_days, confidence=request.confidence
            )
            base_score = points[-1].predicted_score if points else 0.0
            drift = False
            if self._last_forecast_score is not None:
                if abs(base_score - self._last_forecast_score) > 0.05:
                    drift = True
            self._last_forecast_score = base_score
            get_forecasting_metrics().record_forecast(
                horizon_days=request.horizon_days, drift=drift
            )
            return RiskForecast(
                horizon_days=request.horizon_days,
                predicted_risk_score=round(base_score, 4),
                predicted_risk_level=_score_to_level(base_score),
                confidence=request.confidence,
                method="linear_regression+exponential_smoothing",
                points=points,
                series=TimeSeries(
                    name=f"{request.document_id or 'document'}_forecast",
                    points=points,
                ),
                generated_at=time.time(),
                drift_detected=drift,
            )

    def scenario_simulation(
        self, request: ScenarioRequest
    ) -> List[ForecastScenario]:
        with track_request(
            endpoint="/api/v1/forecasting/scenario",
            strategy="scenario",
        ):
            get_forecasting_metrics().record_scenario()
            return self._scenario.analyze(
                request.baseline_score, request.scenario_types
            )

    def trend_prediction(
        self, document_id: str
    ) -> Tuple[float, str]:
        with track_request(
            endpoint="/api/v1/forecasting/trend",
            strategy="trend",
        ):
            get_forecasting_metrics().record_trend_prediction()
            history = self._history_for(document_id)
            return self._trend.predict(history)

    def _history_for(self, document_id: str) -> List[float]:
        try:
            from app.services.compliance_risk import (
                build_default_compliance_risk_service,
            )

            svc = build_default_compliance_risk_service()
            history = svc.history_for(document_id)
            return [h.risk_score for h in history]
        except Exception:  # pragma: no cover
            return []


# ─── Store ─────────────────────────────────────────────────────────


class ForecastingStore(ABC):
    @abstractmethod
    def add(self, f: RiskForecast) -> None: ...

    @abstractmethod
    def get(self, fid: str) -> Optional[RiskForecast]: ...

    @abstractmethod
    def list_all(self) -> List[RiskForecast]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryForecastingStore(ForecastingStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._items: Dict[str, RiskForecast] = {}
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
                        f_obj = RiskForecast(**data)
                        self._items[f_obj.forecast_id] = f_obj
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, f: RiskForecast) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(f.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add(self, f: RiskForecast) -> None:
        with self._lock:
            self._items[f.forecast_id] = f
        self._persist(f)

    def get(self, fid: str) -> Optional[RiskForecast]:
        with self._lock:
            return self._items.get(fid)

    def list_all(self) -> List[RiskForecast]:
        with self._lock:
            return list(self._items.values())

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Service ──────────────────────────────────────────────────────


class ForecastingService:
    def __init__(self, store: ForecastingStore) -> None:
        self.store = store
        self.engine = RiskForecastingEngine()

    def forecast(self, request: ForecastRequest) -> RiskForecast:
        result = self.engine.forecast(request)
        result.forecast_id = (
            f"fcast-{uuid.uuid4().hex[:12]}"
        )
        self.store.add(result)
        return result

    def scenario_simulation(
        self, request: ScenarioRequest
    ) -> List[ForecastScenario]:
        return self.engine.scenario_simulation(request)

    def trend_prediction(
        self, document_id: str
    ) -> Tuple[float, str]:
        return self.engine.trend_prediction(document_id)

    def get(self, fid: str) -> Optional[RiskForecast]:
        return self.store.get(fid)

    def list_all(self) -> List[RiskForecast]:
        return self.store.list_all()

    def accuracy_metrics(self) -> Dict[str, Any]:
        items = self.store.list_all()
        if not items:
            return {"total_forecasts": 0}
        horizons: List[int] = []
        drifts = sum(1 for f in items if f.drift_detected)
        for f in items:
            horizons.append(f.horizon_days)
        return {
            "total_forecasts": len(items),
            "average_horizon_days": sum(horizons) / len(horizons),
            "drift_detected": drifts,
            "drift_rate": round(drifts / len(items), 4),
        }


def build_default_forecasting_service() -> ForecastingService:
    persist = os.path.join(
        settings.STORAGE_ROOT, "forecasting", "forecasts.jsonl"
    )
    store = InMemoryForecastingStore(persist_path=persist)
    return ForecastingService(store=store)


__all__ = [
    "ForecastModel",
    "LinearRegressionForecastModel",
    "ExponentialSmoothingForecastModel",
    "TrendPredictor",
    "ScenarioAnalyzer",
    "RiskForecastingEngine",
    "ForecastingStore",
    "InMemoryForecastingStore",
    "ForecastingService",
    "build_default_forecasting_service",
]
