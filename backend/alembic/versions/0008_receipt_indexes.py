"""indexes for finding a record by chat message, owner and peer

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.create_index("ix_receipts_chat_message", ["chat_id", "message_id"])
        batch.create_index("ix_receipts_bot_message_id", ["bot_message_id"])
        batch.create_index("ix_receipts_user_id", ["user_id"])
        batch.create_index("ix_receipts_peer_user_id", ["peer_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.drop_index("ix_receipts_peer_user_id")
        batch.drop_index("ix_receipts_user_id")
        batch.drop_index("ix_receipts_bot_message_id")
        batch.drop_index("ix_receipts_chat_message")
