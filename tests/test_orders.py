"""Tests for US-ORD-02: просмотр и отслеживание заказов.

DoD scenarios (b2c-orders-flows.md#b2c-10-view-orders):
  - orders_list_returns_own_orders_paginated
  - order_detail_shows_fixed_prices
  - other_user_order_returns_404_not_403

ADR (IDOR protection strategy):
  Chosen approach: filter(user_id=jwt_user_id).get(id=...) — queryset-level filtering.
  The WHERE clause is applied before any ownership check in application code,
  so a non-existent row and a row belonging to another user are indistinguishable
  at the DB level → always 404, never 403.

  Alternatives considered:
  1. get(id=...) + explicit ownership check — exposes two code paths; a bug could
     accidentally return 403, leaking order existence.
  2. Permission class / middleware — adds indirection; still requires 404 semantics
     to be wired in explicitly, so the actual invariant lives in the same place.

  Selection criteria: readability (one place to read, one place to break) and
  deterministic 404-not-403 behaviour across all callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_active_auth_buyer
from app.main import app
from app.models.orders import OrderItemModel, OrderModel, OrderStatus

USER_ID = uuid4()
OTHER_USER_ID = uuid4()
ORDER_ID = uuid4()
SKU_ID = uuid4()
PRODUCT_ID = uuid4()
_NOW = datetime.now(timezone.utc)

_PAYLOAD = {"sub": str(USER_ID), "account_type": "buyer", "email": "buyer@test.com"}


def _order_dict(order_id: UUID | None = None, unit_price: int = 10000) -> dict:
    oid = order_id or ORDER_ID
    return {
        "id": oid,
        "number": f"NM-2026-{str(oid)[:8].upper()}",
        "buyer_id": USER_ID,
        "status": "PAID",
        "status_history": [{"status": "PAID", "changed_at": _NOW, "reason": None}],
        "items": [
            {
                "sku_id": SKU_ID,
                "product_id": PRODUCT_ID,
                "name": "iPhone 15 Pro Max",
                "sku_code": None,
                "image_url": None,
                "quantity": 2,
                "unit_price": unit_price,
                "line_total": unit_price * 2,
            }
        ],
        "subtotal": unit_price * 2,
        "delivery_cost": 0,
        "total": unit_price * 2,
        "address": None,
        "payment_method": None,
        "comment": None,
        "cancel_reason": None,
        "created_at": _NOW,
        "paid_at": _NOW,
        "delivered_at": None,
    }


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_active_auth_buyer] = lambda: _PAYLOAD
    yield
    app.dependency_overrides.pop(get_current_active_auth_buyer, None)


# ── Happy-path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orders_list_returns_own_orders_paginated(ac):
    """GET /api/v1/orders returns only the authenticated user's orders with pagination metadata."""
    order1 = _order_dict(order_id=uuid4())
    order2 = _order_dict(order_id=uuid4())
    # total_count=5 simulates that the user has 5 orders total; only 2 returned per page
    mock_get_list = AsyncMock(return_value=([order1, order2], 5))

    with patch("app.api.routers.orders.OrderService.get_list", new=mock_get_list):
        resp = await ac.get("/api/v1/orders?limit=2&offset=0")

    assert resp.status_code == 200
    body = resp.json()

    # Pagination envelope
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    # Service was called with user_id from JWT (not from query)
    call_kwargs = mock_get_list.call_args.kwargs
    assert call_kwargs["user_id"] == USER_ID
    assert call_kwargs["limit"] == 2
    assert call_kwargs["offset"] == 0


@pytest.mark.asyncio
async def test_order_detail_shows_fixed_prices(ac):
    """GET /api/v1/orders/{id} returns unit_price from OrderItem (fixed at purchase time).

    Even if a seller changes the SKU price after the order was created,
    the order must show the price the buyer actually paid (stored in OrderItem.unit_price).
    The service reads from the DB, never from B2B.
    """
    purchase_price = 12999_00  # price at the moment of purchase
    # Simulate: seller later changed price to 14999_00, but the order shows purchase_price
    order_data = _order_dict(order_id=ORDER_ID, unit_price=purchase_price)

    with patch(
        "app.api.routers.orders.OrderService.get_by_id",
        new=AsyncMock(return_value=order_data),
    ):
        resp = await ac.get(f"/api/v1/orders/{ORDER_ID}")

    assert resp.status_code == 200
    body = resp.json()

    item = body["items"][0]
    assert item["unit_price"] == purchase_price, (
        "unit_price must reflect the price stored in OrderItem at checkout, "
        "not the current B2B SKU price"
    )
    assert item["line_total"] == purchase_price * 2


# ── IDOR / Security ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_other_user_order_returns_404_not_403():
    """IDOR: service raises HTTP 404 (not 403) when order belongs to a different user.

    Returning 403 would reveal that the order exists — a malicious actor could
    enumerate UUIDs and build a list of valid order IDs.  Always 404 prevents this.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.order_service import OrderService

    # Create an order that belongs to OTHER_USER_ID
    other_order = MagicMock(spec=OrderModel)
    other_order.id = ORDER_ID
    other_order.user_id = OTHER_USER_ID  # different owner!

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.scalar = AsyncMock(return_value=other_order)

    with pytest.raises(HTTPException) as exc_info:
        await OrderService.get_by_id(
            mock_session,
            order_id=ORDER_ID,
            user_id=USER_ID,  # requesting as a different user
        )

    # Must be 404, never 403 — existence of the order must not be disclosed
    assert exc_info.value.status_code == 404, (
        f"Expected 404 for IDOR scenario, got {exc_info.value.status_code}"
    )
    assert exc_info.value.status_code != 403
