from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlmodel import select

from database import SessionDep
from models import (
    DashboardSummary,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductStatus,
    TopSellingProduct,
    User,
)
from services.access_token import get_current_admin_or_staff

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def get_current_month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def calculate_percentage_change(current_value: int, previous_value: int) -> float | None:
    if previous_value == 0:
        return None
    return round(((current_value - previous_value) / previous_value) * 100, 2)


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    session: SessionDep,
    current_user: User = Depends(get_current_admin_or_staff),
):
    current_month_start = get_current_month_start()

    total_revenue = session.exec(
        select(func.coalesce(func.sum(Order.total_price), 0)).where(
            Order.status == OrderStatus.COMPLETED,
        )
    ).one()
    revenue_at_previous_month_end = session.exec(
        select(func.coalesce(func.sum(Order.total_price), 0)).where(
            Order.status == OrderStatus.COMPLETED,
            Order.completed_at < current_month_start,
        )
    ).one()

    total_orders = session.exec(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.COMPLETED,
        )
    ).one()
    orders_at_previous_month_end = session.exec(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.COMPLETED,
            Order.completed_at < current_month_start,
        )
    ).one()

    total_customers = session.exec(
        select(func.count(User.id))
    ).one()
    customers_at_previous_month_end = session.exec(
        select(func.count(User.id)).where(
            User.created_at < current_month_start,
        )
    ).one()
    total_products = session.exec(
        select(func.count(Product.id)).where(
            Product.status == ProductStatus.PUBLISHED
        )
    ).one()

    return DashboardSummary(
        total_revenue=total_revenue,
        revenue_change_percent=calculate_percentage_change(
            total_revenue,
            revenue_at_previous_month_end,
        ),
        total_orders=total_orders,
        orders_change_percent=calculate_percentage_change(
            total_orders,
            orders_at_previous_month_end,
        ),
        total_customers=total_customers,
        customers_change_percent=calculate_percentage_change(
            total_customers,
            customers_at_previous_month_end,
        ),
        total_products=total_products,
    )


@router.get("/top-products", response_model=list[TopSellingProduct])
def get_top_selling_products(
    session: SessionDep,
    current_user: User = Depends(get_current_admin_or_staff),
    limit: int = Query(5, ge=1, le=50),
):
    statement = (
        select(
            Product,
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.quantity * OrderItem.price_at_purchase), 0),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == OrderStatus.COMPLETED)
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .options(selectinload(Product.variants))
        .limit(limit)
    )

    products = session.exec(statement).all()
    return [
        TopSellingProduct(
            product=product,
            quantity_sold=quantity_sold,
            revenue=revenue,
        )
        for product, quantity_sold, revenue in products
    ]