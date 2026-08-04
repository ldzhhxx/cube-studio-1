"""create all_node_memory

Revision ID: 0a1b2c3d4e5f
Revises: 9a8b7c6d5e4f
Create Date: 2026-08-04 08:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0a1b2c3d4e5f'
down_revision = '9a8b7c6d5e4f'
branch_labels = None
depends_on = None


def upgrade():
    # 生产库可能已存在该表（外部维护），存在则跳过
    bind = op.get_bind()
    if bind.dialect.has_table(bind, 'all_node_memory'):
        return
    op.create_table('all_node_memory',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('node_name', sa.String(length=255), nullable=True),
    sa.Column('gpu_type', sa.String(length=100), nullable=True),
    sa.Column('gpu_num', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_name')
    )
    # ### end Alembic commands ###


def downgrade():
    bind = op.get_bind()
    if bind.dialect.has_table(bind, 'all_node_memory'):
        op.drop_table('all_node_memory')
