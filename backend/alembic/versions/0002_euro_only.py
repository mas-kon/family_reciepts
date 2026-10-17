"""euro only: drop currency columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.drop_column("currency")
        batch.drop_column("eur_rate")
    with op.batch_alter_table("recurring") as batch:
        batch.drop_column("currency")


def downgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"))
        batch.add_column(sa.Column("eur_rate", sa.Float(), nullable=False, server_default="1.0"))
    with op.batch_alter_table("recurring") as batch:
        batch.add_column(sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"))
