"""add banners and banner_events tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'banners',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('image_url', sa.String(500), nullable=False),
        sa.Column('link', sa.String(500), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )

    op.create_table(
        'banner_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('banner_id', UUID(as_uuid=True),
                  sa.ForeignKey('banners.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('event', sa.String(20), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_banner_events_banner_id', 'banner_events', ['banner_id'])


def downgrade() -> None:
    op.drop_table('banner_events')
    op.drop_table('banners')
