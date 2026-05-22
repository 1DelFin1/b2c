from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ADDRESS_NOT_FOUND
from app.models.addresses import AddressModel
from app.schemas import AddressCreateRequest


class AddressService:
    @staticmethod
    async def get_by_buyer(session: AsyncSession, buyer_id: UUID) -> list[AddressModel]:
        stmt = select(AddressModel).where(AddressModel.buyer_id == buyer_id)
        result = await session.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def create(session: AsyncSession, buyer_id: UUID, data: AddressCreateRequest) -> AddressModel:
        address = AddressModel(buyer_id=buyer_id, **data.model_dump())
        session.add(address)
        await session.commit()
        await session.refresh(address)
        return address

    @staticmethod
    async def update(
        session: AsyncSession, buyer_id: UUID, address_id: UUID, data: AddressCreateRequest
    ) -> AddressModel:
        stmt = select(AddressModel).where(
            AddressModel.id == address_id,
            AddressModel.buyer_id == buyer_id,
        )
        address = await session.scalar(stmt)
        if not address:
            raise ADDRESS_NOT_FOUND

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(address, key, value)
        await session.commit()
        await session.refresh(address)
        return address

    @staticmethod
    async def delete(session: AsyncSession, buyer_id: UUID, address_id: UUID) -> None:
        stmt = select(AddressModel).where(
            AddressModel.id == address_id,
            AddressModel.buyer_id == buyer_id,
        )
        address = await session.scalar(stmt)
        if not address:
            raise ADDRESS_NOT_FOUND
        await session.delete(address)
        await session.commit()
