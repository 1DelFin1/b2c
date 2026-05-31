"""add product_subscriptions table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TEXT

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'product_subscriptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('notify_on', ARRAY(TEXT), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )
    op.create_index('ix_subscriptions_user_id', 'product_subscriptions', ['user_id'])
    op.create_unique_constraint(
        'uq_subscriptions_user_product', 'product_subscriptions', ['user_id', 'product_id']
    )


def downgrade() -> None:
    op.drop_table('product_subscriptions')
