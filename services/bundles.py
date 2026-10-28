from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import (
    Bundle,
    BundleItem,
    BundleItemCreate,
    Product,
    ProductSubVariant,
    ProductVariant,
)


BUNDLE_LOAD_OPTIONS = (
    selectinload(Bundle.items)
    .selectinload(BundleItem.product)
    .selectinload(Product.variants)
    .selectinload(ProductVariant.sub_variants),
    selectinload(Bundle.items).selectinload(BundleItem.product_variant),
    selectinload(Bundle.items).selectinload(BundleItem.product_sub_variant),
)


def load_bundle(session: Session, bundle_id: UUID) -> Bundle | None:
    return session.exec(
        select(Bundle)
        .where(Bundle.id == bundle_id)
        .options(*BUNDLE_LOAD_OPTIONS)
    ).first()


def load_bundle_by_slug(session: Session, slug: str) -> Bundle | None:
    return session.exec(
        select(Bundle)
        .where(Bundle.slug == slug)
        .options(*BUNDLE_LOAD_OPTIONS)
    ).first()


def validate_bundle_items(
    session: Session,
    items: list[BundleItemCreate],
) -> list[BundleItem]:
    uses_variant_selection = any(
        item.product_variant_id is not None or item.product_sub_variant_id is not None
        for item in items
    )
    if not uses_variant_selection and len({item.product_id for item in items}) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A bundle must contain at least two different products",
        )

    selections = {
        (item.product_id, item.product_variant_id, item.product_sub_variant_id)
        for item in items
    }
    if len(selections) != len(items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate bundle component selections are not allowed",
        )

    result: list[BundleItem] = []
    for item in items:
        product = session.get(Product, item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {item.product_id} was not found",
            )

        variants = session.exec(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
        ).all()
        variant = None
        if variants:
            if item.product_variant_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"A variant is required for product {product.name}",
                )
            variant = next(
                (
                    candidate
                    for candidate in variants
                    if candidate.id == item.product_variant_id
                ),
                None,
            )
            if not variant:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"The selected variant does not belong to {product.name}",
                )
        elif item.product_variant_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {product.name} does not have variants",
            )

        if variant:
            sub_variants = session.exec(
                select(ProductSubVariant).where(
                    ProductSubVariant.product_variant_id == variant.id
                )
            ).all()
            if sub_variants:
                if item.product_sub_variant_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"A size is required for variant {variant.name}",
                    )
                if not any(
                    candidate.id == item.product_sub_variant_id
                    for candidate in sub_variants
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"The selected size does not belong to {variant.name}",
                    )
            elif item.product_sub_variant_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Variant {variant.name} does not have sizes",
                )
        elif item.product_sub_variant_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A variant must be selected before choosing a size",
            )

        result.append(
            BundleItem(
                **item.model_dump(),
                product=product,
                product_variant=variant,
                product_sub_variant=(
                    next(
                        (
                            candidate
                            for candidate in sub_variants
                            if candidate.id == item.product_sub_variant_id
                        ),
                        None,
                    )
                    if variant
                    else None
                ),
            )
        )

    return result
