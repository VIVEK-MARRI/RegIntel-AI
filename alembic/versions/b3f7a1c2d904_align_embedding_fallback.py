"""align embedding column with the fallback runtime

Revision ID: b3f7a1c2d904
Revises: 99ef2d3f1ae0
Create Date: 2026-09-20

Lightweight runtimes (no torch: Render free tier, TF-IDF fallback) read and
write ``chunk_embeddings.embedding`` as a float array in Python, but older
migrations create a native ``vector(384)`` column whenever the pgvector
extension is present. asyncpg then fails every read with
``Unknown PG numeric type`` because no vector codec is registered.

This migration converts a ``vector`` column to ``DOUBLE PRECISION[]``,
preserving all rows — but ONLY when the fallback runtime is active
(``USE_PGVECTOR_FALLBACK=true``). Full-ML runtimes keep native vector
columns (and their HNSW index) untouched, so local GPU/CPU dev with torch
keeps working.

Safe to re-run: no-ops when the column is already a float array.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3f7a1c2d904"
down_revision: Union[str, Sequence[str], None] = "99ef2d3f1ae0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "chunk_embeddings"
COLUMN = "embedding"
HNSW_INDEX = "idx_chunk_embeddings_vector"


def _column_udt_name(connection) -> str | None:
    row = connection.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": TABLE, "column": COLUMN},
    ).scalar()
    return row


def upgrade() -> None:
    from app.core.config import settings

    if not settings.USE_PGVECTOR_FALLBACK:
        # Full-ML runtime: native vector columns are correct here.
        return

    bind = op.get_bind()
    if _column_udt_name(bind) != "vector":
        return  # already a float array (or table missing) — nothing to do

    # The HNSW index depends on the vector opclass: drop it before the cast.
    op.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX}")
    # pgvector renders as '[1,2,3]'; float[] renders as '{1,2,3}'. Convert
    # through text so every row (any dimension, NULLs untouched) survives.
    # string_to_array('') yields '{}', so empty vectors stay valid.
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} "
        f"TYPE DOUBLE PRECISION[] USING ("
        f"string_to_array(trim(both '[]' from {COLUMN}::text), ',')"
        f"::double precision[])"
    )


def downgrade() -> None:
    # Reverse: float[] back to vector(384). Only valid when every stored
    # vector has exactly 384 dimensions (full-ML corpora); Postgres aborts
    # the transaction otherwise and no partial state is left behind.
    # NOTE: information_schema reports a float array as udt_name '_float8'
    # (leading underscore), not 'float8'.
    bind = op.get_bind()
    if _column_udt_name(bind) != "_float8":
        return
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} "
        f"TYPE vector(384) USING ("
        f"replace(replace({COLUMN}::text, '{{', '['), '}}', ']')::vector)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {HNSW_INDEX} ON {TABLE} "
        f"USING hnsw ({COLUMN} vector_cosine_ops)"
    )
