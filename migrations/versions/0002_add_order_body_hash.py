"""add request_body_hash to orders

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('request_body_hash', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'request_body_hash')
