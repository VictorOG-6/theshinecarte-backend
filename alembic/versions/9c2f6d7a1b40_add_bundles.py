"""add bundles

Revision ID: 9c2f6d7a1b40
Revises: 518766c67cfa
Create Date: 2026-10-14 12:36:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = "9c2f6d7a1b40"
down_revision: Union[str, Sequence[str], None] = "518766c67cfa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    product_status = postgresql.ENUM(
        "DRAFT",
        "PUBLISHED",
        "ARCHIVED",
        name="productstatus",
        create_type=False,
    )
    op.create_table(
        "bundle",
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", product_status, nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_bundle_price_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id"),
    )
    op.create_index(op.f("ix_bundle_slug"), "bundle", ["slug"], unique=True)

    op.create_table(
        "bundleitem",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("product_variant_id", sa.UUID(), nullable=True),
        sa.Column("product_sub_variant_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bundle_id", sa.UUID(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_bundleitem_quantity_positive"),
        sa.ForeignKeyConstraint(["bundle_id"], ["bundle.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.ForeignKeyConstraint(
            ["product_sub_variant_id"], ["productsubvariant.id"]
        ),
        sa.ForeignKeyConstraint(["product_variant_id"], ["productvariant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id"),
    )
    op.create_index(
        op.f("ix_bundleitem_bundle_id"), "bundleitem", ["bundle_id"], unique=False
    )
    op.create_index(
        op.f("ix_bundleitem_product_id"), "bundleitem", ["product_id"], unique=False
    )

    op.alter_column("cartitem", "product_id", nullable=True)
    op.add_column("cartitem", sa.Column("bundle_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_cartitem_bundle_id_bundle", "cartitem", "bundle", ["bundle_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_cartitem_exactly_one_catalog_item",
        "cartitem",
        "(product_id IS NOT NULL AND bundle_id IS NULL) OR "
        "(product_id IS NULL AND bundle_id IS NOT NULL)",
    )

    op.alter_column("orderitem", "product_id", nullable=True)
    op.add_column("orderitem", sa.Column("bundle_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_orderitem_bundle_id_bundle",
        "orderitem",
        "bundle",
        ["bundle_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_orderitem_exactly_one_catalog_item",
        "orderitem",
        "(product_id IS NOT NULL AND bundle_id IS NULL) OR "
        "(product_id IS NULL AND bundle_id IS NOT NULL)",
    )

    op.create_table(
        "orderbundlecomponent",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_item_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("product_variant_id", sa.UUID(), nullable=True),
        sa.Column("product_sub_variant_id", sa.UUID(), nullable=True),
        sa.Column("quantity_per_bundle", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity_per_bundle > 0",
            name="ck_orderbundlecomponent_quantity_positive",
        ),
        sa.ForeignKeyConstraint(["order_item_id"], ["orderitem.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
        sa.ForeignKeyConstraint(
            ["product_sub_variant_id"], ["productsubvariant.id"]
        ),
        sa.ForeignKeyConstraint(["product_variant_id"], ["productvariant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id"),
    )
    op.create_index(
        op.f("ix_orderbundlecomponent_order_item_id"),
        "orderbundlecomponent",
        ["order_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_orderbundlecomponent_order_item_id"),
        table_name="orderbundlecomponent",
    )
    op.drop_table("orderbundlecomponent")

    op.execute("DELETE FROM orderitem WHERE bundle_id IS NOT NULL")
    op.drop_constraint(
        "ck_orderitem_exactly_one_catalog_item", "orderitem", type_="check"
    )
    op.drop_constraint(
        "fk_orderitem_bundle_id_bundle", "orderitem", type_="foreignkey"
    )
    op.drop_column("orderitem", "bundle_id")
    op.alter_column("orderitem", "product_id", nullable=False)

    op.execute("DELETE FROM cartitem WHERE bundle_id IS NOT NULL")
    op.drop_constraint(
        "ck_cartitem_exactly_one_catalog_item", "cartitem", type_="check"
    )
    op.drop_constraint(
        "fk_cartitem_bundle_id_bundle", "cartitem", type_="foreignkey"
    )
    op.drop_column("cartitem", "bundle_id")
    op.alter_column("cartitem", "product_id", nullable=False)

    op.drop_index(op.f("ix_bundleitem_product_id"), table_name="bundleitem")
    op.drop_index(op.f("ix_bundleitem_bundle_id"), table_name="bundleitem")
    op.drop_table("bundleitem")
    op.drop_index(op.f("ix_bundle_slug"), table_name="bundle")
    op.drop_table("bundle")
