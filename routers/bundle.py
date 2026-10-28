from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from database import SessionDep
from models import (
    Bundle,
    BundleCreate,
    BundleItem,
    BundleRead,
    BundleUpdate,
    OrderItem,
    ProductStatus,
    User,
)
from services.access_token import get_current_admin
from services.bundles import (
    BUNDLE_LOAD_OPTIONS,
    load_bundle,
    validate_bundle_items,
)
from services.slugs import generate_unique_bundle_slug

router = APIRouter(prefix="/bundle", tags=["Bundles"])


def validate_publishable_bundle(items: list[BundleItem]) -> None:
    if any(
        item.product is None or item.product.status != ProductStatus.PUBLISHED
        for item in items
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every product in a published bundle must be published",
        )


@router.post("", response_model=BundleRead, status_code=status.HTTP_201_CREATED)
def create_bundle(
    payload: BundleCreate,
    session: SessionDep,
    _: User = Depends(get_current_admin),
):
    items = validate_bundle_items(session, payload.items)
    if payload.status == ProductStatus.PUBLISHED:
        validate_publishable_bundle(items)
    data = payload.model_dump(exclude={"items"})
    data["slug"] = generate_unique_bundle_slug(session, payload.name)
    bundle = Bundle(**data)
    bundle.items = items
    session.add(bundle)
    session.commit()
    return load_bundle(session, bundle.id)


@router.get("", response_model=list[BundleRead])
def get_bundles(
    session: SessionDep,
    name: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status_filter: Optional[ProductStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    statement = select(Bundle).options(*BUNDLE_LOAD_OPTIONS)
    if name:
        statement = statement.where(col(Bundle.name).contains(name))
    if category:
        statement = statement.where(Bundle.category == category)
    if status_filter:
        statement = statement.where(Bundle.status == status_filter)
    statement = (
        statement.order_by(Bundle.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return session.exec(statement).all()


@router.get("/{bundle_id}", response_model=BundleRead)
def get_bundle(bundle_id: UUID, session: SessionDep):
    bundle = load_bundle(session, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return bundle


@router.put("/{bundle_id}", response_model=BundleRead)
def update_bundle(
    bundle_id: UUID,
    payload: BundleUpdate,
    session: SessionDep,
    _: User = Depends(get_current_admin),
):
    bundle = load_bundle(session, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    data = payload.model_dump(exclude_unset=True, exclude={"items"})
    if "name" in data:
        data["slug"] = generate_unique_bundle_slug(session, data["name"], bundle_id)
    bundle.sqlmodel_update(data)
    if payload.items is not None:
        bundle.items.clear()
        bundle.items.extend(validate_bundle_items(session, payload.items))
    if bundle.status == ProductStatus.PUBLISHED:
        validate_publishable_bundle(bundle.items)

    session.add(bundle)
    session.commit()
    return load_bundle(session, bundle_id)


@router.delete("/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bundle(
    bundle_id: UUID,
    session: SessionDep,
    _: User = Depends(get_current_admin),
):
    bundle = session.get(Bundle, bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")
    if session.exec(
        select(OrderItem.id).where(OrderItem.bundle_id == bundle_id)
    ).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This bundle has existing orders and cannot be deleted. Archive it instead.",
        )
    session.delete(bundle)
    session.commit()
    return None
