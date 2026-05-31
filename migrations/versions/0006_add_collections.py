"""add collections and collection_products tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'collections',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cover_image_url', sa.String(500), nullable=True),
        sa.Column('target_url', sa.String(500), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_collections_priority', 'collections', ['priority'])

    op.create_table(
        'collection_products',
        sa.Column('collection_id', UUID(as_uuid=True),
                  sa.ForeignKey('collections.id', ondelete='CASCADE'),
                  primary_key=True, nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('ordering', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_table('collection_products')
    op.drop_table('collections')
