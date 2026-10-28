from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import selectinload
from sqlmodel import select, col
from models import (
    Bundle,
    BundleItem,
    Cart,
    CartItem,
    CheckoutRead,
    Order,
    OrderBundleComponent,
    OrderItem,
    OrderRead,
    OrderStatus,
    OrderStatusUpdate,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    User,
    Product,
    ProductStatus,
    ProductVariant,
)
from database import SessionDep
from services.access_token import (
    get_current_admin,
    get_current_admin_or_staff,
    get_current_user,
)
from services.payment_lifecycle import initialize_payment, verify_payment
from services.inventory import restore_inventory_for_order, validate_inventory_selection
from services.paystack import PaystackError, paystack_service
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

router = APIRouter(prefix="/order", tags=["Orders"])

_ORDER_READ_OPTIONS = (
    selectinload(Order.order_items).selectinload(OrderItem.product),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle)
    .selectinload(Bundle.items)
    .selectinload(BundleItem.product)
    .selectinload(Product.variants)
    .selectinload(ProductVariant.sub_variants),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle)
    .selectinload(Bundle.items)
    .selectinload(BundleItem.product_variant),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle)
    .selectinload(Bundle.items)
    .selectinload(BundleItem.product_sub_variant),
    selectinload(Order.order_items).selectinload(OrderItem.product_variant),
    selectinload(Order.order_items).selectinload(OrderItem.product_sub_variant),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle_components)
    .selectinload(OrderBundleComponent.product)
    .selectinload(Product.variants)
    .selectinload(ProductVariant.sub_variants),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle_components)
    .selectinload(OrderBundleComponent.product_variant),
    selectinload(Order.order_items)
    .selectinload(OrderItem.bundle_components)
    .selectinload(OrderBundleComponent.product_sub_variant),
    selectinload(Order.user),
)

def load_order_for_read(session: SessionDep, order_id: UUID) -> Order:
    return session.exec(
        select(Order)
        .where(Order.id == order_id)
        .options(*_ORDER_READ_OPTIONS)
    ).one()

def generate_next_order_public_id(session: SessionDep) -> str:
    public_ids = session.exec(select(Order.public_id)).all()
    highest_number = 0

    for public_id in public_ids:
        if not public_id.startswith("ord-"):
            continue

        try:
            order_number = int(public_id.removeprefix("ord-"))
        except ValueError:
            continue

        highest_number = max(highest_number, order_number)

    return f"ord-{highest_number + 1:04d}"

@router.post("", response_model=CheckoutRead, status_code=status.HTTP_201_CREATED)
def create_order(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    # 1. Load cart snapshot
    cart = session.exec(
        select(Cart)
        .where(Cart.user_id == current_user.id)
        .options(
            selectinload(Cart.items).selectinload(CartItem.product),
            selectinload(Cart.items).selectinload(CartItem.product_variant),
            selectinload(Cart.items).selectinload(CartItem.product_sub_variant),
            selectinload(Cart.items)
            .selectinload(CartItem.bundle)
            .selectinload(Bundle.items)
            .selectinload(BundleItem.product),
            selectinload(Cart.items)
            .selectinload(CartItem.bundle)
            .selectinload(Bundle.items)
            .selectinload(BundleItem.product_variant),
            selectinload(Cart.items)
            .selectinload(CartItem.bundle)
            .selectinload(Bundle.items)
            .selectinload(BundleItem.product_sub_variant),
        )
    ).first()
    if not cart or not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty",
        )
    # 2. Build order items from cart items
    order_items: list[OrderItem] = []
    for cart_item in cart.items:
        if cart_item.bundle_id is not None:
            bundle = cart_item.bundle
            if not bundle or bundle.status != ProductStatus.PUBLISHED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A bundle in the cart is no longer available",
                )
            if any(
                component.product is None
                or component.product.status != ProductStatus.PUBLISHED
                for component in bundle.items
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A product in {bundle.name} is no longer available",
                )
            if cart_item.quantity > bundle.quantity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Only {bundle.quantity} units of {bundle.name} are available",
                )
            order_items.append(
                OrderItem(
                    bundle_id=bundle.id,
                    quantity=cart_item.quantity,
                    price_at_purchase=bundle.price,
                    bundle_components=[
                        OrderBundleComponent(
                            product_id=component.product_id,
                            product_variant_id=component.product_variant_id,
                            product_sub_variant_id=component.product_sub_variant_id,
                            quantity_per_bundle=component.quantity,
                        )
                        for component in bundle.items
                    ],
                )
            )
            continue

        product = cart_item.product
        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {cart_item.product_id} not found",
            )
        validate_inventory_selection(
            session,
            product,
            cart_item.product_variant_id,
            cart_item.product_sub_variant_id,
            cart_item.quantity,
        )
        order_items.append(
            OrderItem(
                product_id=cart_item.product_id,
                product_variant_id=cart_item.product_variant_id,
                product_sub_variant_id=cart_item.product_sub_variant_id,
                quantity=cart_item.quantity,
                price_at_purchase=product.price,  # snapshot unit price
            )
        )
    # 3. Compute totals from order_items (not from cart directly)
    total_products = sum(item.quantity for item in order_items)
    total_price = sum(item.quantity * item.price_at_purchase for item in order_items)
    # 4. Create order
    order = Order(
        public_id=generate_next_order_public_id(session),
        user_id=current_user.id,
        total_price=total_price,
        total_products=total_products,
    )
    session.add(order)
    session.flush()  # get order.id before linking items
    # 5. Attach items to order
    for item in order_items:
        item.order_id = order.id
        session.add(item)
    # 6. Initialize the server-owned Paystack transaction.
    payment = initialize_payment(session, order=order, user=current_user)
    # 7. Clear the cart after the checkout snapshot and payment session exist.
    for cart_item in cart.items:
        session.delete(cart_item)
    session.commit()
    session.refresh(order)
    # Eager-load relationships for response
    order = session.exec(
        select(Order)
        .where(Order.id == order.id)
        .options(*_ORDER_READ_OPTIONS)
    ).one()
    session.refresh(payment)
    return CheckoutRead(order=order, payment=payment)

@router.get("", response_model=list[OrderRead])
def get_orders(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(10, description="Number of items per page", ge=1, le=50),
    status: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
):
    statement = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .options(*_ORDER_READ_OPTIONS)
        .order_by(Order.created_at.desc())
    )

    if status:
        statement = statement.where(Order.status == status)

    offset = (page - 1) * page_size
    statement = statement.offset(offset).limit(page_size)

    return session.exec(statement).all()

@router.get("/all", response_model=list[OrderRead])
def get_all_orders(
    session: SessionDep,
    _: User = Depends(get_current_admin),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(10, description="Number of items per page", ge=1, le=50),
    status: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
    name: Optional[str] = Query(
        None,
        description="Filter orders by the name of the user who owns the order (partial match)",
    ),
):
    statement = (
        select(Order)
        .join(User, Order.user_id == User.id)
        .options(*_ORDER_READ_OPTIONS)
        .order_by(Order.created_at.desc())
    )

    if status:
        statement = statement.where(Order.status == status)

    if name:
        statement = statement.where(col(User.name).contains(name))

    offset = (page - 1) * page_size
    statement = statement.offset(offset).limit(page_size)

    return session.exec(statement).all()

@router.patch("/{order_id}", response_model=OrderRead)
def update_order_status(
    order_id: UUID,
    update: OrderStatusUpdate,
    session: SessionDep,
    _: User = Depends(get_current_admin),
):
    order = session.exec(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .options(*_ORDER_READ_OPTIONS)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == update.status:
        return order

    now = datetime.now(timezone.utc)
    previous_status = order.status
    order.status = update.status

    if update.status == OrderStatus.CONFIRMED and order.confirmed_at is None:
        order.confirmed_at = now
    elif update.status == OrderStatus.COMPLETED:
        order.completed_at = now
        if previous_status != OrderStatus.COMPLETED:
            user = session.get(User, order.user_id)
            if user:
                user.total_orders += 1
                user.total_spent += order.total_price
                session.add(user)
    elif update.status == OrderStatus.CANCELLED:
        order.cancelled_at = now
    elif update.status == OrderStatus.REFUNDED:
        order.refunded_at = now

    session.add(order)
    session.commit()
    return load_order_for_read(session, order_id)

@router.patch("/{order_id}/cancel", response_model=OrderRead)
def cancel_order(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    order = session.exec(
        select(Order)
        .where(Order.id == order_id, Order.user_id == current_user.id)
        .with_for_update()
        .options(*_ORDER_READ_OPTIONS)
    ).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status == OrderStatus.REFUND_PENDING:
        return order

    if order.status == OrderStatus.PROCESSING:
        latest_payment = session.exec(
            select(Payment)
            .where(Payment.order_id == order.id)
            .order_by(Payment.created_at.desc())
        ).first()
        if latest_payment:
            verify_payment(session, latest_payment)
            session.flush()
            session.refresh(order)

    if order.status in {OrderStatus.PENDING, OrderStatus.FAILED}:
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(timezone.utc)
        session.add(order)
        session.commit()
        session.refresh(order)
        return order

    if order.status != OrderStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only unpaid or confirmed, unfulfilled orders can be cancelled",
        )

    now = datetime.now(timezone.utc)
    confirmed_at = order.confirmed_at
    if confirmed_at and confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
    if not confirmed_at or now > confirmed_at + timedelta(minutes=30):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The 30-minute refund window has expired",
        )

    payment = session.exec(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        .order_by(Payment.paid_at.desc())
    ).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No refundable payment was found",
        )

    existing_refund = session.exec(
        select(Refund).where(Refund.payment_id == payment.id)
    ).first()
    if existing_refund:
        return order

    try:
        result = paystack_service.create_full_refund(
            transaction_reference=payment.reference,
            merchant_note=f"Customer cancelled {order.public_id} within 30 minutes",
        )
    except PaystackError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    provider_status = str(result.get("status", "pending")).replace("-", "_")
    refund_status = {
        "pending": RefundStatus.PENDING,
        "processing": RefundStatus.PROCESSING,
        "needs_attention": RefundStatus.NEEDS_ATTENTION,
        "processed": RefundStatus.PROCESSED,
    }.get(provider_status, RefundStatus.PENDING)
    refund = Refund(
        payment_id=payment.id,
        provider_refund_id=(
            str(result["id"]) if result.get("id") is not None else None
        ),
        amount_kobo=payment.amount_kobo,
        status=refund_status,
    )
    order.cancelled_at = now
    if refund_status == RefundStatus.PROCESSED:
        refund.processed_at = now
        payment.status = PaymentStatus.REFUNDED
        order.status = OrderStatus.REFUNDED
        order.refunded_at = now
        restore_inventory_for_order(session, order)
    else:
        payment.status = PaymentStatus.REFUND_PENDING
        order.status = OrderStatus.REFUND_PENDING
    session.add(refund)
    session.add(payment)
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.patch("/{order_id}/complete", response_model=OrderRead)
def complete_order(
    order_id: UUID,
    session: SessionDep,
    _: User = Depends(get_current_admin_or_staff),
):
    order = session.exec(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .options(*_ORDER_READ_OPTIONS)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == OrderStatus.COMPLETED:
        return order
    if order.status != OrderStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed orders can be completed",
        )

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.COMPLETED
    order.completed_at = now
    user = session.get(User, order.user_id)
    if user:
        user.total_orders += 1
        user.total_spent += order.total_price
        session.add(user)
    session.add(order)
    session.commit()
    session.refresh(order)
    return order

@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    order = session.exec(
        select(Order)
        .where(Order.id == order_id, Order.user_id == current_user.id)
        .options(*_ORDER_READ_OPTIONS)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order