"""amici: account con nome e PIN, inviti, amicizie, visibilità delle collezioni, scambi

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("display_name", sa.String(length=60), nullable=True))
        b.add_column(sa.Column("pin_hash", sa.String(length=200), nullable=True))
        b.add_column(sa.Column("invited_by", sa.Integer(), nullable=True))
    with op.batch_alter_table("collections") as b:
        b.add_column(sa.Column("visibility", sa.String(length=16), server_default="friends", nullable=False))
        b.add_column(sa.Column("show_values", sa.Boolean(), server_default="0", nullable=False))
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)
    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("friend_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["friend_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "friend_id", name="uq_friendship"),
    )
    op.create_index("ix_friendships_user_id", "friendships", ["user_id"])
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposer_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("proposer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moves", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proposer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_proposer_id", "trades", ["proposer_id"])
    op.create_index("ix_trades_recipient_id", "trades", ["recipient_id"])
    op.create_table(
        "trade_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("source_item_id", sa.Integer(), nullable=True),
        sa.Column("card_id", sa.String(length=64), nullable=False),
        sa.Column("catalog_lang", sa.String(length=8), nullable=False),
        sa.Column("variant", sa.String(length=16), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("set_name", sa.String(length=200), nullable=True),
        sa.Column("number_label", sa.String(length=32), nullable=True),
        sa.Column("image", sa.String(length=300), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_items_trade_id", "trade_items", ["trade_id"])


def downgrade() -> None:
    op.drop_index("ix_trade_items_trade_id", table_name="trade_items")
    op.drop_table("trade_items")
    op.drop_index("ix_trades_recipient_id", table_name="trades")
    op.drop_index("ix_trades_proposer_id", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_friendships_user_id", table_name="friendships")
    op.drop_table("friendships")
    op.drop_index("ix_invites_code", table_name="invites")
    op.drop_table("invites")
    with op.batch_alter_table("collections") as b:
        b.drop_column("show_values")
        b.drop_column("visibility")
    with op.batch_alter_table("users") as b:
        b.drop_column("invited_by")
        b.drop_column("pin_hash")
        b.drop_column("display_name")
