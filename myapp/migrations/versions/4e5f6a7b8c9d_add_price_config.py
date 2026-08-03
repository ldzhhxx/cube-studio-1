"""add price config table

计费标准：cpu / memory / gpu_memory 三种资源单价（分/单位/小时），含默认价格

Revision ID: 4e5f6a7b8c9d
Revises: 8d3e2f1a6c9b
Create Date: 2026-08-03 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e5f6a7b8c9d'
down_revision = '8d3e2f1a6c9b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('price_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('price_fen', sa.Integer(), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resource_type')
    )
    # 默认计费标准（按月计费，按使用时长折算）：cpu 200元/核/月、内存 100元/GB/月、显存 1000元/GB/月
    price_config = sa.table('price_config',
        sa.column('resource_type', sa.String(50)),
        sa.column('price_fen', sa.Integer()),
        sa.column('unit', sa.String(50)),
        sa.column('updated_by', sa.String(100)),
    )
    op.bulk_insert(price_config, [
        {'resource_type': 'cpu', 'price_fen': 20000, 'unit': '元/核/月', 'updated_by': 'system'},
        {'resource_type': 'memory', 'price_fen': 10000, 'unit': '元/GB/月', 'updated_by': 'system'},
        {'resource_type': 'gpu_memory', 'price_fen': 100000, 'unit': '元/GB显存/月', 'updated_by': 'system'},
    ])


def downgrade():
    op.drop_table('price_config')
