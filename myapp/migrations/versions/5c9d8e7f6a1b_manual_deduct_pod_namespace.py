"""manual deduct pod_name optional + namespace

手动扣费支持自定义 pod 名（选填，为空存 NULL 不再自动生成 manual-xxx）；
bill 新增 namespace 列（命名空间，手动扣费/外部推送均可填写）

Revision ID: 5c9d8e7f6a1b
Revises: 7a8b9c0d1e2f
Create Date: 2026-08-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c9d8e7f6a1b'
down_revision = '7a8b9c0d1e2f'
branch_labels = None
depends_on = None


def upgrade():
    # 1. pod_name 允许 NULL（唯一索引仍保留：MySQL 允许多个 NULL，推送幂等键不受影响）
    op.alter_column('bill', 'pod_name',
                    existing_type=sa.String(length=200),
                    existing_nullable=False,
                    nullable=True)
    # 2. bill 新增 namespace 列
    op.add_column('bill', sa.Column('namespace', sa.String(length=200), nullable=True))
    # 3. bill_item 新增 unit 单位快照列（明细展示用）
    op.add_column('bill_item', sa.Column('unit', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('bill_item', 'unit')
    op.drop_column('bill', 'namespace')
    op.alter_column('bill', 'pod_name',
                    existing_type=sa.String(length=200),
                    existing_nullable=True,
                    nullable=False)
