import time
import logging
import asyncio
import uuid
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import EmbeddingStatusEnum
from app.repositories.embedding import ChunkEmbeddingRepository
from app.services.chunk_registry import ChunkRegistryService
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """Orchestrator for chunk embedding generation pipeline supporting batching, retry rules, and metrics."""

    def __init__(
        self,
        db_session: AsyncSession,
        chunk_service: ChunkRegistryService,
        embedding_provider: EmbeddingProvider,
    ):
        self.db_session = db_session
        self.chunk_service = chunk_service
        self.embedding_provider = embedding_provider
        self.embedding_repo = ChunkEmbeddingRepository(db_session)

    async def process_document_embeddings(
        self,
        document_id: uuid.UUID,
        batch_size: int = 32,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> Dict[str, Any]:
        """Loads chunks for a document, generates vector embeddings in batches, and persists status."""
        if isinstance(document_id, str):
            document_id = uuid.UUID(document_id)
        logger.info(f"Starting embedding pipeline for document: {document_id}")
        start_time = time.perf_counter()

        # 1. Fetch chunks from chunk registry (raises DocumentNotFoundError if missing)
        chunks = await self.chunk_service.get_document_chunks(document_id, limit=10000)
        total_chunks = len(chunks)
        logger.info(f"Loaded {total_chunks} chunks for document: {document_id}")

        if total_chunks == 0:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return {
                "total_chunks": 0,
                "processed_chunks": 0,
                "failed_chunks": 0,
                "duration_ms": duration_ms,
            }

        # Retrieve model details from provider
        model_name = self.embedding_provider.get_model_name()
        dimension = self.embedding_provider.get_dimension()

        # 2. Initialize PENDING state for chunks in db (if not already existing)
        pending_data = [
            {
                "chunk_id": chunk.id,
                "embedding": None,
                "embedding_model": model_name,
                "embedding_dimension": dimension,
                "status": EmbeddingStatusEnum.PENDING,
                "error_message": None,
            }
            for chunk in chunks
        ]
        await self.embedding_repo.save_embeddings_bulk(pending_data)
        await self.db_session.commit()

        processed_count = 0
        failed_count = 0

        # 3. Process in batches
        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_chunk_ids = [c.id for c in batch_chunks]
            batch_contents = [c.content for c in batch_chunks]

            logger.info(
                f"Processing batch of {len(batch_chunks)} chunks ({i} to {i + len(batch_chunks)})..."
            )

            # Update status to PROCESSING in bulk
            processing_data = [
                {
                    "chunk_id": chunk_id,
                    "embedding": None,
                    "embedding_model": model_name,
                    "embedding_dimension": dimension,
                    "status": EmbeddingStatusEnum.PROCESSING,
                    "error_message": None,
                }
                for chunk_id in batch_chunk_ids
            ]
            await self.embedding_repo.save_embeddings_bulk(processing_data)
            await self.db_session.commit()

            # Generate embeddings with retry mechanism
            embeddings = None
            error_occured = None

            for attempt in range(1, max_retries + 1):
                try:
                    # encode_batch is run asynchronously (CPU/GPU evaluation)
                    embeddings = self.embedding_provider.encode_batch(batch_contents)
                    break
                except Exception as e:
                    error_occured = e
                    if attempt == max_retries:
                        logger.error(
                            f"Batch encoding failed permanently after {max_retries} attempts: {e}"
                        )
                        break

                    sleep_time = backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        f"Batch encoding attempt {attempt} failed, retrying in {sleep_time:.2f}s... Error: {e}"
                    )
                    await asyncio.sleep(sleep_time)

            # Persist results in bulk
            if embeddings is not None:
                # Success
                success_data = [
                    {
                        "chunk_id": chunk_id,
                        "embedding": embeddings[idx],
                        "embedding_model": model_name,
                        "embedding_dimension": dimension,
                        "status": EmbeddingStatusEnum.COMPLETED,
                        "error_message": None,
                    }
                    for idx, chunk_id in enumerate(batch_chunk_ids)
                ]
                await self.embedding_repo.save_embeddings_bulk(success_data)
                processed_count += len(batch_chunks)
            else:
                # Failure
                failure_data = [
                    {
                        "chunk_id": chunk_id,
                        "embedding": None,
                        "embedding_model": model_name,
                        "embedding_dimension": dimension,
                        "status": EmbeddingStatusEnum.FAILED,
                        "error_message": str(error_occured),
                    }
                    for chunk_id in batch_chunk_ids
                ]
                await self.embedding_repo.save_embeddings_bulk(failure_data)
                failed_count += len(batch_chunks)

            await self.db_session.commit()

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Embedding pipeline completed for document {document_id}. "
            f"Processed: {processed_count}, Failed: {failed_count} in {duration_ms:.2f}ms"
        )

        return {
            "total_chunks": total_chunks,
            "processed_chunks": processed_count,
            "failed_chunks": failed_count,
            "duration_ms": duration_ms,
        }
