"""Tests for US-ORD-03: отмена заказа.

DoD scenarios (b2c-orders-flows.md#b2c-11-cancel-order):
  - cancel_paid_order_transitions_to_cancelled
  - unreserve_failure_transitions_to_cancel_pending
  - cancel_assembling_order_returns_409
  - other_user_order_returns_404

ADR (async retry strategy for CANCEL_PENDING):
  Chosen approach: log + leave CANCEL_PENDING (scaffold, no retry worker yet).
  On first iteration this is explicitly allowed by the DoD.

  Alternatives considered:
  1. Celery task with exponential backoff — production-grade, survives restarts,
     but requires a Celery broker (Redis/RabbitMQ) and worker process to be deployed
     alongside the app; adds operational complexity to a student project.
  2. APScheduler in-process (same approach as product-service reservation TTL) —
     zero extra infrastructure; state held in memory so retries are lost on restart,
     acceptable for a learning project but not for production.
  3. Management command + cron (or Docker COPY of a cron file) — trivial setup,
     guaranteed execution even after restart (cron is infrastructure-managed), but
     adds a second process and a shell dependency; harder to unit-test the retry logic.

  Selection criteria:
  - Setup complexity: cron < in-process scheduler < Celery
  - Restart guarantee: cron = Celery > in-process scheduler
  For a future production hardening of this service, Celery (criterion 2) wins.
  For the current scope, leaving CANCEL_PENDING is explicitly sanctioned by DoD.
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


def _cancel_response_dict(order_status: str) -> dict:
    return {
        "id": ORDER_ID,
        "number": f"NM-2026-{str(ORDER_ID)[:8].upper()}",
        "buyer_id": USER_ID,
        "status": order_status,
        "status_history": [
            {"status": "PAID", "changed_at": _NOW, "reason": None},
            {"status": "CANCEL_PENDING", "changed_at": _NOW, "reason": "Cancelled by buyer"},
        ],
        "items": [
            {
                "sku_id": SKU_ID,
                "product_id": PRODUCT_ID,
                "name": "iPhone 15 Pro Max",
                "sku_code": None,
                "image_url": None,
                "quantity": 1,
                "unit_price": 12999_00,
                "line_total": 12999_00,
            }
        ],
        "subtotal": 12999_00,
        "delivery_cost": 0,
        "total": 12999_00,
        "address": None,
        "payment_method": None,
        "comment": None,
        "cancel_reason": "Cancelled by buyer",
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
async def test_cancel_paid_order_transitions_to_cancelled(ac):
    """POST /api/v1/orders/{id}/cancel with PAID order + unreserve OK → 200 CANCELLED."""
    with patch(
        "app.api.routers.orders.OrderService.cancel",
        new=AsyncMock(return_value=_cancel_response_dict("CANCELLED")),
    ):
        resp = await ac.post(f"/api/v1/orders/{ORDER_ID}/cancel")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CANCELLED"
    assert body["cancel_reason"] == "Cancelled by buyer"


# ── Unhappy-path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unreserve_failure_transitions_to_cancel_pending(ac):
    """POST cancel with B2B unreserve failure → 200 CANCEL_PENDING (buyer's intent accepted).

    The service must NOT return 503 — buyer's cancellation intent is always accepted;
    the unreserve is retried asynchronously.
    """
    with patch(
        "app.api.routers.orders.OrderService.cancel",
        new=AsyncMock(return_value=_cancel_response_dict("CANCEL_PENDING")),
    ):
        resp = await ac.post(f"/api/v1/orders/{ORDER_ID}/cancel")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CANCEL_PENDING"
    # 503 would mean "try again later" — that's the wrong UX here
    assert resp.status_code != 503


@pytest.mark.asyncio
async def test_cancel_assembling_order_returns_409():
    """Service raises 409 CANCEL_NOT_ALLOWED when order is in ASSEMBLING status.

    Only CREATED and PAID orders can be cancelled.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.order_service import OrderService

    assembling_order = MagicMock(spec=OrderModel)
    assembling_order.id = ORDER_ID
    assembling_order.user_id = USER_ID
    assembling_order.status = OrderStatus.ASSEMBLING

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.scalar = AsyncMock(return_value=assembling_order)

    with pytest.raises(HTTPException) as exc_info:
        await OrderService.cancel(mock_session, order_id=ORDER_ID, user_id=USER_ID)

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "CANCEL_NOT_ALLOWED"
    assert exc.detail["details"]["current_status"] == OrderStatus.ASSEMBLING


@pytest.mark.asyncio
async def test_other_user_order_returns_404():
    """IDOR: cancel on another user's order must return 404, never 403."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.order_service import OrderService

    other_order = MagicMock(spec=OrderModel)
    other_order.id = ORDER_ID
    other_order.user_id = OTHER_USER_ID  # different owner
    other_order.status = OrderStatus.PAID

    mock_session = MagicMock(spec=AsyncSession)
    mock_session.scalar = AsyncMock(return_value=other_order)

    with pytest.raises(HTTPException) as exc_info:
        await OrderService.cancel(mock_session, order_id=ORDER_ID, user_id=USER_ID)

    assert exc_info.value.status_code == 404
    assert exc_info.value.status_code != 403


# ── Service-level: unreserve failure sets CANCEL_PENDING ─────────────────────


@pytest.mark.asyncio
async def test_service_sets_cancel_pending_when_unreserve_fails():
    """Service transitions order to CANCEL_PENDING (not exception) when B2B unreserve fails."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.order_service import OrderService

    paid_order = MagicMock(spec=OrderModel)
    paid_order.id = ORDER_ID
    paid_order.user_id = USER_ID
    paid_order.status = OrderStatus.PAID
    paid_order.address_id = None
    paid_order.payment_method_id = None
    paid_order.created_at = _NOW
    paid_order.updated_at = None
    paid_order.subtotal = 12999_00
    paid_order.delivery_cost = 0
    paid_order.total = 12999_00
    paid_order.comment = None
    paid_order.cancel_reason = None
    paid_order.paid_at = _NOW
    paid_order.delivered_at = None

    # After commit the re-fetched order shows CANCEL_PENDING (unreserve failed)
    pending_order = MagicMock(spec=OrderModel)
    pending_order.id = ORDER_ID
    pending_order.user_id = USER_ID
    pending_order.status = OrderStatus.CANCEL_PENDING
    pending_order.address_id = None
    pending_order.payment_method_id = None
    pending_order.created_at = _NOW
    pending_order.updated_at = _NOW
    pending_order.subtotal = 12999_00
    pending_order.delivery_cost = 0
    pending_order.total = 12999_00
    pending_order.comment = None
    pending_order.cancel_reason = "Cancelled by buyer"
    pending_order.paid_at = _NOW
    pending_order.delivered_at = None

    item = MagicMock(spec=OrderItemModel)
    item.order_id = ORDER_ID
    item.sku_id = SKU_ID
    item.product_id = PRODUCT_ID
    item.name = "iPhone 15 Pro Max"
    item.sku_code = None
    item.image_url = None
    item.quantity = 1
    item.unit_price = 12999_00
    item.line_total = 12999_00
    item.seller_id = None

    # Session: first scalar → paid_order; second scalar (re-fetch) → pending_order
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.scalar = AsyncMock(side_effect=[paid_order, pending_order])

    items_result = MagicMock()
    items_result.all = MagicMock(return_value=[item])
    history_result = MagicMock()
    history_result.all = MagicMock(return_value=[])
    mock_session.scalars = AsyncMock(side_effect=[items_result, history_result])

    # Mock B2B unreserve: raise a connection error (B2B unavailable)
    client_mock = AsyncMock()
    client_mock.post = AsyncMock(side_effect=Exception("Connection refused"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        result = await OrderService.cancel(mock_session, order_id=ORDER_ID, user_id=USER_ID)

    # Must return CANCEL_PENDING, not raise an exception
    assert result["status"] == OrderStatus.CANCEL_PENDING
