import logging
import os
from pathlib import Path
from uuid import UUID

import resend
from fastapi import BackgroundTasks
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import Order, OrderItem, User
from services.image_service import image_service


resend.api_key = os.environ["RESEND_API_KEY"]

RESEND_FROM = os.environ["RESEND_FROM"]
RESEND_VERIFICATION_TEMPLATE_ID = os.environ[
    "RESEND_VERIFICATION_TEMPLATE_ID"
]
RESEND_WELCOME_TEMPLATE_ID = os.environ[
    "RESEND_WELCOME_TEMPLATE_ID"
]
RESEND_ORDER_CONFIRMATION_TEMPLATE_ID = os.environ[
    "RESEND_ORDER_CONFIRMATION_TEMPLATE_ID"
]
FRONTEND_URL = os.environ.get("FRONTEND_URL", "").rstrip("/")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

logger = logging.getLogger(__name__)


def format_naira(amount: int) -> str:
    return f"₦{amount:,}"


def _serialize_order_items(order: Order, image_base_url: str) -> list[dict]:
    items = []
    for order_item in order.order_items:
        product = order_item.product
        bundle = order_item.bundle
        variant = order_item.product_variant
        sub_variant = order_item.product_sub_variant
        image_path = None
        if variant and variant.image_url:
            image_path = variant.image_url
        elif product and product.image_url:
            image_path = product.image_url
        elif bundle and bundle.image_url:
            image_path = bundle.image_url
        items.append(
            {
                "name": (
                    product.name
                    if product
                    else bundle.name if bundle else "Item"
                ),
                "price": format_naira(order_item.price_at_purchase),
                "quantity": order_item.quantity,
                "variant": variant.name if variant else "",
                "sub_variant": sub_variant.size if sub_variant else "",
                "image_url": image_service.get_image_url(image_path, image_base_url)
                or "",
            }
        )
    return items


def build_order_confirmation_variables(
    order: Order,
    user: User,
    image_base_url: str,
) -> dict[str, str]:
    order_items = _serialize_order_items(order, image_base_url)
    fields = jinja_env.get_template("order_item_fields.html").module
    order_total = format_naira(order.total_price)

    return {
        "FULL_NAME": user.name or user.email,
        "ORDER_URL": f"{FRONTEND_URL}/orders/{order.id}",
        "ORDER_ID": order.public_id,
        "ITEM_NAME": fields.names(order_items),
        "ITEM_IMAGE_URL": fields.image_urls(order_items),
        "ITEM_PRICE": fields.prices(order_items),
        "ITEM_QUANTITY": fields.quantities(order_items),
        "ITEM_VARIANT": fields.variants(order_items),
        "ITEM_SUBVARIANT": fields.sub_variants(order_items),
        "ORDER_TOTAL": order_total,
        "ITEMS_TOTAL": order_total,
    }


def schedule_order_confirmation_email(
    session: Session,
    *,
    order_id: UUID,
    image_base_url: str,
    background_tasks: BackgroundTasks,
) -> None:
    order = session.exec(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.order_items).selectinload(OrderItem.product),
            selectinload(Order.order_items).selectinload(OrderItem.bundle),
            selectinload(Order.order_items).selectinload(OrderItem.product_variant),
            selectinload(Order.order_items).selectinload(OrderItem.product_sub_variant),
            selectinload(Order.user),
        )
    ).first()
    if not order or not order.user:
        logger.warning(
            "Skipping order confirmation email; order %s or user was not found",
            order_id,
        )
        return

    background_tasks.add_task(
        send_order_confirmation_email,
        order.user.email,
        build_order_confirmation_variables(
            order=order,
            user=order.user,
            image_base_url=image_base_url,
        ),
    )


async def send_verification_email(
    email: str,
    otp: str,
    user_name: str,
):
    params: resend.Emails.SendParams = {
        "from": RESEND_FROM,
        "to": [email],
        "reply_to": "theshinecartel@gmail.com",
        "template": {
            "id": RESEND_VERIFICATION_TEMPLATE_ID,
            "variables": {
                "YOUR_NAME": user_name,
                "OTP": otp,
            },
        },
    }

    return await resend.Emails.send_async(params)


async def send_welcome_email(
    email: str,
    user_name: str,
):
    params: resend.Emails.SendParams = {
        "from": RESEND_FROM,
        "to": [email],
        "reply_to": "theshinecartel@gmail.com",
        "template": {
            "id": RESEND_WELCOME_TEMPLATE_ID,
            "variables": {
                "YOUR_NAME": user_name,
            },
        },
    }

    return await resend.Emails.send_async(params)


async def send_order_confirmation_email(
    email: str,
    variables: dict[str, str],
):
    params: resend.Emails.SendParams = {
        "from": RESEND_FROM,
        "to": [email],
        "reply_to": "theshinecartel@gmail.com",
        "subject": f"Order Confirmation (#{variables['ORDER_ID']})",
        "template": {
            "id": RESEND_ORDER_CONFIRMATION_TEMPLATE_ID,
            "variables": variables,
        },
    }

    try:
        return await resend.Emails.send_async(params)
    except Exception:
        logger.exception("Failed to send order confirmation email to %s", email)
        return None