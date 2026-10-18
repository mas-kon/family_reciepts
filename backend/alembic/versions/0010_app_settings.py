"""app_settings: family-wide settings such as the interface language

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
