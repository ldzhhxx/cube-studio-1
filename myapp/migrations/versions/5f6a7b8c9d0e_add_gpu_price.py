"""add gpu price table and bill gpu_type

GPU 按型号定价：gpu_price 表（型号 → 每卡每月价格分）；bill 增加 gpu_type 字段

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-08-03 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f6a7b8c9d0e'
down_revision = '4e5f6a7b8c9d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('gpu_price',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('gpu_type', sa.String(length=50), nullable=False),
        sa.Column('price_fen', sa.Integer(), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('gpu_type')
    )
    # 默认 GPU 型号价格（元/卡/月，管理员可改）
    gpu_price = sa.table('gpu_price',
        sa.column('gpu_type', sa.String(50)),
        sa.column('price_fen', sa.Integer()),
        sa.column('unit', sa.String(50)),
        sa.column('updated_by', sa.String(100)),
    )
    op.bulk_insert(gpu_price, [
        {'gpu_type': 'A40', 'price_fen': 300000, 'unit': '元/卡/月', 'updated_by': 'system'},
        {'gpu_type': 'L20', 'price_fen': 200000, 'unit': '元/卡/月', 'updated_by': 'system'},
        {'gpu_type': 'A100', 'price_fen': 500000, 'unit': '元/卡/月', 'updated_by': 'system'},
        {'gpu_type': 'H100', 'price_fen': 800000, 'unit': '元/卡/月', 'updated_by': 'system'},
    ])
    # bill 表增加 GPU 型号字段
    op.add_column('bill', sa.Column('gpu_type', sa.String(length=50), nullable=True))
    op.create_index('ix_bill_gpu_type', 'bill', ['gpu_type'])


def downgrade():
    op.drop_index('ix_bill_gpu_type', table_name='bill')
    op.drop_column('bill', 'gpu_type')
    op.drop_table('gpu_price')
