from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.exceptions import BUYER_NOT_FOUND, BUYER_ALREADY_EXISTS
from app.models.buyers import BuyerModel
from app.schemas import BuyerRegisterRequest, BuyerUpdate


class BuyerService:
    @staticmethod
    async def get_by_id(session: AsyncSession, buyer_id: UUID) -> BuyerModel:
        stmt = select(BuyerModel).where(BuyerModel.id == buyer_id)
        buyer = await session.scalar(stmt)
        if not buyer:
            raise BUYER_NOT_FOUND
        return buyer

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> BuyerModel | None:
        stmt = select(BuyerModel).where(BuyerModel.email == email)
        return await session.scalar(stmt)

    @staticmethod
    async def create(session: AsyncSession, data: BuyerRegisterRequest) -> BuyerModel:
        existing = await session.scalar(
            select(BuyerModel).where(BuyerModel.email == data.email)
        )
        if existing:
            raise BUYER_ALREADY_EXISTS

        buyer = BuyerModel(
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            hashed_password=get_password_hash(data.password),
        )
        session.add(buyer)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "Email already registered"},
            )
        await session.refresh(buyer)
        return buyer

    @staticmethod
    async def update(session: AsyncSession, data: BuyerUpdate, buyer_id: UUID) -> BuyerModel:
        stmt = select(BuyerModel).where(BuyerModel.id == buyer_id)
        buyer = await session.scalar(stmt)
        if not buyer:
            raise BUYER_NOT_FOUND

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None or key in update_data:
                setattr(buyer, key, value)

        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)
        return buyer

    @staticmethod
    async def delete(session: AsyncSession, buyer_id: UUID) -> dict:
        stmt = select(BuyerModel).where(BuyerModel.id == buyer_id)
        buyer = await session.scalar(stmt)
        if not buyer:
            raise BUYER_NOT_FOUND

        buyer.is_active = False
        await session.commit()
        return {"ok": True}
