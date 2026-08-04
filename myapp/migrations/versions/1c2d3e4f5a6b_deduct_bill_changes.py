"""deduct: bill 表改造（去唯一约束+扣费字段）+ 扣费相关四张新表

Revision ID: 1c2d3e4f5a6b
Revises: 0a1b2c3d4e5f
Create Date: 2026-08-04 08:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c2d3e4f5a6b'
down_revision = '0a1b2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. bill 去掉 pod_name 唯一约束：同一 pod 允许多次扣费（增量结算），外部推送幂等改为应用层判断
    indexes = [i['name'] for i in inspector.get_indexes('bill')]
    if 'pod_name' in indexes:
        op.drop_index('pod_name', table_name='bill')

    # 2. bill 新增扣费字段
    cols = [c['name'] for c in inspector.get_columns('bill')]
    if 'pod_uid' not in cols:
        op.add_column('bill', sa.Column('pod_uid', sa.String(length=200), nullable=True))
        op.create_index('ix_bill_pod_uid', 'bill', ['pod_uid'])
    if 'billing_run_id' not in cols:
        op.add_column('bill', sa.Column('billing_run_id', sa.Integer(), nullable=True))
        op.create_index('ix_bill_billing_run_id', 'bill', ['billing_run_id'])
    if 'deduct_from_hours' not in cols:
        op.add_column('bill', sa.Column('deduct_from_hours', sa.Float(), nullable=True))
    if 'deduct_to_hours' not in cols:
        op.add_column('bill', sa.Column('deduct_to_hours', sa.Float(), nullable=True))

    # 3. 新表：扣费批次
    if not bind.dialect.has_table(bind, 'billing_run'):
        op.create_table('billing_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('execute_type', sa.String(length=20), nullable=True),
        sa.Column('operator', sa.String(length=100), nullable=True),
        sa.Column('generated_count', sa.Integer(), nullable=True),
        sa.Column('skipped_no_delta', sa.Integer(), nullable=True),
        sa.Column('skipped_not_running', sa.Integer(), nullable=True),
        sa.Column('skipped_below_min', sa.Integer(), nullable=True),
        sa.Column('skipped_whitelist', sa.Integer(), nullable=True),
        sa.Column('skipped_no_user', sa.Integer(), nullable=True),
        sa.Column('skipped_fallback_gpu', sa.Integer(), nullable=True),
        sa.Column('remark', sa.String(length=500), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )

    # 4. 新表：质疑记录
    if not bind.dialect.has_table(bind, 'bill_dispute'):
        op.create_table('bill_dispute',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bill_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('resolution', sa.String(length=20), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('operator', sa.String(length=100), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('processed_on', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['bill_id'], ['bill.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['ab_user.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    # 5. 新表：扣费白名单
    if not bind.dialect.has_table(bind, 'bill_whitelist'):
        op.create_table('bill_whitelist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dimension', sa.String(length=20), nullable=False),
        sa.Column('value', sa.String(length=200), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('enabled', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dimension', 'value', name='uq_whitelist_dim_value')
        )

    # 6. 新表：扣费规则配置 + 默认值
    if not bind.dialect.has_table(bind, 'billing_config'):
        op.create_table('billing_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cfg_key', sa.String(length=50), nullable=False),
        sa.Column('cfg_value', sa.String(length=200), nullable=True),
        sa.Column('cfg_desc', sa.String(length=200), nullable=True),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cfg_key')
        )
        op.bulk_insert(sa.table('billing_config',
            sa.column('cfg_key', sa.String), sa.column('cfg_value', sa.String), sa.column('cfg_desc', sa.String)),
            [
                {'cfg_key': 'min_duration_minutes', 'cfg_value': '10', 'cfg_desc': '最低付费时长阈值（分钟）'},
                {'cfg_key': 'month_hours', 'cfg_value': '720', 'cfg_desc': '月价→小时价折算系数'},
                {'cfg_key': 'auto_settle_days', 'cfg_value': '7', 'cfg_desc': '扣费单超时自动扣费天数'},
                {'cfg_key': 'gpu_fallback', 'cfg_value': 'L20', 'cfg_desc': 'node_name 查不到显卡型号时的兜底型号'},
                {'cfg_key': 'enabled', 'cfg_value': '1', 'cfg_desc': '扣费功能总开关（0 关闭）'},
            ])
    # ### end Alembic commands ###


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for t in ('billing_run', 'bill_dispute', 'bill_whitelist', 'billing_config'):
        if bind.dialect.has_table(bind, t):
            op.drop_table(t)
    cols = [c['name'] for c in inspector.get_columns('bill')]
    for col, index in (('pod_uid', 'ix_bill_pod_uid'), ('billing_run_id', 'ix_bill_billing_run_id')):
        if col in cols:
            try:
                op.drop_index(index, table_name='bill')
            except Exception:
                pass
            op.drop_column('bill', col)
    for col in ('deduct_from_hours', 'deduct_to_hours'):
        if col in cols:
            op.drop_column('bill', col)
    indexes = [i['name'] for i in inspector.get_indexes('bill')]
    if 'pod_name' not in indexes:
        op.create_index('pod_name', 'bill', ['pod_name'], unique=True)
