"""app PokeVault: sessioni di accesso e carte viste di recente

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_sessions_token_hash", "app_sessions", ["token_hash"], unique=True)
    op.create_index("ix_app_sessions_user_id", "app_sessions", ["user_id"])
    op.create_table(
        "recent_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.String(length=64), nullable=False),
        sa.Column("catalog_lang", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("image", sa.String(length=300), nullable=True),
        sa.Column("set_name", sa.String(length=200), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "catalog_lang", "card_id", name="uq_recent_user_card"),
    )
    op.create_index("ix_recent_views_user_id", "recent_views", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_recent_views_user_id", table_name="recent_views")
    op.drop_table("recent_views")
    op.drop_index("ix_app_sessions_user_id", table_name="app_sessions")
    op.drop_index("ix_app_sessions_token_hash", table_name="app_sessions")
    op.drop_table("app_sessions")
