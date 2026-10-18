"""categories.key: stable key of a system category

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.add_column(sa.Column("key", sa.String(50), nullable=True))
        batch.create_unique_constraint("uq_categories_key", ["key"])


def downgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.drop_constraint("uq_categories_key", type_="unique")
        batch.drop_column("key")
