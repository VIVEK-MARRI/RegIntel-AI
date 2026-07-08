import logging
import re
from typing import List, Dict, Any, Optional
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.chunk import ChunkEmbedding, DocumentChunk, EmbeddingStatusEnum

logger = logging.getLogger(__name__)


class VectorIndexManager:
    """Manages the lifecycle, maintenance, and monitoring of pgvector HNSW indexes on ChunkEmbedding."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    def _sanitize_index_name(self, model_name: str, metric: str) -> str:
        """Generates a clean index name from model name and metric."""
        clean_model = re.sub(r"[^a-zA-Z0-9_]", "_", model_name).lower()
        clean_metric = metric.lower()
        # Keep name within PG limit (63 chars)
        name = f"idx_chunk_embeddings_hnsw_{clean_model}_{clean_metric}"
        return name[:60]

    async def _execute_outside_transaction(
        self, sql: str, params: Optional[dict] = None
    ) -> None:
        """Executes a SQL statement outside the current active transaction block (e.g. for CONCURRENTLY)."""
        engine = self.db_session.bind
        if engine:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text(sql), params or {})
        else:
            # Fallback to normal execution if no bind is available
            await self.db_session.execute(text(sql), params or {})

    async def create_index(
        self,
        model_name: str,
        distance_metric: str = "cosine",
        m: int = 16,
        ef_construction: int = 64,
        concurrently: bool = False,
    ) -> str:
        """Creates a model-specific partial HNSW vector index (or fallback index)."""
        metric = distance_metric.lower()
        metrics_map = {
            "cosine": "vector_cosine_ops",
            "inner_product": "vector_ip_ops",
            "ip": "vector_ip_ops",
            "l2": "vector_l2_ops",
            "euclidean": "vector_l2_ops",
        }

        if metric not in metrics_map:
            raise ValueError(
                f"Unsupported distance metric '{distance_metric}'. Supported: cosine, inner_product, ip, l2, euclidean"
            )

        index_name = self._sanitize_index_name(model_name, metric)
        concurrent_clause = "CONCURRENTLY" if concurrently else ""
        escaped_model_name = model_name.replace("'", "''")

        if settings.USE_PGVECTOR_FALLBACK:
            logger.warning(
                f"pgvector fallback is active. Bypassing HNSW index for model '{model_name}'. "
                "Creating standard B-tree index."
            )
            # Create a standard B-tree index on (chunk_id, embedding_model) to simulate life-cycle tests
            sql = f"""
                CREATE INDEX IF NOT EXISTS {index_name} 
                ON chunk_embeddings (chunk_id, embedding_model) 
                WHERE embedding_model = '{escaped_model_name}'
            """
            await self.db_session.execute(text(sql))
            await self.db_session.commit()
            return index_name

        op_class = metrics_map[metric]
        sql = f"""
            CREATE INDEX {concurrent_clause} IF NOT EXISTS {index_name}
            ON chunk_embeddings USING hnsw (embedding {op_class})
            WITH (m = {m}, ef_construction = {ef_construction})
            WHERE embedding_model = '{escaped_model_name}'
        """

        if concurrently:
            await self._execute_outside_transaction(sql)
        else:
            await self.db_session.execute(text(sql))
            await self.db_session.commit()

        logger.info(
            f"Successfully created HNSW index '{index_name}' for model '{model_name}'"
        )
        return index_name

    async def rebuild_index(self, index_name: str, concurrently: bool = False) -> None:
        """Rebuilds an existing vector index."""
        concurrent_clause = "CONCURRENTLY" if concurrently else ""
        sql = f"REINDEX INDEX {concurrent_clause} {index_name}"

        logger.info(f"Rebuilding index '{index_name}' (concurrently={concurrently})...")
        if concurrently:
            await self._execute_outside_transaction(sql)
        else:
            await self.db_session.execute(text(sql))
            await self.db_session.commit()
        logger.info(f"Rebuild completed for index '{index_name}'")

    async def drop_index(self, index_name: str) -> None:
        """Drops an existing vector index."""
        sql = f"DROP INDEX IF EXISTS {index_name}"
        await self.db_session.execute(text(sql))
        await self.db_session.commit()
        logger.info(f"Dropped index '{index_name}'")

    async def index_health(self) -> List[Dict[str, Any]]:
        """Collects performance, size, and scanning metrics for all indexes on chunk_embeddings."""
        sql = """
            SELECT
                i.relname AS index_name,
                t.relname AS table_name,
                pg_relation_size(i.oid) AS index_size_bytes,
                idx.indisvalid AS is_valid,
                idx.indisunique AS is_unique,
                COALESCE(s.idx_scan, 0) AS index_scans,
                COALESCE(s.idx_tup_read, 0) AS tuples_read,
                COALESCE(s.idx_tup_fetch, 0) AS tuples_fetched
            FROM pg_index idx
            JOIN pg_class i ON i.oid = idx.indexrelid
            JOIN pg_class t ON t.oid = idx.indrelid
            LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = idx.indexrelid
            WHERE t.relname = 'chunk_embeddings'
        """
        result = await self.db_session.execute(text(sql))
        metrics = []
        for row in result.all():
            metrics.append(
                {
                    "index_name": row.index_name,
                    "table_name": row.table_name,
                    "index_size_bytes": row.index_size_bytes,
                    "index_size_pretty": f"{row.index_size_bytes / 1024:.2f} KB"
                    if row.index_size_bytes < 1024 * 1024
                    else f"{row.index_size_bytes / (1024 * 1024):.2f} MB",
                    "is_valid": row.is_valid,
                    "is_unique": row.is_unique,
                    "index_scans": row.index_scans,
                    "tuples_read": row.tuples_read,
                    "tuples_fetched": row.tuples_fetched,
                }
            )
        return metrics

    async def validate_consistency(self, model_name: str) -> Dict[str, Any]:
        """Validates count consistency and checks for invalid indexes."""
        # 1. Total registered chunks in DB
        chunk_stmt = select(func.count(DocumentChunk.id))
        chunk_res = await self.db_session.execute(chunk_stmt)
        total_chunks = chunk_res.scalar() or 0

        # 2. Embedding counts group by status
        stmt = (
            select(ChunkEmbedding.status, func.count(ChunkEmbedding.id))
            .where(ChunkEmbedding.embedding_model == model_name)
            .group_by(ChunkEmbedding.status)
        )
        res = await self.db_session.execute(stmt)

        status_counts = {
            EmbeddingStatusEnum.PENDING.value: 0,
            EmbeddingStatusEnum.PROCESSING.value: 0,
            EmbeddingStatusEnum.COMPLETED.value: 0,
            EmbeddingStatusEnum.FAILED.value: 0,
        }
        for row in res.all():
            status_val, count = row
            val = status_val.value if hasattr(status_val, "value") else str(status_val)
            status_counts[val] = count

        # 3. Check invalid indexes
        health_metrics = await self.index_health()
        invalid_indexes = [m["index_name"] for m in health_metrics if not m["is_valid"]]

        is_consistent = (
            status_counts[EmbeddingStatusEnum.COMPLETED.value]
            + status_counts[EmbeddingStatusEnum.FAILED.value]
            <= total_chunks
            and len(invalid_indexes) == 0
        )

        return {
            "model_name": model_name,
            "total_chunks": total_chunks,
            "completed_embeddings": status_counts[EmbeddingStatusEnum.COMPLETED.value],
            "failed_embeddings": status_counts[EmbeddingStatusEnum.FAILED.value],
            "pending_embeddings": status_counts[EmbeddingStatusEnum.PENDING.value],
            "processing_embeddings": status_counts[
                EmbeddingStatusEnum.PROCESSING.value
            ],
            "invalid_indexes": invalid_indexes,
            "is_consistent": is_consistent,
        }

    async def auto_rebuild_check(self, index_name: str) -> bool:
        """Determines if the index requires a rebuild based on health and statistics."""
        health_metrics = await self.index_health()
        target_metric = next(
            (m for m in health_metrics if m["index_name"] == index_name), None
        )

        if not target_metric:
            logger.warning(f"Index '{index_name}' not found during auto rebuild check")
            return False

        # Rule 1: Invalid indexes (e.g. from failed concurrent executions) must be rebuilt
        if not target_metric["is_valid"]:
            logger.info(
                f"Auto-Rebuild check: Index '{index_name}' is INVALID. Rebuild triggered."
            )
            return True

        # Rule 2: Rebuild if index has substantial size and scan/utilization shows high reads but poor fetches
        # (This is a simplified metric simulating performance degradation check)
        if target_metric["index_size_bytes"] > 10 * 1024 * 1024:  # > 10MB
            if (
                target_metric["tuples_read"] > 5 * target_metric["tuples_fetched"]
                and target_metric["index_scans"] > 100
            ):
                logger.info(
                    f"Auto-Rebuild check: High tuple read/fetch ratio detected for '{index_name}'. Rebuild triggered."
                )
                return True

        return False
