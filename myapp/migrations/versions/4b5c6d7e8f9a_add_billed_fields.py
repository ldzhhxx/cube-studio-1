"""add billed fields to pod_info_history_v2

Revision ID: 4b5c6d7e8f9a
Revises: 3a4b5c6d7e8f
Create Date: 2026-08-04 10:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4b5c6d7e8f9a'
down_revision = '3a4b5c6d7e8f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'pod_info_history_v2'):
        return
    inspector = sa.inspect(bind)
    cols = [c['name'] for c in inspector.get_columns('pod_info_history_v2')]
    if 'billed_duration' not in cols:
        op.add_column('pod_info_history_v2', sa.Column('billed_duration', sa.Float(), nullable=True))
    if 'billed_count' not in cols:
        op.add_column('pod_info_history_v2', sa.Column('billed_count', sa.Integer(), nullable=True))
    if 'last_billed_at' not in cols:
        op.add_column('pod_info_history_v2', sa.Column('last_billed_at', sa.DateTime(), nullable=True))
    # 存量初始化：已生效扣费单（draft/cancelled/failed 不计）按 pod 回填指针，避免重复收费
    if bind.dialect.has_table(bind, 'bill'):
        op.execute("""UPDATE pod_info_history_v2 p
                      JOIN (SELECT pod_uid,
                                   MAX(deduct_to_hours) AS billed_duration,
                                   COUNT(*) AS billed_count,
                                   MAX(created_on) AS last_billed_at
                            FROM bill
                            WHERE pod_uid IS NOT NULL AND pod_uid != ''
                              AND status NOT IN ('draft', 'cancelled', 'failed')
                            GROUP BY pod_uid) b ON b.pod_uid = p.pod_uid
                      SET p.billed_duration = b.billed_duration,
                          p.billed_count = b.billed_count,
                          p.last_billed_at = b.last_billed_at""")


def downgrade():
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, 'pod_info_history_v2'):
        return
    for col in ('billed_duration', 'billed_count', 'last_billed_at'):
        try:
            op.drop_column('pod_info_history_v2', col)
        except Exception:
            pass
