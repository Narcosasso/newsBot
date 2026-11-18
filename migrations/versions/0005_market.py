"""dati di mercato per l'analisi: prodotti Cardmarket e andamento dei set

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_info",
        sa.Column("id_product", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("id_expansion", sa.Integer(), nullable=True),
        sa.Column("id_metacard", sa.Integer(), nullable=True),
        sa.Column("date_added", sa.Date(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id_product"),
    )
    op.create_index("ix_product_info_id_expansion", "product_info", ["id_expansion"])
    op.create_index("ix_product_info_id_metacard", "product_info", ["id_metacard"])
    op.create_table(
        "set_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("id_expansion", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cards", sa.Integer(), nullable=False),
        sa.Column("total_trend", sa.Float(), nullable=False),
        sa.Column("median_change_7d", sa.Float(), nullable=True),
        sa.Column("median_change_30d", sa.Float(), nullable=True),
        sa.Column("share_up_30d", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id_expansion", "day", name="uq_set_stats_day"),
    )
    op.create_index("ix_set_stats_id_expansion", "set_stats", ["id_expansion"])


def downgrade() -> None:
    op.drop_index("ix_set_stats_id_expansion", table_name="set_stats")
    op.drop_table("set_stats")
    op.drop_index("ix_product_info_id_metacard", table_name="product_info")
    op.drop_index("ix_product_info_id_expansion", table_name="product_info")
    op.drop_table("product_info")
