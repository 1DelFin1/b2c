from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.api.deps import SessionDep, get_current_active_auth_buyer, get_user_id
from app.schemas import (
    CancelOrderRequest,
    OrderCreateRequest,
    OrderResponse,
    PaginatedOrders,
)
from app.services.cart_service import CartService
from app.services.order_service import OrderService

orders_v1_router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@orders_v1_router.get("", response_model=PaginatedOrders)
async def list_orders(
    session: SessionDep,
    status: Annotated[Literal["CREATED", "PAID", "ASSEMBLING", "DELIVERING", "DELIVERED", "CANCELLED", "CANCEL_PENDING"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    items, total = await OrderService.get_list(
        session,
        user_id=user_id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return PaginatedOrders(
        items=items,
        total_count=total,
        limit=limit,
        offset=offset,
    )


@orders_v1_router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    request: Request,
    session: SessionDep,
    body: OrderCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)

    try:
        idem_uuid = UUID(idempotency_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be a valid UUID",
        )

    cart_items = await CartService.get_items(str(user_id))

    order_dict = await OrderService.create(
        session=session,
        user_id=user_id,
        data=body,
        cart_items=cart_items,
        idempotency_key=idem_uuid,
    )

    await CartService.clear(str(user_id))

    return order_dict


@orders_v1_router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    session: SessionDep,
    order_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    return await OrderService.get_by_id(session, order_id=order_id, user_id=user_id)


@orders_v1_router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    session: SessionDep,
    order_id: UUID,
    body: CancelOrderRequest | None = None,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    reason = body.reason if body else None
    return await OrderService.cancel(session, order_id=order_id, user_id=user_id, reason=reason)
