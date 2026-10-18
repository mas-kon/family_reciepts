"""income and inside-the-family transfers

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TRANSFER_PREFIX = "Перевод: "


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="expense"))
        batch.add_column(sa.Column("counterparty", sa.String(200), nullable=True))
        batch.add_column(sa.Column("peer_user_id", sa.Integer(), nullable=True))
        batch.create_index("ix_receipts_kind", ["kind"])
        batch.create_foreign_key(
            "fk_receipts_peer_user_id_users", "users", ["peer_user_id"], ["id"], ondelete="SET NULL"
        )
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("bank_names", sa.String(500), nullable=True))
    with op.batch_alter_table("categories") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="expense"))
    with op.batch_alter_table("recurring") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="expense"))

    # bank transfers booked before: "Перевод: Vera Maslennikova" -> counterparty
    op.get_bind().execute(
        sa.text("UPDATE receipts SET counterparty = trim(substr(store, :n)) WHERE source = 'bank' AND store LIKE :p"),
        {"n": len(TRANSFER_PREFIX) + 1, "p": TRANSFER_PREFIX + "%"},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM categories WHERE kind = 'income'"))
    with op.batch_alter_table("recurring") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("categories") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("bank_names")
    with op.batch_alter_table("receipts") as batch:
        batch.drop_constraint("fk_receipts_peer_user_id_users", type_="foreignkey")
        batch.drop_index("ix_receipts_kind")
        batch.drop_column("peer_user_id")
        batch.drop_column("counterparty")
        batch.drop_column("kind")
