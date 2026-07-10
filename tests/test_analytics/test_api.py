"""Tests for analytics API routes."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db_session
from app.main import app
from app.models.document import Base


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

ANALYTICS_TABLES = [
    "retrieval_metrics_records",
    "aggregated_metrics_snapshots",
    "query_distribution_records",
    "reranker_gain_records",
    "system_health_snapshots",
]


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def api_engine():
    """Create a test database engine with a shared in-memory connection."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_api_db(api_engine):
    """Truncate all analytics tables before each test for isolation."""
    async with api_engine.begin() as conn:
        for table in ANALYTICS_TABLES:
            await conn.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture
async def client(api_engine, clean_api_db) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client with overridden DB session."""
    async_session_factory = async_sessionmaker(
        bind=api_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestMetricsAPI:
    """Tests for metrics API endpoints."""

    async def test_record_metric(self, client):
        """Test POST /api/v1/analytics/metrics."""
        payload = {
            "query_id": str(uuid.uuid4()),
            "query_text": "What are SEBI regulations?",
            "query_category": "factual",
            "strategy": "dense",
            "dense_recall_at_5": 0.75,
            "mrr": 0.80,
            "retrieval_latency_ms": 45.0,
        }
        response = await client.post("/api/v1/analytics/metrics", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["query_text"] == "What are SEBI regulations?"
        assert data["strategy"] == "dense"
        assert data["dense_recall_at_5"] == 0.75

    async def test_record_metric_batch(self, client):
        """Test POST /api/v1/analytics/metrics/batch."""
        payload = [
            {
                "query_id": str(uuid.uuid4()),
                "query_text": f"Batch query {i}",
                "strategy": "dense",
                "dense_recall_at_5": 0.5 + (i * 0.1),
            }
            for i in range(3)
        ]
        response = await client.post("/api/v1/analytics/metrics/batch", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert len(data) == 3

    async def test_query_metrics(self, client):
        """Test GET /api/v1/analytics/metrics."""
        response = await client.get("/api/v1/analytics/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "items" in data

    async def test_query_metrics_with_filters(self, client):
        """Test GET /api/v1/analytics/metrics with strategy filter."""
        response = await client.get(
            "/api/v1/analytics/metrics",
            params={"strategy": "dense", "limit": 10},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["strategy"] == "dense"


@pytest.mark.asyncio
class TestAggregatedMetricsAPI:
    """Tests for aggregated metrics API endpoints."""

    async def test_get_aggregated_metrics(self, client):
        """Test GET /api/v1/analytics/metrics/aggregated/{strategy}."""
        response = await client.get(
            "/api/v1/analytics/metrics/aggregated/dense",
            params={
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_queries" in data


@pytest.mark.asyncio
class TestTrendAnalysisAPI:
    """Tests for trend analysis API endpoints."""

    async def test_get_trend_analysis(self, client):
        """Test GET /api/v1/analytics/trends/{metric_name}."""
        response = await client.get(
            "/api/v1/analytics/trends/dense_recall_at_5",
            params={
                "strategies": ["dense"],
                "window_type": "daily",
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=30)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metric_name"] == "dense_recall_at_5"
        assert "series" in data

    async def test_get_trend_analysis_invalid_metric_rejected(self, client):
        """Invalid metric name returns empty series — allow-list blocks injection (B608)."""
        response = await client.get(
            "/api/v1/analytics/trends/DROP_TABLE_users",
            params={
                "strategies": ["dense"],
                "window_type": "daily",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metric_name"] == "DROP_TABLE_users"
        for series in data["series"]:
            assert len(series["data_points"]) == 0


@pytest.mark.asyncio
class TestPerformanceSummaryAPI:
    """Tests for performance summary API endpoints."""

    async def test_get_performance_summary(self, client):
        """Test GET /api/v1/analytics/performance/summary."""
        response = await client.get(
            "/api/v1/analytics/performance/summary",
            params={
                "window_type": "daily",
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data
        assert "total_queries" in data


@pytest.mark.asyncio
class TestStrategyComparisonAPI:
    """Tests for strategy comparison API endpoints."""

    async def test_compare_strategies(self, client):
        """Test GET /api/v1/analytics/performance/compare."""
        response = await client.get(
            "/api/v1/analytics/performance/compare",
            params={
                "metric_name": "dense_recall_at_5",
                "window_type": "daily",
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metric_name"] == "dense_recall_at_5"
        assert "comparisons" in data
        assert "winner" in data


@pytest.mark.asyncio
class TestQueryDistributionAPI:
    """Tests for query distribution API endpoints."""

    async def test_get_query_distribution(self, client):
        """Test GET /api/v1/analytics/distribution/queries."""
        response = await client.get(
            "/api/v1/analytics/distribution/queries",
            params={
                "window_type": "daily",
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_queries" in data
        assert "category_distribution" in data
        assert "strategy_distribution" in data


@pytest.mark.asyncio
class TestRerankerGainAPI:
    """Tests for reranker gain API endpoints."""

    async def test_get_reranker_gain_not_found(self, client):
        """Test GET /api/v1/analytics/reranker/gain when no data exists."""
        response = await client.get(
            "/api/v1/analytics/reranker/gain",
            params={"window_type": "daily"},
        )
        assert response.status_code == 404

    async def test_record_reranker_gain(self, client):
        """Test POST /api/v1/analytics/reranker/gain."""
        now = datetime.now(timezone.utc)
        response = await client.post(
            "/api/v1/analytics/reranker/gain",
            params={
                "window_type": "daily",
                "window_start": now.isoformat(),
                "window_end": now.isoformat(),
                "avg_recall_gain_at_5": 0.05,
                "avg_mrr_gain": 0.06,
                "reranker_queries_count": 100,
                "improvement_rate": 0.75,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["avg_recall_gain_at_5"] == 0.05
        assert data["improvement_rate"] == 0.75

    async def test_get_reranker_gain_after_record(self, client):
        """Test GET /api/v1/analytics/reranker/gain after recording."""
        now = datetime.now(timezone.utc)
        await client.post(
            "/api/v1/analytics/reranker/gain",
            params={
                "window_type": "daily",
                "window_start": now.isoformat(),
                "window_end": now.isoformat(),
                "avg_recall_gain_at_5": 0.08,
                "reranker_queries_count": 50,
            },
        )

        response = await client.get(
            "/api/v1/analytics/reranker/gain",
            params={"window_type": "daily"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["avg_recall_gain_at_5"] == 0.08


@pytest.mark.asyncio
class TestSystemHealthAPI:
    """Tests for system health API endpoints."""

    async def test_get_system_health(self, client):
        """Test GET /api/v1/analytics/health."""
        response = await client.get("/api/v1/analytics/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "dense_retrieval_available" in data

    async def test_record_system_health(self, client):
        """Test POST /api/v1/analytics/health."""
        response = await client.post(
            "/api/v1/analytics/health",
            params={
                "status": "healthy",
                "dense_available": True,
                "embedding_coverage": 95.5,
                "total_indexed": 1000,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "healthy"
        assert data["embedding_coverage_pct"] == 95.5


@pytest.mark.asyncio
class TestReportAPI:
    """Tests for report generation API endpoints."""

    async def test_generate_report_post(self, client):
        """Test POST /api/v1/analytics/reports."""
        payload = {
            "window_type": "daily",
            "include_trends": False,
            "include_query_distribution": False,
            "include_reranker_gain": False,
            "include_system_health": False,
        }
        response = await client.post("/api/v1/analytics/reports", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "report_id" in data
        assert "performance_summary" in data

    async def test_generate_report_get(self, client):
        """Test GET /api/v1/analytics/reports/summary."""
        response = await client.get(
            "/api/v1/analytics/reports/summary",
            params={
                "window_type": "daily",
                "start_time": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "end_time": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "report_id" in data
