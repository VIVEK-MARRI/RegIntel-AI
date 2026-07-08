import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import ForeignKey, Integer, Text, DateTime, Index
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.document import Base
from app.models.types import PortableJSON, PortableFloatArray
from app.core.config import settings


class EmbeddingStatusEnum(str, PyEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    subsection: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
    embeddings: Mapped[list["ChunkEmbedding"]] = relationship(
        "ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan"
    )

    # Optimization indexes
    __table_args__ = (
        Index("idx_chunks_doc_id_page_num", "document_id", "page_number"),
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    if settings.USE_PGVECTOR_FALLBACK:
        embedding: Mapped[list[float] | None] = mapped_column(
            PortableFloatArray(), nullable=True
        )
    else:
        from pgvector.sqlalchemy import Vector

        embedding: Mapped[list[float] | None] = mapped_column(
            Vector(384), nullable=True
        )

    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[EmbeddingStatusEnum] = mapped_column(
        SQLEnum(EmbeddingStatusEnum, name="embedding_status_enum"),
        default=EmbeddingStatusEnum.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    chunk: Mapped["DocumentChunk"] = relationship(
        "DocumentChunk", back_populates="embeddings"
    )

    # Optimization indexes and constraints
    if settings.USE_PGVECTOR_FALLBACK:
        __table_args__ = (
            Index("idx_chunk_embeddings_chunk_id", "chunk_id"),
            Index("idx_chunk_embeddings_model", "embedding_model"),
            Index(
                "idx_chunk_embeddings_chunk_model",
                "chunk_id",
                "embedding_model",
                unique=True,
            ),
        )
    else:
        __table_args__ = (
            Index("idx_chunk_embeddings_chunk_id", "chunk_id"),
            Index("idx_chunk_embeddings_model", "embedding_model"),
            Index(
                "idx_chunk_embeddings_chunk_model",
                "chunk_id",
                "embedding_model",
                unique=True,
            ),
            Index(
                "idx_chunk_embeddings_vector",
                "embedding",
                postgresql_using="hnsw",
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )
