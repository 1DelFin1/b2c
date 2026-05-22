from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import SessionDep, get_current_active_auth_buyer, get_user_id
from app.schemas import (
    BuyerResponse,
    BuyerUpdate,
    AddressCreateRequest,
    AddressResponse,
    PaymentMethodCreateRequest,
    PaymentMethodResponse,
)
from app.services.buyer_service import BuyerService
from app.services.address_service import AddressService
from app.services.payment_method_service import PaymentMethodService

buyers_router = APIRouter(prefix="/api/v1/buyers", tags=["buyers"])


@buyers_router.get("/me", response_model=BuyerResponse)
async def get_buyer_profile(
    session: SessionDep,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    buyer = await BuyerService.get_by_id(session, buyer_id)
    return buyer


@buyers_router.patch("/me", response_model=BuyerResponse)
async def update_buyer_profile(
    session: SessionDep,
    data: BuyerUpdate,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    await BuyerService.update(session, data, buyer_id)
    return await BuyerService.get_by_id(session, buyer_id)


@buyers_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_buyer(
    session: SessionDep,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    await BuyerService.delete(session, buyer_id)


# ── Addresses ─────────────────────────────────────────────────────────────────

@buyers_router.get("/me/addresses", response_model=list[AddressResponse])
async def list_addresses(
    session: SessionDep,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    return await AddressService.get_by_buyer(session, buyer_id)


@buyers_router.post("/me/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    session: SessionDep,
    data: AddressCreateRequest,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    return await AddressService.create(session, buyer_id, data)


@buyers_router.patch("/me/addresses/{address_id}", response_model=AddressResponse)
async def update_address(
    session: SessionDep,
    address_id: UUID,
    data: AddressCreateRequest,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    return await AddressService.update(session, buyer_id, address_id, data)


@buyers_router.delete("/me/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    session: SessionDep,
    address_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    await AddressService.delete(session, buyer_id, address_id)


# ── Payment Methods ───────────────────────────────────────────────────────────

@buyers_router.get("/me/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    session: SessionDep,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    return await PaymentMethodService.get_by_buyer(session, buyer_id)


@buyers_router.post("/me/payment-methods", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_method(
    session: SessionDep,
    data: PaymentMethodCreateRequest,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    return await PaymentMethodService.create(session, buyer_id, data)


@buyers_router.delete("/me/payment-methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    session: SessionDep,
    method_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    buyer_id = get_user_id(payload)
    await PaymentMethodService.delete(session, buyer_id, method_id)
