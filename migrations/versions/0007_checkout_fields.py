"""add checkout fields: delivery_address to orders, product_title/sku_name to order_items

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # orders: add delivery_address string, make address_id nullable
    op.add_column('orders', sa.Column('delivery_address', sa.Text(), nullable=True))
    op.alter_column('orders', 'address_id', nullable=True)

    # order_items: snapshot fields for fixed prices
    op.add_column('order_items', sa.Column('product_title', sa.String(500), nullable=True))
    op.add_column('order_items', sa.Column('sku_name', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('order_items', 'sku_name')
    op.drop_column('order_items', 'product_title')
    op.alter_column('orders', 'address_id', nullable=False)
    op.drop_column('orders', 'delivery_address')
