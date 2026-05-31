"""add favorites table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'favorites',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column(
            'added_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )
    op.create_index('ix_favorites_user_id', 'favorites', ['user_id'])
    op.create_unique_constraint('uq_favorites_user_product', 'favorites', ['user_id', 'product_id'])


def downgrade() -> None:
    op.drop_table('favorites')
