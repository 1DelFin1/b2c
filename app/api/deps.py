from __future__ import annotations

from typing import Annotated, AsyncGenerator
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory


async def get_session() -> AsyncGenerator:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt.JWT_SECRET_KEY,
            algorithms=[settings.jwt.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_id(payload: dict) -> UUID:
    """Extract user UUID from JWT payload (sub or id field)."""
    raw = payload.get("sub") or payload.get("id")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
        )
    try:
        return UUID(str(raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier in token",
        )


async def get_current_auth_user(request: Request) -> dict:
    """Require a valid JWT token of any account_type."""
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(token)


async def get_current_active_auth_buyer(request: Request) -> dict:
    """Require a valid JWT token with account_type == 'buyer'."""
    payload = await get_current_auth_user(request)
    if payload.get("account_type") != "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyer account required",
        )
    return payload


def get_optional_user_id(request: Request) -> UUID | None:
    """Return user UUID from JWT if present, else None (no error)."""
    token = _extract_bearer(request)
    if not token:
        return None
    try:
        payload = _decode_token(token)
        return get_user_id(payload)
    except HTTPException:
        return None


async def verify_service_key(x_service_key: str = Header(..., alias="X-Service-Key")) -> str:
    """Validate X-Service-Key header for internal service-to-service calls."""
    if x_service_key != settings.service.SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service key",
        )
    return x_service_key


BuyerDep = Annotated[dict, Depends(get_current_active_auth_buyer)]
ServiceKeyDep = Annotated[str, Depends(verify_service_key)]
