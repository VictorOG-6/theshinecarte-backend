from fastapi import APIRouter, status, Depends, Query, HTTPException
from models import (
    ProductRead,
    ProductCreate,
    Product,
    ProductUpdate,
    ProductVariant,
    ProductVariantCreate,
    ProductSubVariant,
    User,
    ProductStatus,
    ProductCategorySummary,
    OrderItem,
    OrderBundleComponent,
    BundleItem,
)
from database import SessionDep
from services.access_token import get_current_admin
from typing import Optional
from sqlmodel import select, col
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from uuid import UUID

from services.slugs import generate_unique_product_slug

router = APIRouter(prefix="/product", tags=["Products"])

def validate_variant_sub_variants(variant: ProductVariantCreate) -> None:
    sub_variants = variant.sub_variants or []
    if not sub_variants:
        return

    sub_variant_total = sum(sub_variant.quantity for sub_variant in sub_variants)
    if sub_variant_total != variant.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Sub-variant quantities for '{variant.name}' must sum to "
                f"the variant quantity ({variant.quantity}), got {sub_variant_total}"
            ),
        )

def build_product_variant(variant: ProductVariantCreate) -> ProductVariant:
    validate_variant_sub_variants(variant)
    variant_data = variant.model_dump(exclude={"sub_variants"})
    product_variant = ProductVariant(**variant_data)
    sub_variants = variant.sub_variants or []
    if sub_variants:
        product_variant.sub_variants = [
            ProductSubVariant(**sub_variant.model_dump())
            for sub_variant in sub_variants
        ]
    return product_variant

@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate, session: SessionDep, current_admin: User = Depends(get_current_admin)):
    variants_data = product.variants or []
    product_data = product.model_dump(exclude={"variants"})
    product_data["slug"] = generate_unique_product_slug(session, product.name)
    if variants_data:
        product_data["quantity"] = sum(variant.quantity for variant in variants_data)

    new_product = Product(**product_data)
    new_product.variants = [
        build_product_variant(variant)
        for variant in variants_data
    ]
    session.add(new_product)

    session.commit()
    session.refresh(new_product)
    return new_product

@router.get("", response_model=list[ProductRead])
def get_products(
    session: SessionDep, 
    name: Optional[str] = Query(None, description="Filter products by name (partial match)"),
    category: Optional[str] = Query(None, description="Filter products by category (partial match)"),
    status: Optional[ProductStatus] = Query(None, description="Filter products by status"),
    page: int = Query(1, description="Page number", ge=1),
    page_size: int = Query(10, description="Number of items per page", ge=1, le=100),
    ):
    
    statement = select(Product).options(
        selectinload(Product.variants).selectinload(ProductVariant.sub_variants)
    )

    if (name):
        statement = statement.where(col(Product.name).contains(name))

    if (category):
        statement = statement.where(Product.category == category)

    if (status):
        statement = statement.where(Product.status == status)
    
    products = session.exec(statement).all()
    return products

@router.get("/categories/summary", response_model=list[ProductCategorySummary])
def get_product_categories_summary(
    session: SessionDep,
    status: Optional[ProductStatus] = Query(None, alias="status"),
):
    statement = (
        select(Product.category, func.count(Product.id))
        .group_by(Product.category)
        .order_by(Product.category)
    )

    if status:
        statement = statement.where(Product.status == status)

    categories = session.exec(statement).all()
    return [
        ProductCategorySummary(category=category, product_count=count)
        for category, count in categories
    ]

@router.get("/{product_id}", response_model=ProductRead)
def get_product_by_id(product_id: str, session: SessionDep):
    product = session.exec(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.variants).selectinload(ProductVariant.sub_variants)
        )
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product

@router.put("/{product_id}", response_model=ProductRead, status_code=status.HTTP_202_ACCEPTED)
def update_product(product_id: str, product_update: ProductUpdate, session: SessionDep, current_admin: User = Depends(get_current_admin)):
    updated_product = session.exec(select(Product).where(Product.id == product_id)).first()
    if not updated_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product_data = product_update.model_dump(exclude_unset=True, exclude={"variants"})
    if product_data.get("name") is not None:
        product_data["slug"] = generate_unique_product_slug(
            session, product_data["name"], UUID(product_id)
        )

    if product_update.variants is not None:
        product_data["quantity"] = sum(
            variant.quantity for variant in product_update.variants
        )
    elif product_update.variants is None and updated_product.variants:
        product_data["quantity"] = sum(
            variant.quantity for variant in updated_product.variants
        )

    updated_product.sqlmodel_update(product_data)

    if product_update.variants is not None:
        used_in_bundle = session.exec(
            select(BundleItem.id).where(BundleItem.product_id == product_id)
        ).first()
        used_in_order = session.exec(
            select(OrderItem.id).where(OrderItem.product_id == product_id)
        ).first() or session.exec(
            select(OrderBundleComponent.id).where(
                OrderBundleComponent.product_id == product_id
            )
        ).first()
        if used_in_bundle or used_in_order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Variants cannot be replaced while this product is used in "
                    "a bundle or order."
                ),
            )
        updated_product.variants.clear()
        updated_product.variants.extend(
            build_product_variant(variant)
            for variant in product_update.variants
        )

    session.commit()
    session.refresh(updated_product)
    return updated_product

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: str,
    session: SessionDep,
    current_admin: User = Depends(get_current_admin)
):
    product = session.exec(
        select(Product).where(Product.id == product_id)
    ).first()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    has_orders = session.exec(
        select(OrderItem.id).where(
            OrderItem.product_id == product_id
        )
    ).first() or session.exec(
        select(OrderBundleComponent.id).where(
            OrderBundleComponent.product_id == product_id
        )
    ).first()

    if has_orders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This product has existing orders and cannot be deleted. "
                "Archive it instead."
            )
        )

    if session.exec(
        select(BundleItem.id).where(BundleItem.product_id == product_id)
    ).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This product is used in a bundle and cannot be deleted. "
                "Update or archive the bundle first."
            ),
        )

    session.delete(product)
    session.commit()

    return None