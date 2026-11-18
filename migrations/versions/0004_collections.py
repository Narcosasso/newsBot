"""collezioni, storico prezzi e valore delle collezioni

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_user_id", "collections", ["user_id"])
    op.create_table(
        "collection_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.String(length=64), nullable=False),
        sa.Column("catalog_lang", sa.String(length=8), nullable=False),
        sa.Column("variant", sa.String(length=16), nullable=False),
        sa.Column("variant_label", sa.String(length=64), nullable=True),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("set_id", sa.String(length=64), nullable=True),
        sa.Column("set_name", sa.String(length=200), nullable=True),
        sa.Column("number_label", sa.String(length=32), nullable=True),
        sa.Column("image", sa.String(length=300), nullable=True),
        sa.Column("rarity", sa.String(length=64), nullable=True),
        sa.Column("id_product", sa.Integer(), nullable=True),
        sa.Column("shared_product", sa.Boolean(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "catalog_lang", "card_id", "variant", "lang",
                            name="uq_item_card_variant_lang"),
    )
    op.create_index("ix_collection_items_collection_id", "collection_items", ["collection_id"])
    op.create_index("ix_collection_items_card_id", "collection_items", ["card_id"])
    op.create_index("ix_collection_items_id_product", "collection_items", ["id_product"])
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("id_product", sa.Integer(), nullable=False),
        sa.Column("fields", sa.String(length=8), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("trend", sa.Float(), nullable=True),
        sa.Column("avg", sa.Float(), nullable=True),
        sa.Column("avg1", sa.Float(), nullable=True),
        sa.Column("avg7", sa.Float(), nullable=True),
        sa.Column("avg30", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id_product", "fields", "day", name="uq_history_product_fields_day"),
    )
    op.create_index("ix_price_history_id_product", "price_history", ["id_product"])
    op.create_table(
        "collection_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("cards", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "day", name="uq_collection_value_day"),
    )
    op.create_index("ix_collection_values_collection_id", "collection_values", ["collection_id"])


def downgrade() -> None:
    op.drop_index("ix_collection_values_collection_id", table_name="collection_values")
    op.drop_table("collection_values")
    op.drop_index("ix_price_history_id_product", table_name="price_history")
    op.drop_table("price_history")
    op.drop_index("ix_collection_items_id_product", table_name="collection_items")
    op.drop_index("ix_collection_items_card_id", table_name="collection_items")
    op.drop_index("ix_collection_items_collection_id", table_name="collection_items")
    op.drop_table("collection_items")
    op.drop_index("ix_collections_user_id", table_name="collections")
    op.drop_table("collections")
