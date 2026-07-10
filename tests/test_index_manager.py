import pytest
from unittest.mock import patch
from app.core.config import settings
from app.services.embedding.index_manager import VectorIndexManager


@pytest.mark.asyncio
async def test_create_rebuild_drop_index(db_session):
    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("pgvector index management requires PostgreSQL system tables")
    manager = VectorIndexManager(db_session)
    model_name = "BAAI/bge-small-en-v1.5"
    metric = "cosine"

    # 1. Create Index
    index_name = await manager.create_index(
        model_name=model_name, distance_metric=metric, concurrently=False
    )
    assert index_name is not None
    assert "hnsw" in index_name or "idx_chunk_embeddings" in index_name

    # 2. Check Health (it should list the index)
    health_metrics = await manager.index_health()
    assert len(health_metrics) > 0
    target = next((m for m in health_metrics if m["index_name"] == index_name), None)
    assert target is not None
    assert target["table_name"] == "chunk_embeddings"
    assert target["is_valid"] is True

    # 3. Rebuild Index
    await manager.rebuild_index(index_name, concurrently=False)

    # Verify it is still healthy
    health_metrics_after = await manager.index_health()
    target_after = next(
        (m for m in health_metrics_after if m["index_name"] == index_name), None
    )
    assert target_after is not None
    assert target_after["is_valid"] is True

    # 4. Drop Index
    await manager.drop_index(index_name)
    health_metrics_dropped = await manager.index_health()
    target_dropped = next(
        (m for m in health_metrics_dropped if m["index_name"] == index_name), None
    )
    assert target_dropped is None


@pytest.mark.asyncio
async def test_invalid_distance_metric(db_session):
    manager = VectorIndexManager(db_session)
    with pytest.raises(ValueError) as exc_info:
        await manager.create_index(
            model_name="test-model", distance_metric="invalid_metric"
        )
    assert "Unsupported distance metric" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_consistency(db_session):
    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("pgvector index management requires PostgreSQL system tables")
    manager = VectorIndexManager(db_session)
    report = await manager.validate_consistency("BAAI/bge-small-en-v1.5")

    assert "model_name" in report
    assert "total_chunks" in report
    assert "completed_embeddings" in report
    assert "failed_embeddings" in report
    assert "invalid_indexes" in report
    assert "is_consistent" in report
    assert isinstance(report["is_consistent"], bool)


@pytest.mark.asyncio
async def test_auto_rebuild_check(db_session):
    if settings.DATABASE_URL.startswith("sqlite"):
        pytest.skip("pgvector index management requires PostgreSQL system tables")
    manager = VectorIndexManager(db_session)

    # Check on non-existent index should return False
    assert await manager.auto_rebuild_check("non_existent_index") is False

    # Mock index_health to return invalid index and verify auto_rebuild returns True
    mock_health = [
        {
            "index_name": "idx_mock_invalid",
            "table_name": "chunk_embeddings",
            "index_size_bytes": 1000,
            "is_valid": False,
            "is_unique": False,
            "index_scans": 0,
            "tuples_read": 0,
            "tuples_fetched": 0,
        }
    ]
    with patch.object(manager, "index_health", return_value=mock_health):
        assert await manager.auto_rebuild_check("idx_mock_invalid") is True
