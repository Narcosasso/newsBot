"""prezzi PSA 10: fonte, id esterno e valuta dei prezzi sorvegliati

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tracking_targets") as batch:
        batch.add_column(sa.Column("source", sa.String(length=16), nullable=False, server_default="cardmarket"))
        batch.add_column(sa.Column("external_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"))
        batch.alter_column("id_product", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("tracking_targets") as batch:
        batch.alter_column("id_product", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("currency")
        batch.drop_column("external_id")
        batch.drop_column("source")
