from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import col, select

from database import SessionDep
from models import (
    Bundle,
    BundleRead,
    CatalogItemRead,
    Product,
    ProductRead,
    ProductStatus,
    ProductVariant,
)
from services.bundles import BUNDLE_LOAD_OPTIONS, load_bundle_by_slug
from services.slugs import is_bundle_catalog_slug

router = APIRouter(prefix="/catalog", tags=["Catalog"])


def catalog_item_from_product(product: Product) -> CatalogItemRead:
    data = ProductRead.model_validate(product).model_dump()
    data["item_type"] = "product"
    data["items"] = []
    return CatalogItemRead.model_validate(data)


def catalog_item_from_bundle(bundle: Bundle) -> CatalogItemRead:
    data = BundleRead.model_validate(bundle).model_dump()
    data["item_type"] = "bundle"
    data["variants"] = []
    return CatalogItemRead.model_validate(data)


def bundle_unavailable_for_catalog(bundle: Bundle) -> bool:
    return any(
        item.product is None or item.product.status != ProductStatus.PUBLISHED
        for item in bundle.items
    )


@router.get("", response_model=list[CatalogItemRead])
def get_catalog(
    session: SessionDep,
    name: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status_filter: Optional[ProductStatus] = Query(
        ProductStatus.PUBLISHED, alias="status"
    ),
    item_type: Optional[Literal["product", "bundle"]] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    catalog: list[CatalogItemRead] = []

    if item_type in (None, "product"):
        product_statement = select(Product).options(
            selectinload(Product.variants).selectinload(
                ProductVariant.sub_variants
            )
        )
        if name:
            product_statement = product_statement.where(
                col(Product.name).contains(name)
            )
        if category:
            product_statement = product_statement.where(
                Product.category == category
            )
        if status_filter:
            product_statement = product_statement.where(
                Product.status == status_filter
            )
        for product in session.exec(product_statement).all():
            catalog.append(catalog_item_from_product(product))

    if item_type in (None, "bundle"):
        bundle_statement = select(Bundle).options(*BUNDLE_LOAD_OPTIONS)
        if name:
            bundle_statement = bundle_statement.where(
                col(Bundle.name).contains(name)
            )
        if category:
            bundle_statement = bundle_statement.where(
                Bundle.category == category
            )
        if status_filter:
            bundle_statement = bundle_statement.where(
                Bundle.status == status_filter
            )
        for bundle in session.exec(bundle_statement).all():
            if (
                status_filter == ProductStatus.PUBLISHED
                and bundle_unavailable_for_catalog(bundle)
            ):
                continue
            catalog.append(catalog_item_from_bundle(bundle))

    catalog.sort(key=lambda item: item.created_at, reverse=True)
    offset = (page - 1) * page_size
    return catalog[offset : offset + page_size]


@router.get("/{slug}", response_model=CatalogItemRead)
def get_catalog_item(slug: str, session: SessionDep):
    if is_bundle_catalog_slug(slug):
        bundle = load_bundle_by_slug(session, slug)
        if not bundle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Catalog item not found",
            )
        if bundle.status == ProductStatus.PUBLISHED and bundle_unavailable_for_catalog(
            bundle
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Catalog item not found",
            )
        return catalog_item_from_bundle(bundle)

    product = session.exec(
        select(Product)
        .where(Product.slug == slug)
        .options(
            selectinload(Product.variants).selectinload(
                ProductVariant.sub_variants
            )
        )
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog item not found",
        )
    return catalog_item_from_product(product)
