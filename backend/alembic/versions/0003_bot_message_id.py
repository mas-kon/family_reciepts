"""bot reply message id on receipts

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("bot_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.drop_column("bot_message_id")
