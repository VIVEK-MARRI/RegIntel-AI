"""update_chunk_embeddings_pgvector

Revision ID: 9e2cc037e137
Revises: 700a22ca6619
Create Date: 2026-06-02 08:21:52.237296

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects.postgresql import ENUM

# revision identifiers, used by Alembic.
revision: str = '9e2cc037e137'
down_revision: Union[str, Sequence[str], None] = '700a22ca6619'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def check_vector_extension_available(connection) -> bool:
    try:
        # Check if vector extension is available in pg_available_extensions
        result = connection.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"))
        return result.scalar() is not None
    except Exception:
        return False


def upgrade() -> None:
    # Check if vector extension is available
    bind = op.get_bind()
    vector_available = check_vector_extension_available(bind)
    
    if vector_available:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        embedding_type = pgvector.sqlalchemy.Vector(384)
    else:
        # Fallback to ARRAY(Float)
        embedding_type = sa.ARRAY(sa.Float())
        
    op.drop_table("chunk_embeddings")
    
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("status", ENUM("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="embedding_status_enum", create_type=False), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id")
    )
    
    op.create_index("idx_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"])
    op.create_index("idx_chunk_embeddings_model", "chunk_embeddings", ["embedding_model"])
    op.create_index(
        "idx_chunk_embeddings_chunk_model",
        "chunk_embeddings",
        ["chunk_id", "embedding_model"],
        unique=True
    )
    
    if vector_available:
        # HNSW Index
        op.create_index(
            "idx_chunk_embeddings_vector",
            "chunk_embeddings",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"}
        )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("status", ENUM("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="embedding_status_enum", create_type=False), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id")
    )
