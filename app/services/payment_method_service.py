from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PAYMENT_METHOD_NOT_FOUND
from app.models.payment_methods import PaymentMethodModel
from app.schemas import PaymentMethodCreateRequest


class PaymentMethodService:
    @staticmethod
    async def get_by_buyer(session: AsyncSession, buyer_id: UUID) -> list[PaymentMethodModel]:
        stmt = select(PaymentMethodModel).where(PaymentMethodModel.buyer_id == buyer_id)
        result = await session.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def create(
        session: AsyncSession, buyer_id: UUID, data: PaymentMethodCreateRequest
    ) -> PaymentMethodModel:
        method = PaymentMethodModel(buyer_id=buyer_id, **data.model_dump())
        session.add(method)
        await session.commit()
        await session.refresh(method)
        return method

    @staticmethod
    async def delete(session: AsyncSession, buyer_id: UUID, method_id: UUID) -> None:
        stmt = select(PaymentMethodModel).where(
            PaymentMethodModel.id == method_id,
            PaymentMethodModel.buyer_id == buyer_id,
        )
        method = await session.scalar(stmt)
        if not method:
            raise PAYMENT_METHOD_NOT_FOUND
        await session.delete(method)
        await session.commit()
