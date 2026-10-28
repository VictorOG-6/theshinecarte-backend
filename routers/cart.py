from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from database import SessionDep
from models import (
    Bundle,
    BundleItem,
    Cart,
    CartItem,
    CartItemCreate,
    CartItemRead,
    CartItemUpdate,
    CartRead,
    Product,
    ProductStatus,
    ProductVariant,
    User,
)
from services.access_token import get_current_user
from services.bundles import load_bundle
from services.inventory import validate_inventory_selection

router = APIRouter(prefix="/cart", tags=["Cart"])


def _cart_options():
    return (
        selectinload(Cart.user),
        selectinload(Cart.items)
        .selectinload(CartItem.product)
        .selectinload(Product.variants)
        .selectinload(ProductVariant.sub_variants),
        selectinload(Cart.items).selectinload(CartItem.product_variant),
        selectinload(Cart.items).selectinload(CartItem.product_sub_variant),
        selectinload(Cart.items)
        .selectinload(CartItem.bundle)
        .selectinload(Bundle.items)
        .selectinload(BundleItem.product)
        .selectinload(Product.variants)
        .selectinload(ProductVariant.sub_variants),
        selectinload(Cart.items)
        .selectinload(CartItem.bundle)
        .selectinload(Bundle.items)
        .selectinload(BundleItem.product_variant),
        selectinload(Cart.items)
        .selectinload(CartItem.bundle)
        .selectinload(Bundle.items)
        .selectinload(BundleItem.product_sub_variant),
    )


def _get_cart(session: SessionDep, user_id: UUID, create: bool = False) -> Cart | None:
    cart = session.exec(
        select(Cart)
        .where(Cart.user_id == user_id)
        .options(*_cart_options())
    ).first()
    if cart or not create:
        return cart
    cart = Cart(user_id=user_id, total_price=0, total_products=0)
    session.add(cart)
    session.commit()
    return session.exec(
        select(Cart).where(Cart.id == cart.id).options(*_cart_options())
    ).one()


def _recalculate_cart(cart: Cart) -> None:
    cart.total_price = sum(item.total_price for item in cart.items)
    cart.total_products = sum(item.quantity for item in cart.items)


def _validate_bundle_for_cart(bundle: Bundle, quantity: int) -> None:
    if bundle.status != ProductStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This bundle is not available for purchase",
        )
    if any(
        item.product is None or item.product.status != ProductStatus.PUBLISHED
        for item in bundle.items
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more bundle products are unavailable",
        )
    if quantity > bundle.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only {bundle.quantity} units of {bundle.name} are available",
        )


@router.get("", response_model=CartRead)
def get_cart(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    return _get_cart(session, current_user.id, create=True)


@router.post("/items", response_model=CartItemRead, status_code=status.HTTP_201_CREATED)
def add_cart_item(
    payload: CartItemCreate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    if (payload.product_id is None) == (payload.bundle_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of product_id or bundle_id",
        )
    cart = _get_cart(session, current_user.id, create=True)

    if payload.bundle_id is not None:
        if payload.product_variant_id or payload.product_sub_variant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Variants cannot be selected for a bundle",
            )
        bundle = load_bundle(session, payload.bundle_id)
        if not bundle:
            raise HTTPException(status_code=404, detail="Bundle not found")
        existing = next(
            (item for item in cart.items if item.bundle_id == bundle.id),
            None,
        )
        requested_quantity = payload.quantity + (existing.quantity if existing else 0)
        _validate_bundle_for_cart(bundle, requested_quantity)
        if existing:
            existing.quantity = requested_quantity
            existing.total_price = requested_quantity * bundle.price
            item = existing
        else:
            item = CartItem(
                cart_id=cart.id,
                bundle_id=bundle.id,
                quantity=payload.quantity,
                total_price=payload.quantity * bundle.price,
            )
            cart.items.append(item)
    else:
        product = session.get(Product, payload.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        if product.status != ProductStatus.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This product is not available for purchase",
            )
        existing = next(
            (
                candidate
                for candidate in cart.items
                if candidate.product_id == product.id
                and candidate.product_variant_id == payload.product_variant_id
                and candidate.product_sub_variant_id == payload.product_sub_variant_id
            ),
            None,
        )
        requested_quantity = payload.quantity + (existing.quantity if existing else 0)
        validate_inventory_selection(
            session,
            product,
            payload.product_variant_id,
            payload.product_sub_variant_id,
            requested_quantity,
        )
        if existing:
            existing.quantity = requested_quantity
            existing.total_price = requested_quantity * product.price
            item = existing
        else:
            item = CartItem(
                cart_id=cart.id,
                product_id=product.id,
                product_variant_id=payload.product_variant_id,
                product_sub_variant_id=payload.product_sub_variant_id,
                quantity=payload.quantity,
                total_price=payload.quantity * product.price,
            )
            cart.items.append(item)

    session.add(item)
    _recalculate_cart(cart)
    session.add(cart)
    session.commit()
    refreshed = _get_cart(session, current_user.id)
    return next(candidate for candidate in refreshed.items if candidate.id == item.id)


@router.patch("/items/{item_id}", response_model=CartItemRead)
def update_cart_item(
    item_id: UUID,
    payload: CartItemUpdate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    cart = _get_cart(session, current_user.id)
    item = next(
        (candidate for candidate in (cart.items if cart else []) if candidate.id == item_id),
        None,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    quantity = payload.quantity if payload.quantity is not None else item.quantity
    if item.bundle_id:
        bundle = load_bundle(session, item.bundle_id)
        if not bundle:
            raise HTTPException(status_code=409, detail="Bundle is no longer available")
        _validate_bundle_for_cart(bundle, quantity)
        item.total_price = quantity * bundle.price
    else:
        validate_inventory_selection(
            session,
            item.product,
            item.product_variant_id,
            item.product_sub_variant_id,
            quantity,
        )
        item.total_price = quantity * item.product.price
    item.quantity = quantity
    _recalculate_cart(cart)
    session.add(item)
    session.add(cart)
    session.commit()
    refreshed = _get_cart(session, current_user.id)
    return next(candidate for candidate in refreshed.items if candidate.id == item.id)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_cart_item(
    item_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    cart = _get_cart(session, current_user.id)
    item = next(
        (candidate for candidate in (cart.items if cart else []) if candidate.id == item_id),
        None,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    cart.items.remove(item)
    session.delete(item)
    _recalculate_cart(cart)
    session.add(cart)
    session.commit()
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    cart = _get_cart(session, current_user.id)
    if cart:
        for item in list(cart.items):
            session.delete(item)
        cart.items.clear()
        _recalculate_cart(cart)
        session.add(cart)
        session.commit()
    return None
