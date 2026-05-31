"""POST /api/v1/events/product — receive product lifecycle events from B2B.

Canonical flow: b2c-orders-flows.md#b2c-12-handle-events

ADR (idempotency storage):
  Chosen approach: Redis with 24h TTL.

  Alternatives considered:
  1. PostgreSQL table EventIdempotencyKey — durable, survives restarts.
     Con: needs periodic cleanup job (e.g. DELETE WHERE created_at < NOW() - INTERVAL '7 days');
     without it the table grows unboundedly under high event load.
  2. Redis with TTL — auto-expiry handles cleanup automatically; no maintenance job.
     Con: not durable across Redis restarts (acceptable for idempotency guard — at-most-once
     semantics are best-effort anyway; worst case a rare duplicate event re-marks cart items,
     which is idempotent in effect).
  3. unavailable_reason field in cart_items — does not generalise: one event affects N carts
     across N buyers, so you'd need to fan-out writes to every cart item, and the key to
     de-duplicate is still per-event, not per-item.

  Selection criteria:
  - Risk of memory/disk leak: PostgreSQL without cleanup = unbounded growth;
    Redis TTL = O(1) per-key, auto-expired → no leak.
  - Cleanup complexity: Redis = zero (TTL); PostgreSQL = requires a scheduled job.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from app.api.deps import ServiceKeyDep, SessionDep
from app.core.redis_client import redis_client
from app.schemas import ProductEventRequest
from app.services.cart_service import CartService

logger = logging.getLogger(__name__)

product_events_router = APIRouter(prefix="/api/v1/events", tags=["product-events"])

_IDEM_TTL = 86_400  # 24 hours
_REASON_MAP = {
    "PRODUCT_BLOCKED": "PRODUCT_BLOCKED",
    "PRODUCT_DELETED": "PRODUCT_DELETED",
    "SKU_OUT_OF_STOCK": "OUT_OF_STOCK",
}


@product_events_router.post("/product", status_code=status.HTTP_200_OK)
async def receive_product_event(
    body: ProductEventRequest,
    _service_key: ServiceKeyDep,
    session: SessionDep,  # noqa: ARG001 — kept for dependency consistency
) -> dict:
    """Receive PRODUCT_BLOCKED / PRODUCT_DELETED / SKU_OUT_OF_STOCK from B2B.

    Actions:
    - Cart: mark matching cart_items as unavailable (unavailable_reason set).
    - Orders: NOT touched — prices are fixed, seller must fulfil accepted orders.
    - Idempotency: duplicate idempotency_key → 200 accepted silently (no re-processing).
    """
    idem_key = f"b2c:product_event:idem:{body.idempotency_key}"

    # Idempotency check — return early without side effects
    if await redis_client.exists(idem_key):
        logger.info(
            "Duplicate product event ignored: event=%s idempotency_key=%s",
            body.event,
            body.idempotency_key,
        )
        return {"accepted": True}

    reason = _REASON_MAP.get(body.event, body.event)

    if body.sku_ids:
        updated = await CartService.mark_skus_unavailable_in_all_carts(body.sku_ids, reason)
        logger.info(
            "Product event %s: marked %d cart item(s) unavailable for sku_ids=%s product_id=%s",
            body.event,
            updated,
            [str(s) for s in body.sku_ids],
            body.product_id,
        )
    else:
        logger.warning(
            "Product event %s received with empty sku_ids for product_id=%s — no cart items updated",
            body.event,
            body.product_id,
        )

    # Persist idempotency key AFTER successful processing
    await redis_client.setex(idem_key, _IDEM_TTL, "1")

    return {"accepted": True}
