# 计费系统数据模型
# 方案：外部费用清单接口推送，平台只记账
#   bill       费用明细（一个 pod 一条，pod_name 唯一幂等）
#   wallet     用户钱包余额（分）
#   account_log 资金流水（充值/消费/转账，双向审计）
from flask_appbuilder import Model
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
import datetime
from myapp import app, db
from myapp.models.base import MyappModelBase

conf = app.config
metadata = Model.metadata


# 费用明细：外部推送后生成，一次任务运行（一个 pod）一条
# 快照自动扣费后同一 pod 可有多条（每次扣费一条，增量结算）
class Bill(Model, MyappModelBase):
    __tablename__ = 'bill'
    id = Column(Integer, primary_key=True)
    pod_name = Column(String(200))                                # pod名：推送幂等键（必填）；手动扣费选填；快照扣费为任务 pod 名（不再唯一）
    pod_uid = Column(String(200), default='')                     # 任务标识（快照扣费来源：pod_info_history_v2.pod_uid）
    billing_run_id = Column(Integer, ForeignKey('billing_run.id'), nullable=True, default=None)  # 扣费批次
    deduct_from_hours = Column(Float, default=None)               # 本次计费起点（上次已扣时长，小时）
    deduct_to_hours = Column(Float, default=None)                 # 本次计费终点（最新快照 duration，小时）
    namespace = Column(String(200), default='')                   # 命名空间（手动扣费/推送可选）
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
    duration_seconds = Column(Integer, default=0)                 # 本次计费时长（增量，秒）
    amount_fen = Column(Integer, default=0)                       # 费用（分）
    start_time = Column(DateTime, default=None)
    end_time = Column(DateTime, default=None)
    status = Column(String(50), default='settled')                # draft=已计算 pushed=已推送 agreed=已同意 settled=已入账 disputed=有异议 cancelled=作废 failed=入账失败
    source = Column(String(50), default='external')               # 来源：external=外部清单推送 manual=手动扣费 history=快照自动扣费
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
    item_type = Column(String(20), default='quantity')           # quantity 数量型 / model 型号型（分组，子型号为独立数量型计费项）
    parent_key = Column(String(50), default=None)                # 父计费项标识（型号型分组下的子型号），NULL=顶级
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
    unit = Column(String(50), default='')                        # 单位快照（如 元/GB/月）
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


# Pod 资源占用历史（任务历史占用资源统计）
# 数据由外部采集程序写入（如公司内网 AI 库的 pod_info_history_v2），平台侧只读，用于计费/统计
class PodInfoHistoryV2(Model, MyappModelBase):
    __tablename__ = 'pod_info_history_v2'
    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 唯一主键ID
    username = Column(String(255), default=None)              # 提交任务的用户名
    k8s_namespace = Column(String(255), default=None)          # k8s命名空间
    pod_uid = Column(String(255), default=None)                # Pod的唯一UID
    pod_name = Column(String(255), default=None)               # Pod的任务名称 (pod name)
    status = Column(String(255), default=None)                 # Pod的运行状态 (e.g., Running, Pending, Succeeded)
    node_name = Column(String(255), default=None)              # Pod运行所在的节点名称
    machine_ip = Column(String(255), default=None)             # 节点IP
    pod_ip = Column(String(255), default=None)                 # Pod的IP地址
    cluster = Column(String(100), default=None)                # 集群信息
    mem_usage_gb = Column(Float, default=None)                 # Pod当前内存使用量 (单位: GB)
    cpu_usage = Column(Float, default=None)                    # Pod当前CPU使用量 (单位: cores)
    gpu_mem_usage_gb = Column(Float, default=None)             # Pod当前GPU显存使用量 (单位: GB)
    gpu_usage = Column(Float, default=None)                    # Pod当前GPU使用率 (百分比)
    mem_limit_gb = Column(Float, default=None)                 # Pod的内存限制 (单位: GB)
    cpu_limit = Column(Float, default=None)                    # Pod的CPU限制 (单位: cores)
    created_at = Column(DateTime, default=None)                # Pod的创建时间戳
    label = Column(String(255), default=None)                  # Pod的标签
    duration = Column(String(255), default=None)               # 任务运行总耗时
    gpu_type = Column(String(255), default=None)               # GPU显卡型号 (e.g., A100, V100)
    tf32 = Column(String(255), default=None)                   # 是否启用TF32 (e.g., "True", "False")
    gpu_mem_util = Column(String(255), default=None)           # GPU显存的实际使用率 (百分比)
    gpu_util = Column(String(255), default=None)               # GPU核心的实际使用率 (百分比)
    conversion_rate = Column(String(255), default=None)        # 业务相关的转化率指标
    pending_at = Column(DateTime, default=None)                # 任务进入Pending状态的时间
    pending_message = Column(Text, default=None)               # 任务Pending或Waiting的原因
    waiting_time = Column(String(255), default=None)           # pending时长
    update_at = Column(DateTime, default=None)                 # 更新时间戳
    details = Column(Text, default=None)                       # 详情
    # 扣费状态（指针只写在最新快照行上；读取用 MAX 兜底，新增快照行不会丢失指针）
    billed_duration = Column(Float, default=None)              # 该任务累计已扣费时长（小时）
    billed_count = Column(Integer, default=0)                  # 已扣费次数
    last_billed_at = Column(DateTime, default=None)            # 上次扣费时间

    def __repr__(self):
        return '%s:%s' % (self.pod_name, self.status)


# 节点信息表（外部维护，如公司内网 AI 库的 all_node_memory）
# 通过 node_name 与 pod_info_history_v2.node_name 关联，查询节点显卡型号 gpu_type
# gpu_type 为 NULL 表示 CPU 节点（无显卡），只收 CPU/内存费用
class AllNodeMemory(Model, MyappModelBase):
    __tablename__ = 'all_node_memory'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    node_name = Column(String(255), unique=True, default=None)   # 节点名称（关联键）
    gpu_type = Column(String(100), default=None)                 # 显卡型号 (e.g., A100, L20, V100)；NULL=CPU节点
    gpu_num = Column(Integer, default=0)                         # 节点显卡数量
    updated_at = Column(DateTime, default=None)                  # 更新时间

    def __repr__(self):
        return '%s:%s' % (self.node_name, self.gpu_type or 'CPU')


# 扣费批次：一次执行生成一个批次，记录统计结果
class BillingRun(Model, MyappModelBase):
    __tablename__ = 'billing_run'
    id = Column(Integer, primary_key=True)
    execute_type = Column(String(20), default='manual')           # manual 手动 / scheduled 定时
    operator = Column(String(100), default='')                    # 执行人
    generated_count = Column(Integer, default=0)                  # 生成扣费单数
    skipped_no_delta = Column(Integer, default=0)                 # 跳过：增量=0（已扣过）
    skipped_not_running = Column(Integer, default=0)              # 跳过：非 Running
    skipped_below_min = Column(Integer, default=0)                # 跳过：未达最低付费时长
    skipped_whitelist = Column(Integer, default=0)                # 跳过：命中白名单
    skipped_no_user = Column(Integer, default=0)                  # 跳过：用户名对不上平台账号
    skipped_fallback_gpu = Column(Integer, default=0)             # 显卡型号走了 L20 兜底的数量
    remark = Column(String(500), default='')                      # 备注
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)

    def __repr__(self):
        return '%s:%s:%s' % (self.id, self.execute_type, self.generated_count)


# 扣费单质疑记录：用户质疑 → 管理员处理（改价/驳回/作废）
class BillDispute(Model, MyappModelBase):
    __tablename__ = 'bill_dispute'
    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey('bill.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True, default=None)  # 质疑用户
    reason = Column(Text, default='')                             # 质疑理由
    status = Column(String(20), default='open')                   # open 待处理 / processed 已处理
    resolution = Column(String(20), default='')                   # adjust 改价 / reject 驳回 / cancel 作废
    resolution_note = Column(Text, default='')                    # 处理意见
    operator = Column(String(100), default='')                    # 处理人
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)
    processed_on = Column(DateTime, default=None)

    def __repr__(self):
        return '%s:%s' % (self.bill_id, self.status)


# 扣费白名单：维度 org 部门 / user 用户 / cluster 集群
class BillWhitelist(Model, MyappModelBase):
    __tablename__ = 'bill_whitelist'
    id = Column(Integer, primary_key=True)
    dimension = Column(String(20), nullable=False)                # org 部门 / user 用户 / cluster 集群
    value = Column(String(200), nullable=False)                   # 白名单值（部门名/用户名/集群名）
    note = Column(String(200), default='')                        # 备注
    enabled = Column(Integer, default=1)                          # 1 启用 / 0 停用
    created_by = Column(String(100), default='')
    created_on = Column(DateTime, default=datetime.datetime.now, nullable=False)
    __table_args__ = (UniqueConstraint('dimension', 'value', name='uq_whitelist_dim_value'),)

    def __repr__(self):
        return '%s:%s' % (self.dimension, self.value)


# 扣费规则配置（key-value）
class BillingConfig(Model, MyappModelBase):
    __tablename__ = 'billing_config'
    id = Column(Integer, primary_key=True)
    cfg_key = Column(String(50), nullable=False, unique=True)     # min_duration_minutes / month_hours / auto_settle_days / gpu_fallback / enabled
    cfg_value = Column(String(200), default='')
    cfg_desc = Column(String(200), default='')
    updated_by = Column(String(100), default='')
    updated_on = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

    def __repr__(self):
        return '%s:%s' % (self.cfg_key, self.cfg_value)
