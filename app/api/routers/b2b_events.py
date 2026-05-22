from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import ServiceKeyDep, SessionDep
from app.core.redis_client import redis_client
from app.schemas import B2BEvent
from app.services.cart_service import CartService
from app.services.favorites_service import FavoritesService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

b2b_events_router = APIRouter(prefix="/api/v1/b2b", tags=["b2b-events"])


@b2b_events_router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def receive_b2b_event(
    session: SessionDep,
    event: B2BEvent,
    _service_key: ServiceKeyDep,
):
    """
    Receive product lifecycle events from B2B service.

    Supported event_types:
    - PRODUCT_BLOCKED / PRODUCT_HARD_BLOCKED: remove from all carts, notify affected buyers
    - PRODUCT_DELETED: same as BLOCKED
    - SKU_OUT_OF_STOCK: remove SKU from all carts, notify affected buyers
    - PRICE_CHANGED: log only (future feature)
    """
    # Idempotency check (Fix 22)
    if event.idempotency_key is not None:
        idem_redis_key = f"b2c:event:idem:{event.idempotency_key}"
        if await redis_client.exists(idem_redis_key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_EVENT", "message": "Duplicate idempotency_key"},
            )
        await redis_client.setex(idem_redis_key, 86400, "1")

    logger.info(
        "B2B event received: type=%s idempotency_key=%s occurred_at=%s payload=%s",
        event.event_type,
        event.idempotency_key,
        event.occurred_at,
        event.payload,
    )

    # Resolve product_id and sku_id from the event (may be in payload or top-level)
    product_id: UUID | None = None
    sku_id: UUID | None = None

    if event.payload:
        raw_product = event.payload.get("product_id")
        raw_sku = event.payload.get("sku_id")
        if raw_product:
            try:
                product_id = UUID(str(raw_product))
            except (ValueError, AttributeError):
                pass
        if raw_sku:
            try:
                sku_id = UUID(str(raw_sku))
            except (ValueError, AttributeError):
                pass

    event_type = event.event_type

    if event_type in ("PRODUCT_BLOCKED", "PRODUCT_HARD_BLOCKED", "PRODUCT_DELETED"):
        if product_id is None:
            logger.warning("Event %s received without product_id — skipping cart cleanup", event_type)
        else:
            affected_identities = await CartService.remove_product_from_all_carts(product_id)
            logger.info(
                "Removed product %s from %d carts (event: %s)",
                product_id,
                len(affected_identities),
                event_type,
            )
            # Notify buyers whose carts were affected.
            # Only UUIDs are valid buyer_ids; session-based identities are skipped.
            message = f"Product '{product_id}' is no longer available"
            notified = 0
            for identity in affected_identities:
                try:
                    buyer_id = UUID(identity)
                except ValueError:
                    # guest / session-based cart — no account to notify
                    continue
                await NotificationService.create_for_buyer(
                    session, buyer_id, message, event_type
                )
                notified += 1
            if notified:
                await session.commit()
            logger.info("Sent %d notifications for event %s product %s", notified, event_type, product_id)

    elif event_type == "SKU_OUT_OF_STOCK":
        if sku_id is None:
            logger.warning("SKU_OUT_OF_STOCK event received without sku_id — skipping cart cleanup")
        else:
            affected_identities = await CartService.remove_sku_from_all_carts(sku_id)
            logger.info(
                "Removed SKU %s from %d carts (event: SKU_OUT_OF_STOCK)",
                sku_id,
                len(affected_identities),
            )
            message = f"An item in your cart (SKU '{sku_id}') is no longer available"
            notified = 0
            for identity in affected_identities:
                try:
                    buyer_id = UUID(identity)
                except ValueError:
                    continue
                await NotificationService.create_for_buyer(
                    session, buyer_id, message, event_type
                )
                notified += 1
            if notified:
                await session.commit()
            logger.info("Sent %d notifications for SKU_OUT_OF_STOCK sku %s", notified, sku_id)

    elif event_type == "PRICE_CHANGED":
        if product_id is None:
            logger.warning("PRICE_CHANGED event received without product_id — skipping notifications")
        else:
            buyer_ids = await FavoritesService.get_buyers_for_product(product_id)
            message = f"The price has changed for a product in your favorites (product '{product_id}')"
            notified = 0
            for buyer_id in buyer_ids:
                await NotificationService.create_for_buyer(
                    session, buyer_id, message, event_type
                )
                notified += 1
            if notified:
                await session.commit()
            logger.info(
                "Sent %d notifications for PRICE_CHANGED product %s",
                notified,
                product_id,
            )

    elif event_type == "SKU_BACK_IN_STOCK":
        if product_id is None:
            logger.warning("SKU_BACK_IN_STOCK event received without product_id — skipping notifications")
        else:
            buyer_ids = await FavoritesService.get_buyers_for_product(product_id)
            message = f"A product in your favorites is back in stock (product '{product_id}')"
            notified = 0
            for buyer_id in buyer_ids:
                await NotificationService.create_for_buyer(
                    session, buyer_id, message, event_type
                )
                notified += 1
            if notified:
                await session.commit()
            logger.info(
                "Sent %d notifications for SKU_BACK_IN_STOCK product %s",
                notified,
                product_id,
            )

    else:
        logger.info("Unhandled B2B event type: %s", event_type)

    return Response(status_code=202)
