"""add account_log reverse fields

冲正/撤销机制：原流水标记 reversed + 冲正流水引用 ref_log_id

Revision ID: 8d3e2f1a6c9b
Revises: 2a9c4f8e1b5d
Create Date: 2026-08-03 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8d3e2f1a6c9b'
down_revision = '2a9c4f8e1b5d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('account_log', sa.Column('reversed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('account_log', sa.Column('ref_log_id', sa.Integer(), nullable=True))
    op.create_index('ix_account_log_reversed', 'account_log', ['reversed'])


def downgrade():
    op.drop_index('ix_account_log_reversed', table_name='account_log')
    op.drop_column('account_log', 'ref_log_id')
    op.drop_column('account_log', 'reversed')
