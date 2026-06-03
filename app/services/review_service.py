from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rabbit_config import rabbit_broker
from app.exceptions import REVIEW_NOT_FOUND, REVIEW_ALREADY_EXISTS
from app.models.reviews import ReviewModel
from app.schemas import ReviewCreate, ReviewUpdate, PaginatedReviews

logger = logging.getLogger(__name__)


class ReviewService:
    @staticmethod
    async def get_by_id(session: AsyncSession, review_id: int) -> ReviewModel:
        stmt = select(ReviewModel).where(ReviewModel.id == review_id)
        review = await session.scalar(stmt)
        if not review:
            raise REVIEW_NOT_FOUND
        return review

    @staticmethod
    async def get_by_product(
        session: AsyncSession,
        product_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginatedReviews:
        base_q = select(ReviewModel).where(ReviewModel.product_id == product_id)
        count_stmt = select(func.count()).select_from(base_q.subquery())
        total = (await session.scalar(count_stmt)) or 0

        reviews_stmt = (
            base_q
            .order_by(ReviewModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        reviews = list((await session.scalars(reviews_stmt)).all())

        return PaginatedReviews(
            items=reviews,
            total_count=int(total),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    async def create(session: AsyncSession, user_id: UUID, data: ReviewCreate) -> ReviewModel:
        # Check for existing review
        existing = await session.scalar(
            select(ReviewModel).where(
                ReviewModel.user_id == user_id,
                ReviewModel.product_id == data.product_id,
            )
        )
        if existing:
            raise REVIEW_ALREADY_EXISTS

        # Check if user has purchased the product
        from app.services.order_service import OrderService
        has_purchased = await OrderService.has_user_purchased_product(
            session, user_id, data.product_id
        )
        if not has_purchased:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You can only review products you have purchased"},
            )

        review = ReviewModel(
            user_id=user_id,
            product_id=data.product_id,
            text=data.text,
            rating=data.rating,
        )
        session.add(review)
        await session.commit()
        await session.refresh(review)

        # Publish review event to RabbitMQ (best-effort)
        try:
            await rabbit_broker.publish(
                {
                    "review_id": review.id,
                    "product_id": str(review.product_id),
                    "user_id": str(review.user_id),
                    "rating": review.rating,
                },
                routing_key="reviews",
            )
        except Exception as exc:
            logger.warning("Could not publish review event: %s", exc)

        return review

    @staticmethod
    async def update(
        session: AsyncSession,
        review_id: int,
        user_id: UUID,
        data: ReviewUpdate,
    ) -> ReviewModel:
        stmt = select(ReviewModel).where(ReviewModel.id == review_id)
        review = await session.scalar(stmt)
        if not review:
            raise REVIEW_NOT_FOUND
        if review.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You can only update your own reviews"},
            )

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(review, key, value)

        session.add(review)
        await session.commit()
        await session.refresh(review)
        return review

    @staticmethod
    async def delete(session: AsyncSession, review_id: int, user_id: UUID) -> None:
        stmt = select(ReviewModel).where(ReviewModel.id == review_id)
        review = await session.scalar(stmt)
        if not review:
            raise REVIEW_NOT_FOUND
        if review.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You can only delete your own reviews"},
            )

        await session.delete(review)
        await session.commit()
