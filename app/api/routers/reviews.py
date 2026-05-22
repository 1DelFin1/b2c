from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import SessionDep, get_current_active_auth_buyer, get_user_id
from app.schemas import ReviewCreate, ReviewUpdate, ReviewResponse, PaginatedReviews
from app.services.review_service import ReviewService

reviews_router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@reviews_router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    session: SessionDep,
    data: ReviewCreate,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    return await ReviewService.create(session, user_id, data)


@reviews_router.get("/product/{product_id}", response_model=PaginatedReviews)
async def list_product_reviews(
    session: SessionDep,
    product_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return await ReviewService.get_by_product(session, product_id, limit=limit, offset=offset)


@reviews_router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(session: SessionDep, review_id: int):
    return await ReviewService.get_by_id(session, review_id)


@reviews_router.patch("/{review_id}", response_model=ReviewResponse)
async def update_review(
    session: SessionDep,
    review_id: int,
    data: ReviewUpdate,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    return await ReviewService.update(session, review_id, user_id, data)


@reviews_router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    session: SessionDep,
    review_id: int,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    await ReviewService.delete(session, review_id, user_id)
