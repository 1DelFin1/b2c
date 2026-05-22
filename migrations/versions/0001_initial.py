"""initial

Revision ID: 0001
Revises:
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'buyers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('photo_url', sa.String(1024), nullable=True),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_buyers_email', 'buyers', ['email'], unique=True)

    op.create_table(
        'refresh_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('account_type', sa.String(10), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_refresh_tokens_token', 'refresh_tokens', ['token'], unique=True)

    op.create_table(
        'addresses',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('buyer_id', UUID(as_uuid=True), sa.ForeignKey('buyers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('region', sa.String(100), nullable=True),
        sa.Column('city', sa.String(100), nullable=False),
        sa.Column('street', sa.String(255), nullable=False),
        sa.Column('building', sa.String(50), nullable=False),
        sa.Column('apartment', sa.String(50), nullable=True),
        sa.Column('postal_code', sa.String(20), nullable=True),
        sa.Column('recipient_name', sa.String(255), nullable=True),
        sa.Column('recipient_phone', sa.String(20), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('comment', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_addresses_buyer_id', 'addresses', ['buyer_id'])

    op.create_table(
        'payment_methods',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('buyer_id', UUID(as_uuid=True), sa.ForeignKey('buyers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('card_last4', sa.String(4), nullable=True),
        sa.Column('card_brand', sa.String(50), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_payment_methods_buyer_id', 'payment_methods', ['buyer_id'])

    op.create_table(
        'orders',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='CREATED'),
        sa.Column('address_id', UUID(as_uuid=True), nullable=False),
        sa.Column('payment_method_id', UUID(as_uuid=True), nullable=True),
        sa.Column('comment', sa.String(1000), nullable=True),
        sa.Column('cancel_reason', sa.String(500), nullable=True),
        sa.Column('subtotal', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('delivery_cost', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('idempotency_key', UUID(as_uuid=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('idempotency_key', name='uq_orders_idempotency_key'),
    )
    op.create_index('ix_orders_idempotency_key', 'orders', ['idempotency_key'])

    op.create_table(
        'order_items',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id', UUID(as_uuid=True), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sku_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('sku_code', sa.String(100), nullable=True),
        sa.Column('image_url', sa.String(1000), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('line_total', sa.Integer(), nullable=False),
        sa.Column('seller_id', UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        'order_status_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id', UUID(as_uuid=True), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('reason', sa.String(500), nullable=True),
    )
    op.create_index('ix_order_status_history_order_id', 'order_status_history', ['order_id'])

    op.create_table(
        'notifications',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('body', sa.String(1000), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])

    op.create_table(
        'reviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', UUID(as_uuid=True), nullable=False),
        sa.Column('text', sa.String(1000), nullable=False),
        sa.Column('rating', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'product_id', name='uq_review_user_product'),
    )
    op.create_index('ix_reviews_user_id', 'reviews', ['user_id'])
    op.create_index('ix_reviews_product_id', 'reviews', ['product_id'])


def downgrade() -> None:
    op.drop_table('reviews')
    op.drop_table('notifications')
    op.drop_table('order_status_history')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('payment_methods')
    op.drop_table('addresses')
    op.drop_table('refresh_tokens')
    op.drop_table('buyers')
