"""create knowledge graph tables

Revision ID: c4d9e2f7a106
Revises: b3f7a1c2d904
Create Date: 2026-09-21

Durable kg_nodes / kg_relationships tables backing PostgresGraphStore.
Idempotent: skips tables that already exist (safe re-runs).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4d9e2f7a106"
down_revision: Union[str, Sequence[str], None] = "b3f7a1c2d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(connection, name: str) -> bool:
    return connection.dialect.has_table(connection, name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "kg_nodes"):
        op.create_table(
            "kg_nodes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("entity_type", sa.String(64), nullable=False, index=True),
            sa.Column("name", sa.String(300), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("external_id", sa.String(300), nullable=True),
            sa.Column("source", sa.String(64), nullable=False, server_default="manual"),
            sa.Column("properties", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.Float(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.Float(), nullable=False, server_default="0"),
        )
        op.create_index("idx_kg_nodes_name", "kg_nodes", ["name"])
    if not _table_exists(bind, "kg_relationships"):
        op.create_table(
            "kg_relationships",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("source_id", sa.String(64), nullable=False, index=True),
            sa.Column("target_id", sa.String(64), nullable=False, index=True),
            sa.Column(
                "relationship_type", sa.String(64), nullable=False, index=True
            ),
            sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("properties", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Float(), nullable=False, server_default="0"),
        )
        op.create_index("idx_kg_rel_src", "kg_relationships", ["source_id"])
        op.create_index("idx_kg_rel_tgt", "kg_relationships", ["target_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "kg_relationships"):
        op.drop_table("kg_relationships")
    if _table_exists(bind, "kg_nodes"):
        op.drop_table("kg_nodes")
