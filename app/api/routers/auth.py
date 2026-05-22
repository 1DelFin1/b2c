from __future__ import annotations

from fastapi import APIRouter, Header, status

from app.api.deps import BuyerDep, SessionDep
from app.api.utils import Authorization, RefreshTokenService
from app.schemas import BuyerRegisterRequest, LoginRequest, RefreshRequest, TokenResponse
from app.services.buyer_service import BuyerService
from app.services.cart_service import CartService

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(session: SessionDep, data: BuyerRegisterRequest):
    buyer = await BuyerService.create(session, data)

    from app.api.utils import JWTAuthenticator
    from uuid import UUID

    access_payload = {
        "sub": str(buyer.id),
        "email": buyer.email,
        "account_type": "buyer",
    }
    from app.core.config import settings
    access_token = JWTAuthenticator.create_access_token(access_payload)
    refresh_token = await RefreshTokenService.create(session, str(buyer.id), "buyer")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=UUID(str(buyer.id)),
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    session: SessionDep,
    data: LoginRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    token_response = await Authorization.login(session, data.email, data.password)

    # Merge guest cart if X-Session-Id is present
    if x_session_id:
        user_id_str = str(token_response.user_id)
        guest_items = await CartService.get_items(x_session_id)
        if guest_items:
            user_items = await CartService.get_items(user_id_str)
            merged = {item.sku_id: item for item in user_items}
            for guest_item in guest_items:
                if guest_item.sku_id in merged:
                    existing = merged[guest_item.sku_id]
                    existing.quantity = max(existing.quantity, guest_item.quantity)
                else:
                    merged[guest_item.sku_id] = guest_item
            await CartService._save_items(user_id_str, list(merged.values()))
            await CartService.clear(x_session_id)

    return token_response


@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_token(session: SessionDep, data: RefreshRequest):
    return await Authorization.refresh(session, data.refresh_token)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(session: SessionDep, buyer: BuyerDep):
    await RefreshTokenService.revoke_all_for_account(session, str(buyer["sub"]))
