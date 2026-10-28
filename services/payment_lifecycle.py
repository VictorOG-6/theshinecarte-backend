from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlmodel import Session, select

from models import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    User,
)
from services.inventory import (
    commit_inventory_for_order,
    restore_inventory_for_order,
)
from services.paystack import PaystackError, naira_to_kobo, paystack_service


TERMINAL_PAYMENT_STATUSES = {
    PaymentStatus.SUCCESS,
    PaymentStatus.REFUND_PENDING,
    PaymentStatus.REFUNDED,
}


def _parse_paystack_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def initialize_payment(
    session: Session,
    *,
    order: Order,
    user: User,
) -> Payment:
    existing = session.exec(
        select(Payment).where(
            Payment.order_id == order.id,
            Payment.status.in_(TERMINAL_PAYMENT_STATUSES),
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This order already has a successful payment",
        )
    if order.status not in {
        OrderStatus.PENDING,
        OrderStatus.PROCESSING,
        OrderStatus.FAILED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment cannot be initialized for this order",
        )

    reference = f"{order.public_id}-{uuid4().hex[:16]}"
    amount_kobo = naira_to_kobo(order.total_price)
    try:
        result = paystack_service.initialize_transaction(
            email=str(user.email),
            amount_kobo=amount_kobo,
            reference=reference,
            order_id=str(order.id),
        )
    except PaystackError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    payment = Payment(
        order_id=order.id,
        reference=reference,
        amount_kobo=amount_kobo,
        currency="NGN",
        status=PaymentStatus.PENDING,
        access_code=result.get("access_code"),
        authorization_url=result.get("authorization_url"),
    )
    order.status = OrderStatus.PROCESSING
    session.add(payment)
    session.add(order)
    return payment


def apply_transaction_result(
    session: Session,
    *,
    payment: Payment,
    data: dict[str, Any],
) -> Payment:
    order = session.exec(
        select(Order)
        .where(Order.id == payment.order_id)
        .with_for_update()
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    user = session.get(User, order.user_id)
    customer = data.get("customer") or {}

    if (
        data.get("reference") != payment.reference
        or int(data.get("amount", -1)) != payment.amount_kobo
        or data.get("currency") != payment.currency
        or (customer.get("email") and str(customer["email"]).lower() != str(user.email).lower())
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paystack transaction details do not match the order",
        )

    provider_status = data.get("status")
    payment.provider_transaction_id = str(data.get("id")) if data.get("id") else None
    if provider_status == "success":
        if payment.status in {
            PaymentStatus.REFUND_PENDING,
            PaymentStatus.REFUNDED,
        }:
            return payment
        if (
            payment.status == PaymentStatus.SUCCESS
            and order.inventory_committed_at is not None
        ):
            return payment
        commit_inventory_for_order(session, order)
        payment.status = PaymentStatus.SUCCESS
        if payment.paid_at is None:
            payment.paid_at = (
                _parse_paystack_datetime(data.get("paid_at"))
                or _parse_paystack_datetime(data.get("paidAt"))
                or datetime.now(timezone.utc)
            )
        if order.status not in {
            OrderStatus.COMPLETED,
            OrderStatus.REFUND_PENDING,
            OrderStatus.REFUNDED,
        }:
            order.status = OrderStatus.CONFIRMED
            if order.confirmed_at is None:
                order.confirmed_at = payment.paid_at
    elif provider_status in {"failed", "abandoned"}:
        payment.status = (
            PaymentStatus.ABANDONED
            if provider_status == "abandoned"
            else PaymentStatus.FAILED
        )
        if order.status in {
            OrderStatus.PENDING,
            OrderStatus.PROCESSING,
            OrderStatus.FAILED,
        }:
            order.status = OrderStatus.FAILED
    else:
        payment.status = PaymentStatus.PENDING
        if order.status in {OrderStatus.PENDING, OrderStatus.FAILED}:
            order.status = OrderStatus.PROCESSING

    session.add(payment)
    session.add(order)
    return payment


def verify_payment(session: Session, payment: Payment) -> Payment:
    try:
        data = paystack_service.verify_transaction(payment.reference)
    except PaystackError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return apply_transaction_result(session, payment=payment, data=data)


def apply_refund_event(
    session: Session,
    *,
    event_type: str,
    data: dict[str, Any],
) -> bool:
    transaction = data.get("transaction") or {}
    reference = (
        data.get("transaction_reference")
        or (transaction.get("reference") if isinstance(transaction, dict) else None)
    )
    if not reference:
        return False

    payment = session.exec(
        select(Payment).where(Payment.reference == reference)
    ).first()
    if not payment:
        return False
    refund = session.exec(
        select(Refund).where(Refund.payment_id == payment.id)
    ).first()
    if not refund:
        return False
    order = session.exec(
        select(Order)
        .where(Order.id == payment.order_id)
        .with_for_update()
    ).first()
    if not order:
        return False
    if refund.status == RefundStatus.PROCESSED:
        return True

    try:
        refund_amount = int(data.get("amount", payment.amount_kobo))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid refund amount") from exc
    if (
        refund_amount != payment.amount_kobo
        or data.get("currency", payment.currency) != payment.currency
    ):
        raise HTTPException(
            status_code=400,
            detail="Paystack refund details do not match the payment",
        )

    provider_refund_id = data.get("refund_reference") or data.get("id")
    if provider_refund_id is not None:
        refund.provider_refund_id = str(provider_refund_id)

    status_by_event = {
        "refund.pending": RefundStatus.PENDING,
        "refund.processing": RefundStatus.PROCESSING,
        "refund.needs-attention": RefundStatus.NEEDS_ATTENTION,
        "refund.failed": RefundStatus.FAILED,
        "refund.processed": RefundStatus.PROCESSED,
    }
    refund.status = status_by_event[event_type]

    if refund.status == RefundStatus.PROCESSED:
        now = datetime.now(timezone.utc)
        refund.processed_at = now
        payment.status = PaymentStatus.REFUNDED
        order.status = OrderStatus.REFUNDED
        order.refunded_at = now
        restore_inventory_for_order(session, order)
    elif refund.status == RefundStatus.FAILED:
        payment.status = PaymentStatus.SUCCESS
        order.status = OrderStatus.CONFIRMED
        order.cancelled_at = None
    else:
        payment.status = PaymentStatus.REFUND_PENDING
        order.status = OrderStatus.REFUND_PENDING

    session.add(refund)
    session.add(payment)
    session.add(order)
    return True