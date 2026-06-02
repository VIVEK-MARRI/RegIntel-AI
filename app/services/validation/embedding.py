import uuid
import math
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import ChunkEmbedding, DocumentChunk, EmbeddingStatusEnum
from app.schemas.embedding_validation import (
    EmbeddingValidationIssue,
    EmbeddingValidationMetrics,
    EmbeddingValidationReport
)

logger = logging.getLogger(__name__)

class BaseEmbeddingValidationRule:
    """Base class for all individual embedding validation rules."""
    @property
    def name(self) -> str:
        raise NotImplementedError

    def validate(self, record: ChunkEmbedding, expected_dim: int) -> Optional[str]:
        """Validates a single embedding record. Returns error message if invalid, else None."""
        raise NotImplementedError

class NoDimensionMismatchRule(BaseEmbeddingValidationRule):
    """Rule ensuring embedding vector dimensions match the expected model dimension."""
    @property
    def name(self) -> str:
        return "dimension_mismatch"

    def validate(self, record: ChunkEmbedding, expected_dim: int) -> Optional[str]:
        if record.embedding is None:
            return None
        if len(record.embedding) != expected_dim:
            return f"Vector dimension mismatch: expected {expected_dim}, got {len(record.embedding)}"
        if record.embedding_dimension != expected_dim:
            return f"Field embedding_dimension mismatch: expected {expected_dim}, got {record.embedding_dimension}"
        return None

class NoZeroVectorRule(BaseEmbeddingValidationRule):
    """Rule ensuring embedding vectors are not zero vectors (all elements are zero)."""
    @property
    def name(self) -> str:
        return "zero_vector"

    def validate(self, record: ChunkEmbedding, expected_dim: int) -> Optional[str]:
        if record.embedding is None:
            return None
        norm_val = math.sqrt(sum(x * x for x in record.embedding))
        if norm_val < 1e-6:
            return "Vector is a zero vector (norm is too close to zero)"
        return None

class NoCorruptedVectorRule(BaseEmbeddingValidationRule):
    """Rule ensuring embedding vectors contain only valid floating point numbers (no NaNs or Infs)."""
    @property
    def name(self) -> str:
        return "corrupted_vector"

    def validate(self, record: ChunkEmbedding, expected_dim: int) -> Optional[str]:
        if record.embedding is None:
            return None
        if not isinstance(record.embedding, list):
            return "Vector is not stored as a list"
        for idx, val in enumerate(record.embedding):
            if val is None or not isinstance(val, (int, float)):
                return f"Vector contains non-numeric element at index {idx}"
            if math.isnan(val) or math.isinf(val):
                return f"Vector contains invalid float value (NaN/Inf) at index {idx}"
        return None

class EmbeddingQualityValidator:
    """Orchestrates quality validation checks and calculates statistics on stored embeddings."""

    def __init__(self, db_session: AsyncSession, rules: Optional[List[BaseEmbeddingValidationRule]] = None):
        self.db_session = db_session
        self.rules = rules or [
            NoDimensionMismatchRule(),
            NoZeroVectorRule(),
            NoCorruptedVectorRule()
        ]

    async def validate_embeddings(
        self,
        expected_dim: int,
        embedding_model: str,
        document_id: Optional[uuid.UUID] = None
    ) -> EmbeddingValidationReport:
        """Validates all chunk embeddings for a specific model (optionally filtered by document)."""
        issues: List[EmbeddingValidationIssue] = []

        # 1. Check Missing Embeddings
        missing_stmt = (
            select(DocumentChunk.id)
            .outerjoin(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model == embedding_model,
                    ChunkEmbedding.status == EmbeddingStatusEnum.COMPLETED
                )
            )
            .where(ChunkEmbedding.chunk_id == None)
        )
        if document_id:
            missing_stmt = missing_stmt.where(DocumentChunk.document_id == document_id)
        
        missing_res = await self.db_session.execute(missing_stmt)
        missing_chunk_ids = [row[0] for row in missing_res.all()]
        for chunk_id in missing_chunk_ids:
            issues.append(
                EmbeddingValidationIssue(
                    chunk_id=str(chunk_id),
                    rule_name="missing_embedding",
                    message=f"Chunk is missing a completed embedding for model '{embedding_model}'",
                    severity="ERROR"
                )
            )

        # 2. Check Orphan Embeddings (orphan check runs globally or contextually)
        orphan_stmt = (
            select(ChunkEmbedding.id, ChunkEmbedding.chunk_id)
            .outerjoin(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(
                and_(
                    ChunkEmbedding.embedding_model == embedding_model,
                    DocumentChunk.id == None
                )
            )
        )
        orphan_res = await self.db_session.execute(orphan_stmt)
        for row in orphan_res.all():
            issues.append(
                EmbeddingValidationIssue(
                    embedding_id=str(row[0]),
                    chunk_id=str(row[1]),
                    rule_name="orphan_embedding",
                    message="Embedding record exists but does not correspond to any chunk in document_chunks",
                    severity="ERROR"
                )
            )

        # 3. Fetch all active embedding records for this model to validate individually and compute metrics
        stmt = select(ChunkEmbedding).where(ChunkEmbedding.embedding_model == embedding_model)
        if document_id:
            stmt = stmt.join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id).where(DocumentChunk.document_id == document_id)
        
        records_res = await self.db_session.execute(stmt)
        records = records_res.scalars().all()

        total_embeddings = len(records)
        invalid_records = set()
        completed_norms = []
        embedding_vectors = {}  # chunk_id -> embedding (for duplicate check)

        for record in records:
            if record.status != EmbeddingStatusEnum.COMPLETED or record.embedding is None:
                continue

            embedding_vectors[record.chunk_id] = record.embedding
            
            # Compute L2 norm
            norm_val = math.sqrt(sum(x * x for x in record.embedding))
            completed_norms.append(norm_val)

            for rule in self.rules:
                err = rule.validate(record, expected_dim)
                if err:
                    issues.append(
                        EmbeddingValidationIssue(
                            embedding_id=str(record.id),
                            chunk_id=str(record.chunk_id),
                            rule_name=rule.name,
                            message=err,
                            severity="ERROR"
                        )
                    )
                    invalid_records.add(record.id)

        # 4. Check Duplicate Embeddings
        vector_to_chunks = {}
        for chunk_id, vec in embedding_vectors.items():
            vec_tuple = tuple(vec)
            if vec_tuple not in vector_to_chunks:
                vector_to_chunks[vec_tuple] = []
            vector_to_chunks[vec_tuple].append(chunk_id)

        duplicate_embedding_count = 0
        for vec_tuple, chunk_ids in vector_to_chunks.items():
            if len(chunk_ids) > 1:
                duplicate_embedding_count += len(chunk_ids) - 1
                for chunk_id in chunk_ids:
                    issues.append(
                        EmbeddingValidationIssue(
                            chunk_id=str(chunk_id),
                            rule_name="duplicate_embedding",
                            message=f"Duplicate embedding vector value detected across {len(chunk_ids)} chunks",
                            severity="WARNING"
                        )
                    )

        # 5. Fetch Total Chunks count for coverage calculation
        total_chunks_stmt = select(func.count(DocumentChunk.id))
        if document_id:
            total_chunks_stmt = total_chunks_stmt.where(DocumentChunk.document_id == document_id)
        total_chunks_res = await self.db_session.execute(total_chunks_stmt)
        total_chunks = total_chunks_res.scalar() or 0

        # Metrics calculation
        completed_count = len(completed_norms)
        embedding_coverage = (completed_count / total_chunks * 100.0) if total_chunks > 0 else 100.0
        avg_norm = (sum(completed_norms) / completed_count) if completed_count > 0 else 0.0
        invalid_count = len(invalid_records)

        metrics = EmbeddingValidationMetrics(
            total_chunks=total_chunks,
            total_embeddings=total_embeddings,
            embedding_coverage=embedding_coverage,
            average_vector_norm=avg_norm,
            invalid_embedding_count=invalid_count,
            duplicate_embedding_count=duplicate_embedding_count
        )

        has_errors = any(i.severity == "ERROR" for i in issues)
        valid = not has_errors

        summary = (
            f"Validated {total_embeddings} embeddings for model '{embedding_model}'. "
            f"Coverage: {embedding_coverage:.1f}%. Issues found: {len(issues)}."
        )

        return EmbeddingValidationReport(
            valid=valid,
            issues=issues,
            metrics=metrics,
            summary=summary
        )
