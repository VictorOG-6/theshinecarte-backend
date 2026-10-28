from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import selectinload
from models import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductRead,
    Review,
    ReviewCreate,
    ReviewRead,
    ReviewUpdate,
    User,
)
from database import SessionDep
from services.access_token import get_current_admin, get_current_user
from sqlmodel import select
from uuid import UUID
from typing import Optional

router = APIRouter(prefix="/review", tags=["Reviews"])

def has_completed_order_for_product(
    product_id: UUID,
    session: SessionDep,
    current_user: User,
) -> bool:
    ordered_product = session.exec(
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.user_id == current_user.id,
            Order.status == OrderStatus.COMPLETED,
            OrderItem.product_id == product_id,
        )
    ).first()
    return ordered_product is not None

@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
def create_review(review: ReviewCreate, session: SessionDep, current_user: User = Depends(get_current_user)):
    if not has_completed_order_for_product(review.product_id, session, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only review products from completed orders",
        )

    new_review = Review(**review.model_dump(), user_id=current_user.id)
    current_user.total_reviews += 1
    session.add(new_review)
    session.add(current_user)
    session.commit()
    session.refresh(new_review)

    created_review = session.exec(
        select(Review)
        .where(Review.id == new_review.id)
        .options(
            selectinload(Review.product),
            selectinload(Review.user),
        )
    ).one()
    return created_review

@router.get("", response_model=list[ReviewRead])
def get_reviews(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    product_id: Optional[UUID] = None,
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(20, description="Number of items per page", ge=1, le=50),
):
    statement = (
        select(Review)
        .where(Review.user_id == current_user.id)
        .options(
            selectinload(Review.product),
            selectinload(Review.user),
        )
        .order_by(Review.created_at.desc())
    )
    if product_id:
        statement = statement.where(Review.product_id == product_id)

    offset = (page - 1) * page_size
    statement = statement.offset(offset).limit(page_size)

    return session.exec(statement).all()

@router.get("/all", response_model=list[ReviewRead])
def get_all_reviews(
    session: SessionDep,
    _: User = Depends(get_current_admin),
    product_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(20, description="Number of items per page", ge=1, le=50),
    ):
    statement = (
        select(Review)
        .options(
            selectinload(Review.product),
            selectinload(Review.user),
        )
        .order_by(Review.created_at.desc())
    )
    if product_id:
        statement = statement.where(Review.product_id == product_id)
    if user_id:
        statement = statement.where(Review.user_id == user_id)
    
    offset = (page - 1) * page_size
    statement = statement.offset(offset).limit(page_size)

    return session.exec(statement).all()

@router.get("/eligible-products", response_model=list[ProductRead])
def get_review_eligible_products(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(20, description="Number of items per page", ge=1, le=50),
):
    statement = (
        select(Product)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.user_id == current_user.id,
            Order.status == OrderStatus.COMPLETED,
        )
        .distinct()
        .order_by(Product.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    products = session.exec(statement).all()
    return products

@router.put("/{review_id}", response_model=ReviewRead, status_code=status.HTTP_202_ACCEPTED)
def update_review(review_id: UUID, review_update: ReviewUpdate, session: SessionDep, current_user: User = Depends(get_current_user)):
    updated_review = session.exec(select(Review).where(Review.id == review_id, Review.user_id == current_user.id)).first()
    if not updated_review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    review_data = review_update.model_dump(exclude_unset=True)
    updated_review.sqlmodel_update(review_data)

    session.add(updated_review)
    session.commit()
    session.refresh(updated_review)
    return updated_review

@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(review_id: UUID, session: SessionDep, current_user: User = Depends(get_current_user)):
    deleted_review = session.exec(select(Review).where(Review.id == review_id, Review.user_id == current_user.id)).first()
    if not deleted_review:
        raise HTTPException(status_code=404, detail="Review not found")
    current_user.total_reviews = max(0, current_user.total_reviews - 1)
    session.delete(deleted_review)
    session.add(current_user)
    session.commit()
    return None