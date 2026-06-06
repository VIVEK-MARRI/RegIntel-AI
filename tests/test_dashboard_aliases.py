"""Regression tests for the dashboard-facing RESTful path aliases.

The single-resource list endpoints used by the React dashboard
(``/compliance-risk/assessments``, ``/forecasting/forecasts``,
``/review/tasks``) must keep working in lock-step with their canonical
empty-path siblings. These tests pin the alias behaviour and the
recommendations paginated contract.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def _reset_singletons():
    yield


@pytest.mark.asyncio
async def test_compliance_risk_assessments_alias():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/compliance-risk/assessments", params={"page": 1, "page_size": 5}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body and "total" in body
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_forecasting_forecasts_alias():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/forecasting/forecasts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)


@pytest.mark.asyncio
async def test_review_tasks_alias():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/review/tasks", params={"page": 1, "page_size": 5}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body and "total" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_recommendations_paginated_contract():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/recommendations", params={"page": 1, "page_size": 5}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(["items", "total", "page", "page_size", "has_more"]).issubset(body)
    assert isinstance(body["items"], list)
