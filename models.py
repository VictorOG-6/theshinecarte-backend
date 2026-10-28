from sqlmodel import Field, SQLModel, Relationship
from typing import Literal, Optional
from datetime import datetime, timezone
from pydantic import EmailStr
from uuid import UUID, uuid4
from sqlalchemy import Column, DateTime
from enum import Enum
from pwdlib import PasswordHash
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import func

password_hash = PasswordHash.recommended()

class GoogleUser(SQLModel):
    sub: str
    email: EmailStr
    email_verified: bool = False
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = None
    locale: Optional[str] = None

class UserBase(SQLModel):
    name: Optional[str] = Field(default=None)
    email: EmailStr = Field(unique=True, index=True)

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    STAFF = "staff"
    
class User(UserBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    hashed_password: Optional[str] = None
    email_verified: bool = Field(default=False)
    google_sub: Optional[str] = Field(default=None, unique=True, index=True)
    profile_image_url: Optional[str] = Field(default=None, max_length=500)
    cart: "Cart" = Relationship(back_populates="user")
    orders: list["Order"] = Relationship(back_populates="user")
    reviews: list["Review"] = Relationship(back_populates="user")
    email_verifications: list["EmailVerification"] = Relationship(back_populates="user")
    total_orders: int = Field(default=0)
    total_spent: int = Field(default=0)
    total_reviews: int = Field(default=0)
    role: UserRole = Field(default=UserRole.USER)

class UserRead(UserBase):
    id: UUID
    profile_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    total_orders: int
    total_spent: int
    total_reviews: int
    role: UserRole

class UserSummary(SQLModel):
    id: UUID
    name: Optional[str] = None
    email: EmailStr

class UserWithRelationsRead(UserRead):
    orders: list["OrderRead"] = Field(default_factory=list)
    reviews: list["ReviewRead"] = Field(default_factory=list)
    cart: Optional["CartRead"] = None

class UserCreate(UserBase):
    profile_image_url: Optional[str] = Field(default=None)
    password: str

class UserUpdate(UserBase):
    name: Optional[str] = Field(default=None, min_length=2)
    email: Optional[EmailStr] = None
    profile_image_url: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=100)

class Login(SQLModel):
    username: str
    password: str

class Token(SQLModel):
    access_token: str
    token_type: str
    refresh_token: str

class TokenData(SQLModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    jti: Optional[str] = None

class RefreshTokenRequest(SQLModel):
    refresh_token: str

class RefreshToken(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    token: str = Field(unique=True, index=True)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    revoked: bool = Field(default=False)

class AuthModel(SQLModel):
    user: UserRead
    access_token: str
    refresh_token: str
    token_type: str

class UserRegisterResponse(SQLModel):
    message: str
    user: UserRead

class ProductStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class ProductSubVariantBase(SQLModel):
    size: str
    quantity: int = Field(ge=0)

class ProductSubVariant(ProductSubVariantBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    product_variant_id: UUID = Field(foreign_key="productvariant.id", nullable=False)
    product_variant: Optional["ProductVariant"] = Relationship(back_populates="sub_variants")
    order_items: list["OrderItem"] = Relationship(back_populates="product_sub_variant")
    cart_items: list["CartItem"] = Relationship(back_populates="product_sub_variant")

class ProductSubVariantCreate(ProductSubVariantBase):
    pass

class ProductSubVariantRead(ProductSubVariantBase):
    id: UUID
    product_variant_id: UUID

class ProductVariantBase(SQLModel):
    name: str
    image_url: str
    color: str
    quantity: int = Field(ge=0)

class ProductVariant(ProductVariantBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    product_id: UUID = Field(foreign_key="product.id", nullable=False)
    product: Optional["Product"] = Relationship(back_populates="variants")
    sub_variants: list["ProductSubVariant"] = Relationship(
        back_populates="product_variant",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    order_items: list["OrderItem"] = Relationship(back_populates="product_variant")
    cart_items: list["CartItem"] = Relationship(back_populates="product_variant")

class ProductVariantCreate(ProductVariantBase):
    sub_variants: Optional[list[ProductSubVariantCreate]] = None

class ProductVariantRead(ProductVariantBase):
    id: UUID
    product_id: UUID
    sub_variants: list["ProductSubVariantRead"] = Field(default_factory=list)

class ProductBase(SQLModel):
    name: str
    image_url: str
    price: int
    category: str
    description: str
    quantity: int = Field(default=0, ge=0)

class Product(ProductBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    slug: str = Field(index=True, unique=True)
    created_at: datetime = Field(
        default_factory=datetime.now,
         sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    reviews: list["Review"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    total_reviews: int = Field(default=0)
    average_rating: int = Field(default=0)
    variants: list["ProductVariant"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    order_items: list["OrderItem"] = Relationship(back_populates="product")
    cart_items: list["CartItem"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    bundle_items: list["BundleItem"] = Relationship(back_populates="product")
    order_bundle_components: list["OrderBundleComponent"] = Relationship(
        back_populates="product"
    )
    status: ProductStatus = Field(default=ProductStatus.DRAFT)

class ProductCreate(ProductBase):
    variants: Optional[list[ProductVariantCreate]] = None
    status: ProductStatus = ProductStatus.DRAFT

class ProductRead(ProductBase):
    id: UUID
    slug: str
    created_at: datetime
    updated_at: datetime
    total_reviews: int
    average_rating: int
    variants: list["ProductVariantRead"]
    status: ProductStatus
    item_type: Literal["product"] = "product"

class ProductUpdate(SQLModel):
    name: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=0)
    variants: Optional[list[ProductVariantCreate]] = None
    status: Optional[ProductStatus] = None


class BundleItemBase(SQLModel):
    product_id: UUID
    product_variant_id: Optional[UUID] = None
    product_sub_variant_id: Optional[UUID] = None
    quantity: int = Field(ge=1)


class BundleItem(BundleItemBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    bundle_id: UUID = Field(foreign_key="bundle.id", nullable=False, index=True)
    bundle: Optional["Bundle"] = Relationship(back_populates="items")
    product_id: UUID = Field(foreign_key="product.id", nullable=False, index=True)
    product: Optional["Product"] = Relationship(back_populates="bundle_items")
    product_variant_id: Optional[UUID] = Field(
        default=None, foreign_key="productvariant.id"
    )
    product_variant: Optional["ProductVariant"] = Relationship()
    product_sub_variant_id: Optional[UUID] = Field(
        default=None, foreign_key="productsubvariant.id"
    )
    product_sub_variant: Optional["ProductSubVariant"] = Relationship()


class BundleItemCreate(BundleItemBase):
    pass


class BundleItemRead(BundleItemBase):
    id: UUID
    bundle_id: UUID
    product: ProductRead
    product_variant: Optional[ProductVariantRead] = None
    product_sub_variant: Optional[ProductSubVariantRead] = None


class BundleBase(SQLModel):
    name: str
    image_url: str
    price: int = Field(ge=0)
    category: str
    description: str


class Bundle(BundleBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    slug: str = Field(index=True, unique=True)
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    status: ProductStatus = Field(default=ProductStatus.DRAFT)
    items: list["BundleItem"] = Relationship(
        back_populates="bundle",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    cart_items: list["CartItem"] = Relationship(
        back_populates="bundle",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    order_items: list["OrderItem"] = Relationship(back_populates="bundle")

    @property
    def quantity(self) -> int:
        capacities: list[int] = []
        for item in self.items:
            inventory = (
                item.product_sub_variant
                or item.product_variant
                or item.product
            )
            if inventory is None:
                return 0
            capacities.append(inventory.quantity // item.quantity)
        return min(capacities, default=0)


class BundleCreate(BundleBase):
    items: list[BundleItemCreate] = Field(min_length=2)
    status: ProductStatus = ProductStatus.DRAFT


class BundleRead(BundleBase):
    id: UUID
    slug: str
    created_at: datetime
    updated_at: datetime
    status: ProductStatus
    quantity: int
    items: list[BundleItemRead]
    item_type: Literal["bundle"] = "bundle"

class BundleUpdate(SQLModel):
    name: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[int] = Field(default=None, ge=0)
    category: Optional[str] = None
    description: Optional[str] = None
    items: Optional[list[BundleItemCreate]] = Field(default=None, min_length=2)
    status: Optional[ProductStatus] = None


class CatalogItemRead(SQLModel):
    id: UUID
    slug: str
    name: str
    image_url: str
    price: int
    category: str
    description: str
    quantity: int
    created_at: datetime
    updated_at: datetime
    status: ProductStatus
    item_type: Literal["product", "bundle"]
    variants: list[ProductVariantRead] = Field(default_factory=list)
    items: list[BundleItemRead] = Field(default_factory=list)

class DashboardSummary(SQLModel):
    total_revenue: int
    revenue_change_percent: Optional[float] = None
    total_orders: int
    orders_change_percent: Optional[float] = None
    total_customers: int
    customers_change_percent: Optional[float] = None
    total_products: int

class TopSellingProduct(SQLModel):
    product: ProductRead
    quantity_sold: int
    revenue: int

class ProductCategorySummary(SQLModel):
    category: str
    product_count: int

class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    COMPLETED = "completed"

class PaymentStatus(str, Enum):
    INITIALIZED = "initialized"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"

class RefundStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    NEEDS_ATTENTION = "needs_attention"
    PROCESSED = "processed"
    FAILED = "failed"

class Order(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    public_id: str = Field(index=True, unique=True)
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory= lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    order_items: list["OrderItem"] = Relationship(back_populates="order")
    total_price: int
    total_products: int
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    user: Optional["User"] = Relationship(back_populates="orders")
    payments: list["Payment"] = Relationship(back_populates="order")
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    confirmed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    cancelled_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    refunded_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    inventory_committed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    inventory_restored_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

class OrderRead(SQLModel):
    id: UUID
    public_id: str
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    user: "UserSummary"
    order_items: list["OrderItemRead"]
    total_price: int
    total_products: int
    status: OrderStatus
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    inventory_committed_at: Optional[datetime] = None
    inventory_restored_at: Optional[datetime] = None

class OrderStatusUpdate(SQLModel):
    status: OrderStatus

class Payment(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    order_id: UUID = Field(foreign_key="order.id", nullable=False, index=True)
    order: Optional["Order"] = Relationship(back_populates="payments")
    reference: str = Field(unique=True, index=True)
    provider_transaction_id: Optional[str] = Field(default=None, index=True)
    amount_kobo: int
    currency: str = Field(default="NGN", max_length=3)
    status: PaymentStatus = Field(default=PaymentStatus.INITIALIZED)
    access_code: Optional[str] = None
    authorization_url: Optional[str] = None
    paid_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    refunds: list["Refund"] = Relationship(back_populates="payment")

class PaymentRead(SQLModel):
    id: UUID
    order_id: UUID
    reference: str
    amount_kobo: int
    currency: str
    status: PaymentStatus
    authorization_url: Optional[str] = None
    paid_at: Optional[datetime] = None

class CheckoutRead(SQLModel):
    order: OrderRead
    payment: PaymentRead

class Refund(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    payment_id: UUID = Field(foreign_key="payment.id", nullable=False, unique=True)
    payment: Optional["Payment"] = Relationship(back_populates="refunds")
    provider_refund_id: Optional[str] = Field(default=None, index=True)
    amount_kobo: int
    status: RefundStatus = Field(default=RefundStatus.PENDING)
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

class WebhookEvent(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    fingerprint: str = Field(unique=True, index=True)
    event_type: str = Field(index=True)
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

class OrderItem(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    order_id: UUID = Field(foreign_key="order.id", nullable=False)
    order: Optional["Order"] = Relationship(back_populates="order_items")
    product_id: Optional[UUID] = Field(
        default=None, foreign_key="product.id", nullable=True
    )
    product: Optional["Product"] = Relationship(back_populates="order_items")
    bundle_id: Optional[UUID] = Field(
        default=None, foreign_key="bundle.id", nullable=True
    )
    bundle: Optional["Bundle"] = Relationship(back_populates="order_items")
    product_variant_id: Optional[UUID] = Field(
        default=None,
        foreign_key="productvariant.id",
    )
    product_variant: Optional["ProductVariant"] = Relationship(
        back_populates="order_items"
    )
    product_sub_variant_id: Optional[UUID] = Field(
        default=None,
        foreign_key="productsubvariant.id",
    )
    product_sub_variant: Optional["ProductSubVariant"] = Relationship(
        back_populates="order_items"
    )
    quantity: int = Field(default=1, ge=1)
    price_at_purchase: int
    bundle_components: list["OrderBundleComponent"] = Relationship(
        back_populates="order_item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class OrderBundleComponent(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    order_item_id: UUID = Field(
        foreign_key="orderitem.id", nullable=False, index=True
    )
    order_item: Optional["OrderItem"] = Relationship(
        back_populates="bundle_components"
    )
    product_id: UUID = Field(foreign_key="product.id", nullable=False)
    product: Optional["Product"] = Relationship(
        back_populates="order_bundle_components"
    )
    product_variant_id: Optional[UUID] = Field(
        default=None, foreign_key="productvariant.id"
    )
    product_variant: Optional["ProductVariant"] = Relationship()
    product_sub_variant_id: Optional[UUID] = Field(
        default=None, foreign_key="productsubvariant.id"
    )
    product_sub_variant: Optional["ProductSubVariant"] = Relationship()
    quantity_per_bundle: int = Field(ge=1)


class OrderBundleComponentRead(SQLModel):
    id: UUID
    product_id: UUID
    product: ProductRead
    product_variant_id: Optional[UUID] = None
    product_variant: Optional[ProductVariantRead] = None
    product_sub_variant_id: Optional[UUID] = None
    product_sub_variant: Optional[ProductSubVariantRead] = None
    quantity_per_bundle: int

class OrderItemRead(SQLModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    order_id: UUID
    product_id: Optional[UUID] = None
    product: Optional["ProductRead"] = None
    bundle_id: Optional[UUID] = None
    bundle: Optional["BundleRead"] = None
    product_variant_id: Optional[UUID] = None
    product_variant: Optional["ProductVariantRead"] = None
    product_sub_variant_id: Optional[UUID] = None
    product_sub_variant: Optional["ProductSubVariantRead"] = None
    quantity: int
    price_at_purchase: int
    bundle_components: list["OrderBundleComponentRead"] = Field(default_factory=list)
    
class Cart(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    user: Optional["User"] = Relationship(back_populates="cart")
    items: list["CartItem"] = Relationship(back_populates="cart")
    total_price: int
    total_products: int

class CartRead(SQLModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    user: "UserRead"
    items: list["CartItemRead"]
    total_price: int
    total_products: int

class CartItemBase(SQLModel):
    quantity: int = Field(default=1, ge=1)

class CartItem(CartItemBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    cart_id: UUID = Field(foreign_key="cart.id", nullable=False) 
    cart: Optional["Cart"] = Relationship(back_populates="items")
    product_id: Optional[UUID] = Field(
        default=None, foreign_key="product.id", nullable=True
    )
    product: Optional["Product"] = Relationship(back_populates="cart_items")
    bundle_id: Optional[UUID] = Field(
        default=None, foreign_key="bundle.id", nullable=True
    )
    bundle: Optional["Bundle"] = Relationship(back_populates="cart_items")
    product_variant_id: Optional[UUID] = Field(
        default=None,
        foreign_key="productvariant.id",
    )
    product_variant: Optional["ProductVariant"] = Relationship(
        back_populates="cart_items"
    )
    product_sub_variant_id: Optional[UUID] = Field(
        default=None,
        foreign_key="productsubvariant.id",
    )
    product_sub_variant: Optional["ProductSubVariant"] = Relationship(
        back_populates="cart_items"
    )
    total_price: int
    
class CartItemCreate(CartItemBase):
    product_id: Optional[UUID] = None
    bundle_id: Optional[UUID] = None
    product_variant_id: Optional[UUID] = None
    product_sub_variant_id: Optional[UUID] = None

class CartItemUpdate(SQLModel):
    quantity: Optional[int] = Field(default=None, ge=1)

class CartItemRead(CartItemBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    cart_id: UUID
    product_id: Optional[UUID] = None
    product: Optional["ProductRead"] = None
    bundle_id: Optional[UUID] = None
    bundle: Optional["BundleRead"] = None
    product_variant_id: Optional[UUID] = None
    product_variant: Optional["ProductVariantRead"] = None
    product_sub_variant_id: Optional[UUID] = None
    product_sub_variant: Optional["ProductSubVariantRead"] = None
    total_price: int

class ReviewBase(SQLModel):
    rating: int
    comment: str

class Review(ReviewBase, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )
    user_id: UUID = Field(foreign_key="user.id", nullable=False)
    user: Optional["User"] = Relationship(back_populates="reviews")
    product_id: UUID = Field(foreign_key="product.id", nullable=False)
    product: Optional["Product"] = Relationship(back_populates="reviews")

class ReviewCreate(ReviewBase):
    product_id: UUID

class ReviewRead(ReviewBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    product_id: UUID
    product: "ProductRead"
    user: "UserRead"

class ReviewUpdate(SQLModel):
    rating: Optional[int] = None
    comment: Optional[str] = None

class EmailVerification(SQLModel, table=True):
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
    )
    user_id: UUID = Field(foreign_key="user.id", nullable=False, index=True)
    user: Optional["User"] = Relationship(back_populates="email_verifications")
    otp_hash: str = Field(nullable=False)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    attempts: int = Field(default=0, nullable=False)
    used: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

class VerifyOTPRequest(SQLModel):
    email: EmailStr
    otp: str

class ResendOTPRequest(SQLModel):
    email: EmailStr