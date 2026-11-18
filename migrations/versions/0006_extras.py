"""lista desideri, numeri Pokédex delle carte possedute, notifiche push

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as b:
        b.add_column(sa.Column("kind", sa.String(length=16), server_default="collection", nullable=False))
    with op.batch_alter_table("collection_items") as b:
        b.add_column(sa.Column("dex_ids", sa.String(length=32), nullable=True))
        b.add_column(sa.Column("target_price", sa.Float(), nullable=True))
        b.add_column(sa.Column("target_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=600), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    with op.batch_alter_table("collection_items") as b:
        b.drop_column("target_notified_at")
        b.drop_column("target_price")
        b.drop_column("dex_ids")
    with op.batch_alter_table("collections") as b:
        b.drop_column("kind")
