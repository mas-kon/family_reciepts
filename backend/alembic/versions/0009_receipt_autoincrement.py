"""receipt ids are never reused (AUTOINCREMENT)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("receipts", table_kwargs={"sqlite_autoincrement": True}, recreate="always"):
        pass


def downgrade() -> None:
    with op.batch_alter_table("receipts", table_kwargs={"sqlite_autoincrement": False}, recreate="always"):
        pass
