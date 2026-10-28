import re
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from models import Bundle, Product

BUNDLE_SLUG_SUFFIX = "_bundle"


def slugify_product_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "product"


def slugify_bundle_base_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "bundle"


def format_bundle_slug(base: str) -> str:
    if base.endswith(BUNDLE_SLUG_SUFFIX):
        return base
    return f"{base}{BUNDLE_SLUG_SUFFIX}"


def is_bundle_catalog_slug(slug: str) -> bool:
    return slug.endswith(BUNDLE_SLUG_SUFFIX)


def generate_unique_product_slug(
    session: Session,
    name: str,
    product_id: Optional[UUID] = None,
) -> str:
    base_slug = slugify_product_name(name)
    slug = base_slug
    suffix = 1

    while True:
        statement = select(Product).where(Product.slug == slug)
        if product_id is not None:
            statement = statement.where(Product.id != product_id)

        if not session.exec(statement).first():
            return slug

        suffix += 1
        slug = f"{base_slug}-{suffix}"


def generate_unique_bundle_slug(
    session: Session,
    name: str,
    bundle_id: Optional[UUID] = None,
) -> str:
    base = slugify_bundle_base_name(name)
    slug = format_bundle_slug(base)
    suffix = 1

    while True:
        statement = select(Bundle).where(Bundle.slug == slug)
        if bundle_id is not None:
            statement = statement.where(Bundle.id != bundle_id)

        if not session.exec(statement).first():
            return slug

        suffix += 1
        slug = format_bundle_slug(f"{base}-{suffix}")
