"""Tests for US-ORD-04: реакция B2C на события товаров от B2B.

DoD scenarios (b2c-orders-flows.md#b2c-12-handle-events):
  - product_blocked_marks_cart_items_unavailable
  - orders_not_affected_by_product_blocked
  - idempotent_event_no_side_effects
  - missing_service_key_returns_401

ADR (idempotency storage):
  See app/api/routers/product_events.py for the full ADR.
  Chosen: Redis with 24h TTL — zero cleanup overhead, auto-expiry.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings

_SKU_ID_1 = uuid4()
_SKU_ID_2 = uuid4()
_PRODUCT_ID = uuid4()
_IDEM_KEY = uuid4()
_NOW = datetime.now(timezone.utc).isoformat()

_SERVICE_KEY = settings.service.SERVICE_KEY

_BLOCKED_BODY = {
    "idempotency_key": str(_IDEM_KEY),
    "event": "PRODUCT_BLOCKED",
    "product_id": str(_PRODUCT_ID),
    "sku_ids": [str(_SKU_ID_1), str(_SKU_ID_2)],
    "reason": "Описание не соответствует товару",
    "date": _NOW,
}


def _idem_redis_key(idem_key=None) -> str:
    return f"b2c:product_event:idem:{idem_key or _IDEM_KEY}"


# ── Happy-path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_product_blocked_marks_cart_items_unavailable(ac):
    """PRODUCT_BLOCKED event marks all cart_items with matching sku_ids as unavailable.

    CartService.mark_skus_unavailable_in_all_carts must be called with the
    sku_ids from the event and reason='PRODUCT_BLOCKED'.
    Orders must NOT be touched.
    """
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)   # not a duplicate
    mock_redis.setex = AsyncMock()

    mock_mark = AsyncMock(return_value=3)  # 3 cart items updated

    with patch("app.api.routers.product_events.redis_client", mock_redis), \
         patch("app.api.routers.product_events.CartService.mark_skus_unavailable_in_all_carts", mock_mark):
        resp = await ac.post(
            "/api/v1/events/product",
            json=_BLOCKED_BODY,
            headers={"X-Service-Key": _SERVICE_KEY},
        )

    assert resp.status_code == 200
    assert resp.json() == {"accepted": True}

    # CartService was called with the two sku_ids and the right reason
    mock_mark.assert_awaited_once()
    call_args = mock_mark.call_args
    called_sku_ids = call_args.args[0] if call_args.args else call_args.kwargs["sku_ids"]
    called_reason = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["reason"]

    assert set(str(s) for s in called_sku_ids) == {str(_SKU_ID_1), str(_SKU_ID_2)}
    assert called_reason == "PRODUCT_BLOCKED"

    # Idempotency key persisted
    mock_redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_orders_not_affected_by_product_blocked(ac):
    """PRODUCT_BLOCKED event must NOT modify any order in the database.

    The endpoint handler touches only CartService — no OrderService calls.
    Prices are fixed; the seller is obligated to fulfil accepted orders.
    """
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.setex = AsyncMock()

    mock_mark = AsyncMock(return_value=0)

    # Spy on OrderService to prove it is never called
    with patch("app.api.routers.product_events.redis_client", mock_redis), \
         patch("app.api.routers.product_events.CartService.mark_skus_unavailable_in_all_carts", mock_mark), \
         patch("app.services.order_service.OrderService.cancel") as mock_cancel, \
         patch("app.services.order_service.OrderService.get_by_id") as mock_get:
        resp = await ac.post(
            "/api/v1/events/product",
            json=_BLOCKED_BODY,
            headers={"X-Service-Key": _SERVICE_KEY},
        )

    assert resp.status_code == 200
    mock_cancel.assert_not_called()
    mock_get.assert_not_called()


# ── Idempotency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_event_no_side_effects(ac):
    """Duplicate idempotency_key → 200 {"accepted": true} with no side effects.

    CartService.mark_skus_unavailable_in_all_carts must NOT be called a second time.
    """
    mock_redis = AsyncMock()
    # Simulate: key already exists in Redis (event was already processed)
    mock_redis.exists = AsyncMock(return_value=1)
    mock_redis.setex = AsyncMock()

    mock_mark = AsyncMock(return_value=0)

    with patch("app.api.routers.product_events.redis_client", mock_redis), \
         patch("app.api.routers.product_events.CartService.mark_skus_unavailable_in_all_carts", mock_mark):
        resp = await ac.post(
            "/api/v1/events/product",
            json=_BLOCKED_BODY,
            headers={"X-Service-Key": _SERVICE_KEY},
        )

    assert resp.status_code == 200
    assert resp.json() == {"accepted": True}

    # No cart update — idempotency guard kicked in
    mock_mark.assert_not_awaited()
    # No new idempotency key stored (we returned early)
    mock_redis.setex.assert_not_awaited()


# ── Auth / Security ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_service_key_returns_401(ac):
    """Request without X-Service-Key header must return 401 Unauthorized."""
    resp = await ac.post(
        "/api/v1/events/product",
        json=_BLOCKED_BODY,
        # No X-Service-Key header
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_service_key_returns_401(ac):
    """Request with an incorrect X-Service-Key must return 401."""
    resp = await ac.post(
        "/api/v1/events/product",
        json=_BLOCKED_BODY,
        headers={"X-Service-Key": "wrong-key-value"},
    )
    assert resp.status_code == 401
