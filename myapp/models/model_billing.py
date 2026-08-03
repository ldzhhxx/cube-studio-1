# 计费系统数据模型
# 方案：外部费用清单接口推送，平台只记账
#   bill       费用明细（一个 pod 一条，pod_name 唯一幂等）
#   wallet     用户钱包余额（分）
#   account_log 资金流水（充值/消费/转账，双向审计）
from flask_appbuilder import Model
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
import datetime
from myapp import app, db
from myapp.models.base import MyappModelBase

conf = app.config
metadata = Model.metadata


# 费用明细：外部推送后生成，一次任务运行（一个 pod）一条
class Bill(Model, MyappModelBase):
    __tablename__ = 'bill'
    id = Column(Integer, primary_key=True)
    pod_name = Column(String(200), nullable=False, unique=True)   # pod名，唯一去重键
    task_name = Column(String(200), default='')                   # 任务名
    run_id = Column(String(200), default='')                      # 关联的平台运行id（可选）
    username = Column(String(100), default='')                    # 归属用户名
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True, default=None)  # 归属用户（外部推送可能对不上用户，允许为空）
    org = Column(String(200), default='')                         # 冗余部门（ab_user.org），用于按部门统计
    cpu = Column(Float, default=0)                                # cpu核数
    memory = Column(Float, default=0)                             # 内存GB
    gpu_num = Column(Float, default=0)                            # gpu卡数
    gpu_type = Column(String(50), default='')                     # GPU 型号（A40/L20/...），定价按型号
    gpu_memory = Column(Float, default=0)                         # 显存GB
    duration_seconds = Column(Integer, default=0)                 # 运行时间（秒）
    amount_fen = Column(Integer, default=0)                       # 费用（分）
    start_time = Column(DateTime, default=None)
    end_time = Column(DateTime, default=None)
    status = Column(String(50), default='settled')                # settled=已入账 failed=入账失败
    source = Column(String(50), default='external')               # 来源：external=外部清单推送
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)
    updated_on = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def amount_yuan(self):
        return round(self.amount_fen / 100.0, 2) if self.amount_fen else 0

    @property
    def duration_hours(self):
        return round(self.duration_seconds / 3600.0, 2) if self.duration_seconds else 0

    def __repr__(self):
        return self.pod_name


# 用户钱包余额
class Wallet(Model, MyappModelBase):
    __tablename__ = 'wallet'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), unique=True, nullable=False)  # 一用户一行
    balance_fen = Column(Integer, default=0)                      # 余额（分），可为负
    updated_on = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def balance_yuan(self):
        return round(self.balance_fen / 100.0, 2) if self.balance_fen else 0

    def __repr__(self):
        return '%s:%s' % (self.user_id, self.balance_fen)


# 计费项配置（动态，数据驱动）：数量型 quantity / 型号型 model
# 后期新增计费项（存储/服务运维等）只需在前端添加配置，无需改代码
class PriceConfig(Model, MyappModelBase):
    __tablename__ = 'price_config'
    id = Column(Integer, primary_key=True)
    item_key = Column(String(50), nullable=False, unique=True)   # 计费项标识：cpu / memory / gpu / storage ...
    item_name = Column(String(100), default='')                  # 显示名：CPU / 内存 / GPU / 存储
    item_type = Column(String(20), default='quantity')           # quantity 数量型 / model 型号型
    price_fen = Column(Integer, default=0)                       # 数量型：单价（分/单位/月）
    unit = Column(String(50), default='')                        # 单位描述，如 元/核/月
    sort_order = Column(Integer, default=0)                      # 展示顺序
    enabled = Column(Integer, default=1)                         # 1 启用 / 0 停用
    updated_by = Column(String(100), default='')
    updated_on = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    @property
    def price_yuan(self):
        return round(self.price_fen / 100.0, 4) if self.price_fen else 0

    def __repr__(self):
        return '%s:%s' % (self.item_key, self.price_fen)


# 型号型计费项的细项价格（如 GPU 的 A40 / L20 各自单价）
class ItemPriceDetail(Model, MyappModelBase):
    __tablename__ = 'item_price_detail'
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey('price_config.id'), nullable=False)
    option_key = Column(String(50), nullable=False)              # 型号标识：A40 / L20
    option_name = Column(String(100), default='')                # 显示名
    price_fen = Column(Integer, default=0)                       # 该型号单价（分/单位/月）
    updated_by = Column(String(100), default='')
    updated_on = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)
    __table_args__ = (UniqueConstraint('item_id', 'option_key', name='uq_item_option'),)

    @property
    def price_yuan(self):
        return round(self.price_fen / 100.0, 4) if self.price_fen else 0

    def __repr__(self):
        return '%s:%s' % (self.option_key, self.price_fen)


# 账单明细项（快照）：每笔账单的每个计费项一行，价格以当时为准
class BillItem(Model, MyappModelBase):
    __tablename__ = 'bill_item'
    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey('bill.id'), nullable=False)
    item_key = Column(String(50), default='')
    item_name = Column(String(100), default='')
    option_key = Column(String(50), default='')                  # 型号（型号型）
    quantity = Column(Float, default=0)                          # 数量
    unit_price_fen = Column(Integer, default=0)                  # 单价快照（分/单位/月）
    amount_fen = Column(Integer, default=0)                      # 该项费用（分）
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)

    def __repr__(self):
        return '%s:%s' % (self.item_key, self.amount_fen)


# 资金流水：充值/消费/转账全部走流水，双向审计
class AccountLog(Model, MyappModelBase):
    __tablename__ = 'account_log'
    id = Column(Integer, primary_key=True)
    type = Column(String(50), nullable=False)                     # recharge充值 consume消费 transfer_in转入 transfer_out转出
    from_user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True, default=None)  # 转出方（消费时为归属用户）
    to_user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True, default=None)    # 转入方
    amount_fen = Column(Integer, default=0)                       # 金额（分）
    balance_before_fen = Column(Integer, default=0)               # 变动前余额
    balance_after_fen = Column(Integer, default=0)                # 变动后余额
    bill_id = Column(Integer, ForeignKey('bill.id'), nullable=True, default=None)   # 关联费用明细
    operator = Column(String(100), default='')                    # 操作人
    remark = Column(String(500), default='')                      # 备注
    reversed = Column(Integer, default=0, nullable=False)         # 0 正常 / 1 已冲正（撤销）
    ref_log_id = Column(Integer, default=None, nullable=True)     # 冲正流水引用的原流水 id
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)

    def __repr__(self):
        return '%s:%s' % (self.type, self.amount_fen)
