"""add billing_start_time config

Revision ID: 5c6d7e8f9a0b
Revises: 4b5c6d7e8f9a
Create Date: 2026-08-04 11:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c6d7e8f9a0b'
down_revision = '4b5c6d7e8f9a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'billing_config'):
        return
    # 开始收费时间：空=从任务创建起全部计费；设置后只收该时间之后的时长
    op.execute("""INSERT INTO billing_config (cfg_key, cfg_value, cfg_desc)
                  SELECT 'billing_start_time', '', '开始收费时间（YYYY-MM-DD HH:MM:SS，空=全部计费）'
                  WHERE NOT EXISTS (SELECT 1 FROM billing_config WHERE cfg_key='billing_start_time')""")


def downgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'billing_config'):
        return
    op.execute("DELETE FROM billing_config WHERE cfg_key='billing_start_time'")
