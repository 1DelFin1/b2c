from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import status, HTTPException

from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.orders import OrderModel, OrderStatus, OrderItemModel, OrderStatusHistoryModel
from app.models.addresses import AddressModel
from app.models.payment_methods import PaymentMethodModel
from app.schemas import OrderCreateRequest, CartItemStored


def _compute_order_body_hash(data: OrderCreateRequest, cart_items: list[CartItemStored]) -> str:
    items_sorted = sorted(
        [{"sku_id": str(i.sku_id), "quantity": i.quantity} for i in cart_items],
        key=lambda x: x["sku_id"],
    )
    body = {
        "address_id": str(data.address_id),
        "payment_method_id": str(data.payment_method_id),
        "comment": data.comment,
        "items": items_sorted,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

logger = logging.getLogger(__name__)


def _order_number(order: OrderModel) -> str:
    year = order.created_at.year
    short = str(order.id)[:8].upper()
    return f"NM-{year}-{short}"


def _build_order_response(
    order: OrderModel,
    item_rows: list,
    history_rows: list | None = None,
    address: AddressModel | None = None,
    payment: PaymentMethodModel | None = None,
) -> dict:
    items = [
        {
            "sku_id": item.sku_id,
            "product_id": item.product_id,
            "name": item.name,
            "sku_code": getattr(item, "sku_code", None),
            "image_url": getattr(item, "image_url", None),
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "seller_id": item.seller_id,
        }
        for item in item_rows
    ]
    status_history = [
        {
            "status": h.status,
            "changed_at": h.changed_at,
            "reason": h.reason,
        }
        for h in (history_rows or [])
    ]

    address_data: dict | None = None
    if address is not None:
        address_data = {
            "id": address.id,
            "country": address.country,
            "region": address.region,
            "city": address.city,
            "street": address.street,
            "building": address.building,
            "apartment": address.apartment,
            "postal_code": address.postal_code,
            "recipient_name": address.recipient_name,
            "recipient_phone": address.recipient_phone,
            "is_default": address.is_default,
            "comment": address.comment,
            "created_at": address.created_at,
        }

    payment_data: dict | None = None
    if payment is not None:
        payment_data = {
            "id": payment.id,
            "type": payment.type,
            "card_last4": payment.card_last4,
            "card_brand": payment.card_brand,
            "is_default": payment.is_default,
            "created_at": payment.created_at,
        }

    return {
        "id": order.id,
        "number": _order_number(order),
        "buyer_id": order.user_id,
        "status": order.status,
        "status_history": status_history,
        "items": items,
        "subtotal": order.subtotal,
        "delivery_cost": order.delivery_cost,
        "total": order.total,
        "address": address_data,
        "payment_method": payment_data,
        "comment": order.comment,
        "cancel_reason": order.cancel_reason,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
        "delivered_at": getattr(order, "delivered_at", None),
    }


class OrderService:
    @classmethod
    async def get_list(
        cls,
        session: AsyncSession,
        user_id: UUID,
        status_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        base_q = select(OrderModel).where(OrderModel.user_id == user_id)
        if status_filter:
            base_q = base_q.where(OrderModel.status == status_filter)

        count_stmt = select(func.count()).select_from(base_q.subquery())
        total = (await session.scalar(count_stmt)) or 0

        orders_stmt = (
            base_q
            .order_by(OrderModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        order_rows = list((await session.scalars(orders_stmt)).all())

        if not order_rows:
            return [], int(total)

        order_ids = [o.id for o in order_rows]
        items_stmt = select(OrderItemModel).where(OrderItemModel.order_id.in_(order_ids))
        item_rows = list((await session.scalars(items_stmt)).all())

        history_stmt = (
            select(OrderStatusHistoryModel)
            .where(OrderStatusHistoryModel.order_id.in_(order_ids))
            .order_by(OrderStatusHistoryModel.changed_at)
        )
        history_rows = list((await session.scalars(history_stmt)).all())

        items_by_order: dict[UUID, list] = defaultdict(list)
        for item in item_rows:
            items_by_order[item.order_id].append(item)

        history_by_order: dict[UUID, list] = defaultdict(list)
        for h in history_rows:
            history_by_order[h.order_id].append(h)

        # Batch-fetch addresses and payment methods
        address_ids = list({o.address_id for o in order_rows if o.address_id})
        payment_ids = list({o.payment_method_id for o in order_rows if o.payment_method_id})

        addresses_by_id: dict[UUID, AddressModel] = {}
        if address_ids:
            addr_stmt = select(AddressModel).where(AddressModel.id.in_(address_ids))
            for addr in (await session.scalars(addr_stmt)).all():
                addresses_by_id[addr.id] = addr

        payments_by_id: dict[UUID, PaymentMethodModel] = {}
        if payment_ids:
            pay_stmt = select(PaymentMethodModel).where(PaymentMethodModel.id.in_(payment_ids))
            for pay in (await session.scalars(pay_stmt)).all():
                payments_by_id[pay.id] = pay

        result = [
            _build_order_response(
                order,
                items_by_order.get(order.id, []),
                history_by_order.get(order.id, []),
                address=addresses_by_id.get(order.address_id) if order.address_id else None,
                payment=payments_by_id.get(order.payment_method_id) if order.payment_method_id else None,
            )
            for order in order_rows
        ]
        return result, int(total)

    @classmethod
    async def get_by_id(
        cls,
        session: AsyncSession,
        order_id: UUID,
        user_id: UUID,
    ) -> dict:
        order_stmt = select(OrderModel).where(OrderModel.id == order_id)
        order = await session.scalar(order_stmt)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        items_stmt = select(OrderItemModel).where(OrderItemModel.order_id == order_id)
        item_rows = list((await session.scalars(items_stmt)).all())

        history_stmt = (
            select(OrderStatusHistoryModel)
            .where(OrderStatusHistoryModel.order_id == order_id)
            .order_by(OrderStatusHistoryModel.changed_at)
        )
        history_rows = list((await session.scalars(history_stmt)).all())

        address = await session.get(AddressModel, order.address_id) if order.address_id else None
        payment = (
            await session.get(PaymentMethodModel, order.payment_method_id)
            if order.payment_method_id
            else None
        )

        return _build_order_response(order, item_rows, history_rows, address=address, payment=payment)

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_id: UUID,
        data: OrderCreateRequest,
        cart_items: list[CartItemStored],
        idempotency_key: UUID,
    ) -> dict:
        # 1. Idempotency check
        body_hash = _compute_order_body_hash(data, cart_items)
        existing_stmt = select(OrderModel).where(OrderModel.idempotency_key == idempotency_key)
        existing = await session.scalar(existing_stmt)
        if existing:
            if existing.request_body_hash and existing.request_body_hash != body_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reuse with different request body",
                )
            items_stmt = select(OrderItemModel).where(OrderItemModel.order_id == existing.id)
            item_rows = list((await session.scalars(items_stmt)).all())
            existing_address = (
                await session.get(AddressModel, existing.address_id) if existing.address_id else None
            )
            existing_payment = (
                await session.get(PaymentMethodModel, existing.payment_method_id)
                if existing.payment_method_id
                else None
            )
            return _build_order_response(existing, item_rows, address=existing_address, payment=existing_payment)

        # 2. Validate cart
        if not cart_items:
            from app.schemas import CartValidationResponse, CartResponse, CartValidationIssue, CartIssueType
            empty_cart = CartResponse(
                id=user_id,
                items=[],
                items_count=0,
                subtotal=0,
                is_valid=False,
                updated_at=None,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=CartValidationResponse(
                    is_valid=False,
                    issues=[CartValidationIssue(
                        sku_id=UUID("00000000-0000-0000-0000-000000000000"),
                        type=CartIssueType.OUT_OF_STOCK,
                        message="Cart is empty",
                    )],
                    cart=empty_cart,
                ).model_dump(mode="json"),
            )

        # 3. Compute totals
        subtotal = sum(item.unit_price_at_add * item.quantity for item in cart_items)
        delivery_cost = 0
        total = subtotal + delivery_cost

        # 4. Reserve inventory via B2B
        reserve_items = [
            {"sku_id": str(item.sku_id), "quantity": item.quantity}
            for item in cart_items
        ]
        order_id = uuid4()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                reserve_resp = await client.post(
                    f"{settings.service.B2B_URL}/api/v1/inventory/reserve",
                    json={
                        "idempotency_key": str(idempotency_key),
                        "order_id": str(order_id),
                        "items": reserve_items,
                    },
                    headers={
                        "X-Service-Key": settings.service.SERVICE_KEY,
                        "Content-Type": "application/json",
                    },
                )
                if reserve_resp.status_code == 409:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Insufficient stock for one or more items",
                    )
                if reserve_resp.status_code >= 400:
                    logger.warning(
                        "Reserve endpoint returned %s: %s",
                        reserve_resp.status_code,
                        reserve_resp.text,
                    )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Could not reach inventory reserve endpoint: %s", exc)

        # 5. Create order (mock payment — status PAID immediately)
        now = datetime.now(timezone.utc)
        order = OrderModel(
            id=order_id,
            user_id=user_id,
            status=OrderStatus.PAID,
            address_id=data.address_id,
            payment_method_id=data.payment_method_id,
            comment=data.comment,
            subtotal=subtotal,
            delivery_cost=delivery_cost,
            total=total,
            idempotency_key=idempotency_key,
            request_body_hash=body_hash,
            paid_at=now,
        )
        session.add(order)
        await session.flush()

        # 6. Create order items
        order_item_models: list[OrderItemModel] = []
        for item in cart_items:
            line_total = item.unit_price_at_add * item.quantity
            order_item = OrderItemModel(
                id=uuid4(),
                order_id=order.id,
                sku_id=item.sku_id,
                product_id=item.product_id,
                name=item.name,
                sku_code=getattr(item, "sku_code", None),
                image_url=getattr(item, "image_url", None),
                quantity=item.quantity,
                unit_price=item.unit_price_at_add,
                line_total=line_total,
                seller_id=None,
            )
            session.add(order_item)
            order_item_models.append(order_item)

        # 7. Record status history entries (CREATED then immediately PAID)
        history_models: list[OrderStatusHistoryModel] = [
            OrderStatusHistoryModel(
                id=uuid4(),
                order_id=order.id,
                status=OrderStatus.CREATED,
                reason=None,
            ),
            OrderStatusHistoryModel(
                id=uuid4(),
                order_id=order.id,
                status=OrderStatus.PAID,
                reason="Mock payment — paid immediately",
            ),
        ]
        for h in history_models:
            session.add(h)

        await session.commit()
        await session.refresh(order)
        for oi in order_item_models:
            await session.refresh(oi)
        for h in history_models:
            await session.refresh(h)

        # 8. Fulfill inventory (best-effort)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{settings.service.B2B_URL}/api/v1/inventory/fulfill",
                    json={
                        "order_id": str(order.id),
                        "items": reserve_items,
                    },
                    headers={
                        "X-Service-Key": settings.service.SERVICE_KEY,
                        "Content-Type": "application/json",
                    },
                )
        except Exception as exc:
            logger.warning("Could not reach inventory fulfill endpoint: %s", exc)

        created_address = (
            await session.get(AddressModel, order.address_id) if order.address_id else None
        )
        created_payment = (
            await session.get(PaymentMethodModel, order.payment_method_id)
            if order.payment_method_id
            else None
        )

        return _build_order_response(order, order_item_models, history_models, address=created_address, payment=created_payment)

    @classmethod
    async def cancel(
        cls,
        session: AsyncSession,
        order_id: UUID,
        user_id: UUID,
        reason: str | None = None,
    ) -> dict:
        order_stmt = select(OrderModel).where(OrderModel.id == order_id)
        order = await session.scalar(order_stmt)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        cancellable = {OrderStatus.CREATED, OrderStatus.PAID, OrderStatus.ASSEMBLING}
        if order.status not in cancellable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Order in status {order.status!r} cannot be cancelled",
            )

        cancel_reason_text = reason or "Cancelled by buyer"

        # 1. Move to CANCEL_PENDING
        await session.execute(
            update(OrderModel)
            .where(OrderModel.id == order_id)
            .values(status=OrderStatus.CANCEL_PENDING, cancel_reason=cancel_reason_text)
        )
        session.add(OrderStatusHistoryModel(
            id=uuid4(),
            order_id=order_id,
            status=OrderStatus.CANCEL_PENDING,
            reason=cancel_reason_text,
        ))
        await session.commit()

        # 2. Fetch order items for unreserve call
        items_stmt = select(OrderItemModel).where(OrderItemModel.order_id == order_id)
        item_rows = list((await session.scalars(items_stmt)).all())

        unreserve_items = [
            {"sku_id": str(item.sku_id), "quantity": item.quantity}
            for item in item_rows
        ]

        # 3. Try to unreserve inventory via B2B
        unreserve_ok = False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.service.B2B_URL}/api/v1/inventory/unreserve",
                    json={"order_id": str(order_id), "items": unreserve_items},
                    headers={
                        "X-Service-Key": settings.service.SERVICE_KEY,
                        "Content-Type": "application/json",
                    },
                )
                unreserve_ok = resp.status_code < 400
                if not unreserve_ok:
                    logger.warning(
                        "Unreserve returned %s for order %s: %s",
                        resp.status_code, order_id, resp.text,
                    )
        except Exception as exc:
            logger.warning("Could not reach inventory unreserve endpoint: %s", exc)

        # 4. On success → CANCELLED; on failure → stay CANCEL_PENDING (will be retried later)
        if unreserve_ok:
            await session.execute(
                update(OrderModel)
                .where(OrderModel.id == order_id)
                .values(status=OrderStatus.CANCELLED)
            )
            session.add(OrderStatusHistoryModel(
                id=uuid4(),
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                reason=cancel_reason_text,
            ))
            await session.commit()

        # Re-fetch updated order and history
        order = await session.scalar(select(OrderModel).where(OrderModel.id == order_id))
        history_stmt = (
            select(OrderStatusHistoryModel)
            .where(OrderStatusHistoryModel.order_id == order_id)
            .order_by(OrderStatusHistoryModel.changed_at)
        )
        history_rows = list((await session.scalars(history_stmt)).all())

        address = await session.get(AddressModel, order.address_id) if order.address_id else None
        payment = (
            await session.get(PaymentMethodModel, order.payment_method_id)
            if order.payment_method_id
            else None
        )

        return _build_order_response(order, item_rows, history_rows, address=address, payment=payment)

    @classmethod
    async def has_user_purchased_product(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
    ) -> bool:
        review_allowed_statuses = (
            OrderStatus.PAID,
            OrderStatus.ASSEMBLING,
            OrderStatus.DELIVERING,
            OrderStatus.DELIVERED,
        )

        stmt = (
            select(OrderItemModel.id)
            .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
            .where(
                OrderModel.user_id == user_id,
                OrderItemModel.product_id == product_id,
                OrderModel.status.in_(review_allowed_statuses),
            )
            .limit(1)
        )
        purchased_item_id = await session.scalar(stmt)
        return purchased_item_id is not None

    @classmethod
    async def get_order_status_by_id(cls, session: AsyncSession, order_id: UUID) -> str | None:
        stmt = select(OrderModel).where(OrderModel.id == order_id)
        result = await session.scalar(stmt)
        if not result:
            return None
        return result.status

    @classmethod
    async def move_order_to_reserved(cls, order_data: dict):
        """RabbitMQ consumer handler — updates CREATED order to PAID (legacy flow)."""
        async with async_session_factory() as session:
            order_id = order_data.get("order_id")

            order_status = await cls.get_order_status_by_id(session, order_id)
            if order_status != OrderStatus.CREATED or not order_status:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Order is not in CREATED state",
                )

            stmt = (
                update(OrderModel)
                .where(
                    and_(
                        OrderModel.id == order_id,
                        OrderModel.status == OrderStatus.CREATED,
                    )
                )
                .values({"status": OrderStatus.PAID})
            )
            await session.execute(stmt)
            await session.commit()
