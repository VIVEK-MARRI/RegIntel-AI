from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.document import Base
from app.models.types import PortableJSON


class KGNode(Base):
    """Durable knowledge-graph node (PostgreSQL; SQLite via create_all)."""

    __tablename__ = "kg_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    properties: Mapped[dict] = mapped_column(PortableJSON(), nullable=False, default=dict)
    tags: Mapped[list] = mapped_column(PortableJSON(), nullable=False, default=list)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (Index("idx_kg_nodes_name", "name"),)


class KGRelationship(Base):
    """Durable knowledge-graph edge."""

    __tablename__ = "kg_relationships"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    properties: Mapped[dict] = mapped_column(PortableJSON(), nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index("idx_kg_rel_src", "source_id"),
        Index("idx_kg_rel_tgt", "target_id"),
    )
