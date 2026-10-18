"""ai features

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 04:33:26.395780
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('product_aliases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name_normalized', sa.String(length=300), nullable=False),
    sa.Column('product', sa.String(length=300), nullable=False),
    sa.Column('manual', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name_normalized')
    )
    with op.batch_alter_table('product_aliases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_aliases_product'), ['product'], unique=False)

    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('warranty_until', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('warranty_notified', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f('ix_items_warranty_until'), ['warranty_until'], unique=False)

    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('external_id', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('source_text', sa.Text(), nullable=True))
        batch_op.create_unique_constraint('uq_receipts_external_id', ['external_id'])

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cards', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('emails', sa.String(length=300), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('emails')
        batch_op.drop_column('cards')

    with op.batch_alter_table('receipts', schema=None) as batch_op:
        batch_op.drop_constraint('uq_receipts_external_id', type_='unique')
        batch_op.drop_column('external_id')
        batch_op.drop_column('source_text')

    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_items_warranty_until'))
        batch_op.drop_column('warranty_notified')
        batch_op.drop_column('warranty_until')

    with op.batch_alter_table('product_aliases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_aliases_product'))

    op.drop_table('product_aliases')
