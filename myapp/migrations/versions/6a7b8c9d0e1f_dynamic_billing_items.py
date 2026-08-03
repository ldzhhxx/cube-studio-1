"""dynamic billing items

计费项动态化：price_config 改造为通用计费项（quantity/model）；
GPU 型号价格并入 item_price_detail；新增 bill_item 账单明细快照表；删除 gpu_price

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-08-03 17:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a7b8c9d0e1f'
down_revision = '5f6a7b8c9d0e'
branch_labels = None
depends_on = None


def upgrade():
    # 1. price_config 列改造：resource_type → item_key，新增动态字段（MySQL 需显式类型）
    op.alter_column('price_config', 'resource_type', new_column_name='item_key',
                    existing_type=sa.String(length=50), existing_nullable=False)
    op.add_column('price_config', sa.Column('item_name', sa.String(length=100), nullable=True))
    op.add_column('price_config', sa.Column('item_type', sa.String(length=20), nullable=True))
    op.add_column('price_config', sa.Column('sort_order', sa.Integer(), nullable=True))
    op.add_column('price_config', sa.Column('enabled', sa.Integer(), nullable=True))

    # 2. 现有数据：cpu/memory 标为数量型；gpu_memory 行删除（GPU 已改为型号定价）
    op.execute("UPDATE price_config SET item_name='CPU', item_type='quantity', unit='元/核/月', sort_order=1, enabled=1 WHERE item_key='cpu'")
    op.execute("UPDATE price_config SET item_name='内存', item_type='quantity', unit='元/GB/月', sort_order=2, enabled=1 WHERE item_key='memory'")
    op.execute("DELETE FROM price_config WHERE item_key='gpu_memory'")

    # 3. GPU 作为型号型计费项（细项价格来自 gpu_price）
    op.execute("INSERT INTO price_config (item_key, item_name, item_type, price_fen, unit, sort_order, enabled, updated_by) "
               "VALUES ('gpu', 'GPU', 'model', 0, '元/卡/月', 3, 1, 'system')")

    # 4. 建 item_price_detail 并迁移 gpu_price 数据
    op.create_table('item_price_detail',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('option_key', sa.String(length=50), nullable=False),
        sa.Column('option_name', sa.String(length=100), nullable=True),
        sa.Column('price_fen', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.String(length=100), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['price_config.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'option_key', name='uq_item_option')
    )
    op.execute("INSERT INTO item_price_detail (item_id, option_key, option_name, price_fen, updated_by) "
               "SELECT p.id, g.gpu_type, g.gpu_type, g.price_fen, g.updated_by "
               "FROM gpu_price g JOIN price_config p ON p.item_key='gpu'")

    # 5. 建 bill_item 账单明细快照表
    op.create_table('bill_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bill_id', sa.Integer(), nullable=False),
        sa.Column('item_key', sa.String(length=50), nullable=True),
        sa.Column('item_name', sa.String(length=100), nullable=True),
        sa.Column('option_key', sa.String(length=50), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit_price_fen', sa.Integer(), nullable=True),
        sa.Column('amount_fen', sa.Integer(), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['bill_id'], ['bill.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bill_item_bill_id', 'bill_item', ['bill_id'])

    # 6. 删除 gpu_price 表（数据已并入 item_price_detail）
    op.drop_table('gpu_price')


def downgrade():
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
    op.drop_index('ix_bill_item_bill_id', table_name='bill_item')
    op.drop_table('bill_item')
    op.drop_table('item_price_detail')
    op.execute("DELETE FROM price_config WHERE item_key='gpu'")
    op.execute("INSERT INTO price_config (item_key, item_name, item_type, price_fen, unit, sort_order, enabled, updated_by) "
               "VALUES ('gpu_memory', '显存', 'quantity', 0, '元/GB/月', 3, 1, 'system')")
    op.drop_column('price_config', 'enabled')
    op.drop_column('price_config', 'sort_order')
    op.drop_column('price_config', 'item_type')
    op.drop_column('price_config', 'item_name')
    op.alter_column('price_config', 'item_key', new_column_name='resource_type')
