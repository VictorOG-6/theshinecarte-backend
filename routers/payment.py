import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlmodel import select

from database import SessionDep
from models import Payment, PaymentRead, PaymentStatus, User, WebhookEvent
from services.access_token import get_current_user
from services.email import schedule_order_confirmation_email
from services.payment_lifecycle import (
    apply_refund_event,
    apply_transaction_result,
    initialize_payment,
    verify_payment,
)
from services.paystack import paystack_service
from models import Order


router = APIRouter(prefix="/payment", tags=["Payments"])


def _get_owned_payment(
    session: SessionDep,
    *,
    payment_id: UUID,
    user_id: UUID,
) -> Payment:
    payment = session.exec(
        select(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.id == payment_id, Order.user_id == user_id)
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


def _schedule_confirmation_if_newly_paid(
    session: SessionDep,
    *,
    payment: Payment,
    already_success: bool,
    request: Request,
    background_tasks: BackgroundTasks,
) -> None:
    if already_success or payment.status != PaymentStatus.SUCCESS:
        return
    schedule_order_confirmation_email(
        session,
        order_id=payment.order_id,
        image_base_url=str(request.base_url).rstrip("/"),
        background_tasks=background_tasks,
    )


@router.post("/order/{order_id}/initialize", response_model=PaymentRead)
def initialize_order_payment(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    order = session.exec(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = initialize_payment(session, order=order, user=current_user)
    session.commit()
    session.refresh(payment)
    return payment


@router.post("/{payment_id}/verify", response_model=PaymentRead)
def verify_order_payment(
    payment_id: UUID,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    payment = _get_owned_payment(
        session,
        payment_id=payment_id,
        user_id=current_user.id,
    )
    already_success = payment.status == PaymentStatus.SUCCESS
    verify_payment(session, payment)
    session.commit()
    session.refresh(payment)
    _schedule_confirmation_if_newly_paid(
        session,
        payment=payment,
        already_success=already_success,
        request=request,
        background_tasks=background_tasks,
    )
    return payment


@router.post("/reference/{reference}/verify", response_model=PaymentRead)
def verify_order_payment_by_reference(
    reference: str,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    payment = session.exec(
        select(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Payment.reference == reference,
            Order.user_id == current_user.id,
        )
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    already_success = payment.status == PaymentStatus.SUCCESS
    verify_payment(session, payment)
    session.commit()
    session.refresh(payment)
    _schedule_confirmation_if_newly_paid(
        session,
        payment=payment,
        already_success=already_success,
        request=request,
        background_tasks=background_tasks,
    )
    return payment


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(
    request: Request,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    x_paystack_signature: str | None = Header(default=None),
):
    raw_body = await request.body()
    if not paystack_service.verify_webhook_signature(
        raw_body,
        x_paystack_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Paystack signature",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    fingerprint = hashlib.sha256(raw_body).hexdigest()
    if session.exec(
        select(WebhookEvent).where(WebhookEvent.fingerprint == fingerprint)
    ).first():
        return {"status": "ok"}

    event_type = payload.get("event", "")
    data = payload.get("data") or {}
    newly_paid_payment: Payment | None = None
    if event_type in {"charge.success", "charge.failed"}:
        reference = data.get("reference")
        payment = session.exec(
            select(Payment).where(Payment.reference == reference)
        ).first()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payment is not ready for webhook processing",
            )
        already_success = payment.status == PaymentStatus.SUCCESS
        apply_transaction_result(session, payment=payment, data=data)
        if not already_success and payment.status == PaymentStatus.SUCCESS:
            newly_paid_payment = payment
    elif event_type in {
        "refund.pending",
        "refund.processing",
        "refund.needs-attention",
        "refund.failed",
        "refund.processed",
    }:
        processed = apply_refund_event(
            session,
            event_type=event_type,
            data=data,
        )
        if not processed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Refund is not ready for webhook processing",
            )

    session.add(
        WebhookEvent(
            fingerprint=fingerprint,
            event_type=event_type or "unknown",
        )
    )
    session.commit()
    if newly_paid_payment:
        _schedule_confirmation_if_newly_paid(
            session,
            payment=newly_paid_payment,
            already_success=False,
            request=request,
            background_tasks=background_tasks,
        )
    return {"status": "ok"}