"""Module 8.3 — Risk Forecasting Engine API."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.forecasting import (
    ForecastRequest,
    ForecastStats,
    RiskForecast,
    ScenarioRequest,
)
from app.services.forecasting import ForecastingService
from app.services.observability import get_forecasting_metrics

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


def _service_dep():
    from app.api.dependencies import get_forecasting_service

    return Depends(get_forecasting_service)


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_forecasting_metrics()
    return {"status": "ok", "module": "forecasting", "metrics": metrics.snapshot()}


@router.post("/forecast", response_model=RiskForecast, status_code=201)
async def forecast(
    request: ForecastRequest,
    svc: ForecastingService = _service_dep(),
) -> RiskForecast:
    return svc.forecast(request)


@router.post("/scenario", response_model=List)
async def scenario(
    request: ScenarioRequest,
    svc: ForecastingService = _service_dep(),
):
    return svc.scenario_simulation(request)


@router.get("/trend/{document_id}")
async def trend(
    document_id: str,
    svc: ForecastingService = _service_dep(),
) -> Dict[str, Any]:
    score, direction = svc.trend_prediction(document_id)
    return {
        "document_id": document_id,
        "predicted_score": round(score, 4),
        "direction": direction,
    }


@router.get("/stats", response_model=ForecastStats)
async def stats(svc: ForecastingService = _service_dep()) -> ForecastStats:
    metrics = svc.accuracy_metrics()
    items = svc.list_all()
    last_at = max((f.generated_at for f in items), default=None)
    return ForecastStats(
        total_forecasts=metrics.get("total_forecasts", 0),
        average_horizon_days=round(metrics.get("average_horizon_days", 0.0), 3),
        drift_detected=metrics.get("drift_detected", 0),
        drift_rate=metrics.get("drift_rate", 0.0),
        last_forecast_at=last_at,
    )


@router.get("/accuracy")
async def accuracy(svc: ForecastingService = _service_dep()) -> Dict[str, Any]:
    return svc.accuracy_metrics()


@router.get("", response_model=List[RiskForecast])
async def list_forecasts(
    svc: ForecastingService = _service_dep(),
) -> List[RiskForecast]:
    return svc.list_all()


# RESTful alias used by the web dashboard. Mirrors ``GET /forecasting``
# but with the plural-noun path that's expected by the SPA.
@router.get("/forecasts", response_model=List[RiskForecast], include_in_schema=False)
async def list_forecasts_plural(
    svc: ForecastingService = _service_dep(),
) -> List[RiskForecast]:
    return svc.list_all()


@router.get("/{forecast_id}", response_model=RiskForecast)
async def get_forecast(
    forecast_id: str, svc: ForecastingService = _service_dep()
) -> RiskForecast:
    f = svc.get(forecast_id)
    if f is None:
        raise HTTPException(status_code=404, detail="not found")
    return f
