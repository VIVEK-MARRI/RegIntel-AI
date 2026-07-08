import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.models.document import Base


class BM25IndexMetadata(Base):
    """SQLAlchemy model representing indexing metadata for a BM25 index run."""

    __tablename__ = "bm25_index_metadata"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    index_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    corpus_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_doc_len: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vocab_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
