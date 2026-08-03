"""parent child billing items

子型号升级为独立数量型计费项：price_config 增加 parent_key；
item_price_detail 的型号数据转为 price_config 子行后删除该表

Revision ID: 7a8b9c0d1e2f
Revises: 6a7b8c9d0e1f
Create Date: 2026-08-03 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a8b9c0d1e2f'
down_revision = '6a7b8c9d0e1f'
branch_labels = None
depends_on = None


def upgrade():
    # 1. price_config 增加 parent_key
    op.add_column('price_config', sa.Column('parent_key', sa.String(length=50), nullable=True))

    # 2. item_price_detail 的型号 → price_config 子行（独立数量型计费项）
    #    子项 item_key = 父key_型号小写；item_name = 型号名；item_type = quantity；unit 继承父项
    op.execute("""
        INSERT INTO price_config (item_key, item_name, item_type, parent_key, price_fen, unit, sort_order, enabled, updated_by)
        SELECT CONCAT(p.item_key, '_', LOWER(d.option_key)),
               d.option_name,
               'quantity',
               p.item_key,
               d.price_fen,
               p.unit,
               100 + d.id,
               1,
               d.updated_by
        FROM item_price_detail d
        JOIN price_config p ON p.id = d.item_id
    """)

    # 3. 父项（model 型）价格置空、unit 保留（分组容器不参与算价）
    op.execute("UPDATE price_config SET price_fen = 0 WHERE item_type = 'model'")

    # 4. 删除 item_price_detail 表（数据已迁移）
    op.drop_table('item_price_detail')


def downgrade():
    # 从 price_config 子行恢复 item_price_detail（仅还原 model 型父项下的子行）
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
    op.execute("""
        INSERT INTO item_price_detail (item_id, option_key, option_name, price_fen, updated_by)
        SELECT p.id, c.item_name, c.item_name, c.price_fen, c.updated_by
        FROM price_config c
        JOIN price_config p ON p.item_key = c.parent_key AND p.item_type = 'model'
    """)
    op.execute("DELETE FROM price_config WHERE parent_key IS NOT NULL")
    op.drop_column('price_config', 'parent_key')
