"""Enable pgvector extension before any table using Vector columns is created.

Revision ID: 000_enable_pgvector
Revises:
Create Date: 2026-08-24

This migration MUST run before any migration that creates a table with a
``VECTOR`` column.  It is safe to run when the extension is already present
(``IF NOT EXISTS``).  If the extension is not available (e.g., vanilla
Postgres without pgvector), the migration logs a warning and continues — the
application will use ``USE_PGVECTOR_FALLBACK=true`` in that case.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "000_enable_pgvector"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the pgvector extension if available."""
    conn = op.get_bind()
    try:
        # Check whether the extension is available on this server
        result = conn.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        )
        if result.scalar() is not None:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            logger.info("pgvector extension enabled")
        else:
            logger.warning(
                "pgvector extension is not available on this Postgres server. "
                "Set USE_PGVECTOR_FALLBACK=true in your .env to use ARRAY(Float) instead."
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not enable pgvector extension: %s", exc)


def downgrade() -> None:
    """Drop the pgvector extension (only if no columns depend on it)."""
    conn = op.get_bind()
    try:
        conn.execute(text("DROP EXTENSION IF EXISTS vector;"))
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not drop pgvector extension: %s", exc)
