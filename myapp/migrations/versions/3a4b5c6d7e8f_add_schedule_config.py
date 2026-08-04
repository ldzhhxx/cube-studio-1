"""add schedule config keys

Revision ID: 3a4b5c6d7e8f
Revises: 1c2d3e4f5a6b
Create Date: 2026-08-04 09:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a4b5c6d7e8f'
down_revision = '1c2d3e4f5a6b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'billing_config'):
        return
    # 定时扣费周期（分钟，0=关闭）+ 上次定时执行时间
    op.execute("""INSERT INTO billing_config (cfg_key, cfg_value, cfg_desc)
                  SELECT 'schedule_interval_minutes', '0', '定时扣费周期（分钟，0=关闭）'
                  WHERE NOT EXISTS (SELECT 1 FROM billing_config WHERE cfg_key='schedule_interval_minutes')""")
    op.execute("""INSERT INTO billing_config (cfg_key, cfg_value, cfg_desc)
                  SELECT 'last_scheduled_run', '', '上次定时扣费执行时间'
                  WHERE NOT EXISTS (SELECT 1 FROM billing_config WHERE cfg_key='last_scheduled_run')""")


def downgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'billing_config'):
        return
    for k in ('schedule_interval_minutes', 'last_scheduled_run'):
        op.execute("DELETE FROM billing_config WHERE cfg_key='%s'" % k)
