"""add billing indexes

商用加固：计费表高频查询字段加索引（按用户/时间筛选、按部门汇总）

Revision ID: 2a9c4f8e1b5d
Revises: 1ee3bd719439
Create Date: 2026-08-03 14:20:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '2a9c4f8e1b5d'
down_revision = '1ee3bd719439'
branch_labels = None
depends_on = None


def upgrade():
    # bill：按用户查我的账单、按时间/部门筛选汇总
    op.create_index('ix_bill_username', 'bill', ['username'])
    op.create_index('ix_bill_org', 'bill', ['org'])
    op.create_index('ix_bill_created_on', 'bill', ['created_on'])
    # account_log：按用户/时间查流水
    op.create_index('ix_account_log_from_user_id', 'account_log', ['from_user_id'])
    op.create_index('ix_account_log_to_user_id', 'account_log', ['to_user_id'])
    op.create_index('ix_account_log_created_on', 'account_log', ['created_on'])


def downgrade():
    op.drop_index('ix_bill_username', table_name='bill')
    op.drop_index('ix_bill_org', table_name='bill')
    op.drop_index('ix_bill_created_on', table_name='bill')
    op.drop_index('ix_account_log_from_user_id', table_name='account_log')
    op.drop_index('ix_account_log_to_user_id', table_name='account_log')
    op.drop_index('ix_account_log_created_on', table_name='account_log')
