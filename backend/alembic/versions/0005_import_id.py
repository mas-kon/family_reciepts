"""receipts.import_id: records booked from one bank statement

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18
"""
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# statement rows booked before this migration: consecutive bank records without a bot reply
# (notifications always get one) created within this gap belong to one import
GAP = timedelta(minutes=2)


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("import_id", sa.String(40), nullable=True))
        batch.create_index("ix_receipts_import_id", ["import_id"])

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, created_at FROM receipts WHERE source = 'bank' AND bot_message_id IS NULL "
            "ORDER BY created_at, id"
        )
    ).fetchall()
    batch_id, last = None, None
    for rid, created in rows:
        created = datetime.fromisoformat(str(created)) if created else None
        if batch_id is None or created is None or last is None or created - last > GAP:
            batch_id = f"old-{rid}"
        last = created
        conn.execute(sa.text("UPDATE receipts SET import_id = :b WHERE id = :id"), {"b": batch_id, "id": rid})


def downgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.drop_index("ix_receipts_import_id")
        batch.drop_column("import_id")
