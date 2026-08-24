"""add_versioning_and_supersession

Revision ID: 99ef2d3f1ae0
Revises: 001_create_analytics_tables
Create Date: 2026-08-24 13:05:03.910743

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99ef2d3f1ae0'
down_revision: Union[str, Sequence[str], None] = '001_create_analytics_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('version', sa.String(length=50), nullable=True))
    op.add_column('documents', sa.Column('is_superseded', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('documents', sa.Column('superseded_by_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_documents_superseded_by_id', 'documents', 'documents', ['superseded_by_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_documents_superseded_by_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'superseded_by_id')
    op.drop_column('documents', 'is_superseded')
    op.drop_column('documents', 'version')
