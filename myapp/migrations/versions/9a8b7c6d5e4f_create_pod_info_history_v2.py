"""create pod_info_history_v2

Revision ID: 9a8b7c6d5e4f
Revises: 5c9d8e7f6a1b
Create Date: 2026-08-04 07:14:19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a8b7c6d5e4f'
down_revision = '5c9d8e7f6a1b'
branch_labels = None
depends_on = None


def upgrade():
    # 生产库可能已存在该表（由外部采集程序维护），存在则跳过，避免重复建表报错
    bind = op.get_bind()
    if bind.dialect.has_table(bind, 'pod_info_history_v2'):
        return
    op.create_table('pod_info_history_v2',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=255), nullable=True),
    sa.Column('k8s_namespace', sa.String(length=255), nullable=True),
    sa.Column('pod_uid', sa.String(length=255), nullable=True),
    sa.Column('pod_name', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=255), nullable=True),
    sa.Column('node_name', sa.String(length=255), nullable=True),
    sa.Column('machine_ip', sa.String(length=255), nullable=True),
    sa.Column('pod_ip', sa.String(length=255), nullable=True),
    sa.Column('cluster', sa.String(length=100), nullable=True),
    sa.Column('mem_usage_gb', sa.Float(), nullable=True),
    sa.Column('cpu_usage', sa.Float(), nullable=True),
    sa.Column('gpu_mem_usage_gb', sa.Float(), nullable=True),
    sa.Column('gpu_usage', sa.Float(), nullable=True),
    sa.Column('mem_limit_gb', sa.Float(), nullable=True),
    sa.Column('cpu_limit', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('label', sa.String(length=255), nullable=True),
    sa.Column('duration', sa.String(length=255), nullable=True),
    sa.Column('gpu_type', sa.String(length=255), nullable=True),
    sa.Column('tf32', sa.String(length=255), nullable=True),
    sa.Column('gpu_mem_util', sa.String(length=255), nullable=True),
    sa.Column('gpu_util', sa.String(length=255), nullable=True),
    sa.Column('conversion_rate', sa.String(length=255), nullable=True),
    sa.Column('pending_at', sa.DateTime(), nullable=True),
    sa.Column('pending_message', sa.Text(), nullable=True),
    sa.Column('waiting_time', sa.String(length=255), nullable=True),
    sa.Column('update_at', sa.DateTime(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    bind = op.get_bind()
    if bind.dialect.has_table(bind, 'pod_info_history_v2'):
        op.drop_table('pod_info_history_v2')
