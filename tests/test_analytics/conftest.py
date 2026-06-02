"""Test fixtures for analytics platform tests."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.document import Base
from app.models.analytics import (
    RetrievalMetricsRecord,
    AggregatedMetricsSnapshot,
    QueryDistributionRecord,
    RerankerGainRecord,
    SystemHealthSnapshot,
)

# Use SQLite in-memory for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session
        await session.rollback()


def make_metrics_data(**overrides) -> dict:
    """Create sample metrics data for testing."""
    now = datetime.now(timezone.utc)
    data = {
        "query_id": str(uuid.uuid4()),
        "query_text": "What are SEBI regulations on insider trading?",
        "query_category": "factual",
        "strategy": "dense",
        "dataset_name": "test_dataset",
        "dense_recall_at_5": 0.75,
        "dense_recall_at_10": 0.85,
        "bm25_recall_at_5": 0.60,
        "bm25_recall_at_10": 0.70,
        "hybrid_recall_at_5": 0.80,
        "hybrid_recall_at_10": 0.90,
        "precision_at_5": 0.70,
        "precision_at_10": 0.65,
        "mrr": 0.80,
        "hit_rate": 1.0,
        "retrieval_latency_ms": 45.0,
        "reranker_latency_ms": 120.0,
        "total_latency_ms": 165.0,
        "reranker_gain": 0.05,
        "results_returned": 10,
        "relevant_count": 8,
        "metadata_json": {"test": True},
    }
    data.update(overrides)
    return data


def make_batch_metrics_data(count: int = 5) -> list:
    """Create a batch of sample metrics data."""
    strategies = ["dense", "bm25", "hybrid", "hybrid_rerank"]
    categories = ["factual", "navigational", "analytical", "comparative"]
    now = datetime.now(timezone.utc)
    items = []
    for i in range(count):
        items.append({
            "query_id": str(uuid.uuid4()),
            "query_text": f"Test query {i}: What are the regulations?",
            "query_category": categories[i % len(categories)],
            "strategy": strategies[i % len(strategies)],
            "dataset_name": "test_dataset",
            "dense_recall_at_5": 0.5 + (i * 0.08),
            "dense_recall_at_10": 0.6 + (i * 0.07),
            "bm25_recall_at_5": 0.4 + (i * 0.09),
            "bm25_recall_at_10": 0.5 + (i * 0.08),
            "hybrid_recall_at_5": 0.55 + (i * 0.07),
            "hybrid_recall_at_10": 0.65 + (i * 0.06),
            "precision_at_5": 0.5 + (i * 0.06),
            "precision_at_10": 0.45 + (i * 0.05),
            "mrr": 0.6 + (i * 0.07),
            "hit_rate": 1.0 if i % 3 != 0 else 0.0,
            "retrieval_latency_ms": 30.0 + (i * 10),
            "reranker_latency_ms": 100.0 + (i * 20),
            "total_latency_ms": 130.0 + (i * 30),
            "reranker_gain": 0.02 + (i * 0.01),
            "results_returned": 10,
            "relevant_count": 5 + i,
            "metadata_json": {"batch_index": i},
        })
    return items