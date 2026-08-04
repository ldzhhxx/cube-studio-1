# -*- coding: utf-8 -*-
"""快照自动扣费引擎（数据源：pod_info_history_v2 + all_node_memory）

一轮扣费 = run_deduct()：
  遍历所有 pod 的最新快照 → 过滤（Running / 最低时长 / 白名单 / 用户匹配）
  → JOIN all_node_memory 取显卡型号（NULL=CPU 节点不收 GPU 费；查不到按 gpu_fallback 兜底）
  → 增量结算（最新 duration − 上次已扣时长）→ 生成/更新 draft 扣费单

结算 = settle_bill()：agreed → settled，钱包扣款 + consume 流水（幂等）
超时自动扣费 = auto_settle_scan()：pushed 超过 auto_settle_days 天未处理 → 自动同意并入账

规则配置见 billing_config 表（min_duration_minutes / month_hours / auto_settle_days / gpu_fallback / enabled）
"""
import datetime
import logging

from sqlalchemy import and_, or_

from myapp import db
from myapp.models.model_billing import (Bill, Wallet, AccountLog, PriceConfig, BillingRun,
                                        BillWhitelist, BillingConfig,
                                        PodInfoHistoryV2, AllNodeMemory)

logger = logging.getLogger(__name__)


# ============================================================
# 配置与白名单
# ============================================================
def get_config(key, default=None):
    row = db.session.query(BillingConfig).filter_by(cfg_key=key).first()
    if not row:
        return default
    return row.cfg_value


def get_config_int(key, default):
    try:
        return int(float(str(get_config(key, default) or default)))
    except Exception:
        return default


def get_config_float(key, default):
    try:
        return float(str(get_config(key, default) or default))
    except Exception:
        return default


def build_whitelist():
    """白名单：org 部门 / user 用户 / cluster 集群 三个维度"""
    wl = {'org': set(), 'user': set(), 'cluster': set()}
    rows = db.session.query(BillWhitelist).filter_by(enabled=1).all()
    for r in rows:
        if r.dimension in wl:
            wl[r.dimension].add((r.value or '').strip())
    return wl


def is_whitelisted(wl, username, org, cluster):
    return ((username or '') in wl['user']
            or (org or '') in wl['org']
            or (cluster or '') in wl['cluster'])


# ============================================================
# 基础查询
# ============================================================
def get_user_by_username(username):
    from myapp.security import MyUser
    if not username:
        return None
    return db.session.query(MyUser).filter_by(username=username).first()


def get_gpu_parent():
    """GPU 型号型分组父项（不写死 gpu，按实际配置找）"""
    return db.session.query(PriceConfig).filter(
        PriceConfig.item_type == 'model', PriceConfig.parent_key.is_(None)).first()


def get_gpu_child(parent, model):
    """型号 → 型号计费子项（如 L20 → gpu_l20）；未配置价格返回 None"""
    if not parent or not model:
        return None
    return (db.session.query(PriceConfig).filter(
        PriceConfig.parent_key == parent.item_key,
        or_(PriceConfig.item_name == model, PriceConfig.item_key == model)).first()
        or db.session.query(PriceConfig).filter(
            PriceConfig.parent_key == parent.item_key,
            PriceConfig.item_key == ('gpu_%s' % str(model).lower())).first())


def get_gpu_type(node_name):
    """node_name → 显卡型号。
    返回 (型号 or None, 是否兜底)：None=CPU 节点（不收 GPU 费）；节点查不到 → gpu_fallback 兜底"""
    row = None
    if node_name:
        row = db.session.query(AllNodeMemory).filter_by(node_name=node_name).first()
    if row is not None and row.gpu_type:
        return row.gpu_type, False
    if row is not None:
        return None, False          # 节点存在但 gpu_type 为 NULL：CPU 节点
    return get_config('gpu_fallback', 'L20'), True   # 节点查不到：兜底


def _all_latest_snapshots():
    """所有 pod 的最新快照（每个 pod_uid 一条，按 update_at 取最大）"""
    sub = db.session.query(
        PodInfoHistoryV2.pod_uid,
        db.func.max(PodInfoHistoryV2.update_at).label('max_update'),
    ).group_by(PodInfoHistoryV2.pod_uid).subquery()
    snaps = db.session.query(PodInfoHistoryV2).join(
        sub, and_(PodInfoHistoryV2.pod_uid == sub.c.pod_uid,
                  PodInfoHistoryV2.update_at == sub.c.max_update)).all()
    # 同 pod 同 update_at 取 id 最大的一条
    seen = {}
    for s in snaps:
        old = seen.get(s.pod_uid)
        if old is None or s.id > old.id:
            seen[s.pod_uid] = s
    return list(seen.values())


def billed_to_hours(pod_uid):
    """该任务已计费到的时长（小时）：取已生效扣费单的最大 deduct_to_hours。
    draft（未推送）/cancelled（作废）/failed（失败）不占用指针"""
    if not pod_uid:
        return 0
    row = db.session.query(db.func.max(Bill.deduct_to_hours)).filter(
        Bill.pod_uid == pod_uid,
        Bill.status.notin_(('draft', 'cancelled', 'failed'))).first()
    return row[0] or 0


# ============================================================
# 一轮扣费
# ============================================================
class _Skip(Exception):
    """跳过标志：reason ∈ not_running / below_min / no_user / whitelist / no_delta / amount_zero"""
    def __init__(self, reason):
        self.reason = reason


# 跳过原因 → 批次统计字段
_SKIP_COUNTERS = {
    'not_running': 'skipped_not_running',
    'below_min': 'skipped_below_min',
    'no_user': 'skipped_no_user',
    'whitelist': 'skipped_whitelist',
    'no_delta': 'skipped_no_delta',
    'amount_zero': 'skipped_below_min',
}


def run_deduct(operator='', execute_type='manual', remark=''):
    """执行一轮扣费，返回 BillingRun 批次。
    幂等：重复执行时增量=0 全部跳过，不产生新单"""
    if get_config_int('enabled', 1) != 1:
        raise ValueError('扣费功能已关闭（billing_config.enabled=0）')
    run = BillingRun(execute_type=execute_type, operator=operator or '', remark=remark or '')
    db.session.add(run)
    db.session.flush()
    try:
        _run_engine(run)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return run


def _run_engine(run):
    """计算主体：先纯计算（不落库），再统一写入，单事务 + 单 pod 出错不影响整批"""
    from myapp.views.view_billing import calc_resources, _write_bill_items

    whitelist = build_whitelist()
    gpu_parent = get_gpu_parent()
    min_duration_hours = get_config_float('min_duration_minutes', 10) / 60.0
    snaps = _all_latest_snapshots()

    computed = []       # 待写入的 bill_data
    errors = []
    for s in snaps:
        try:
            data = _compute_pod(s, whitelist, gpu_parent, min_duration_hours)
        except _Skip as sk:
            counter = _SKIP_COUNTERS.get(sk.reason)
            if counter:
                setattr(run, counter, (getattr(run, counter) or 0) + 1)
            continue
        except Exception as e:
            logger.warning('billing deduct pod %s(%s) error: %s' % (s.pod_uid, s.pod_name, e))
            errors.append('%s:%s' % (s.pod_name, str(e)[:60]))
            continue
        computed.append(data)
        if data.get('gpu_fallback'):
            run.skipped_fallback_gpu = (run.skipped_fallback_gpu or 0) + 1

    # 统一写入：生成/更新 draft 单（同 pod 的旧 draft 直接更新，不重复建单）
    for data in computed:
        bill = db.session.query(Bill).filter_by(
            pod_uid=data['pod_uid'], source='history', status='draft').first()
        if not bill:
            bill = Bill(pod_uid=data['pod_uid'], source='history', status='draft')
        for k, v in data.items():
            if k in ('calc_items', 'gpu_fallback'):
                continue
            setattr(bill, k, v)
        bill.billing_run_id = run.id
        bill.updated_on = datetime.datetime.now()
        db.session.add(bill)
        db.session.flush()
        _write_bill_items(bill.id, data['calc_items'])

    run.generated_count = len(computed)
    if errors:
        run.remark = ((run.remark or '') + '; 异常pod: ' + '; '.join(errors))[:500]


def _compute_pod(s, whitelist, gpu_parent, min_duration_hours):
    """单个 pod 计算（纯读，不写库）。返回 bill_data dict；跳过抛 _Skip"""
    # 1. Running 过滤
    if (s.status or '') != 'Running':
        raise _Skip('not_running')

    # 2. 时长解析 + 最低付费时长
    try:
        duration = float(str(s.duration or '').strip())
    except Exception:
        duration = 0
    if duration <= 0 or duration < min_duration_hours:
        raise _Skip('below_min')

    # 3. 用户匹配（白名单需要 org）
    user = get_user_by_username(s.username)
    if not user:
        raise _Skip('no_user')

    # 4. 白名单（user / org / cluster 任一命中即跳过）
    if is_whitelisted(whitelist, user.username, user.org, s.cluster):
        raise _Skip('whitelist')

    # 5. 显卡型号（NULL=CPU 节点不收 GPU 费；查不到兜底）
    gpu_model, fallback = get_gpu_type(s.node_name)
    try:
        gpu_num = float(s.gpu_usage or 0) / 100.0
    except Exception:
        gpu_num = 0.0

    # 6. 增量结算：最新 duration − 上次已扣时长
    # 注意：billed_to 来自 MySQL float 列（float32），duration 来自 varchar 解析（float64），
    # 直接相减会有 1e-5 级误差，需归整到 4 位小数（0.0001h=0.36s）避免"幽灵增量"重复计费
    billed_to = billed_to_hours(s.pod_uid)
    delta = round(duration - billed_to, 4)
    if delta <= 0:
        raise _Skip('no_delta')

    # 7. 资源与金额（复用前端算价逻辑：Σ 数量 × 月单价 × 时长/720h）
    resources = []
    if s.cpu_limit and float(s.cpu_limit) > 0:
        resources.append({'item_key': 'cpu', 'quantity': float(s.cpu_limit)})
    if s.mem_limit_gb and float(s.mem_limit_gb) > 0:
        resources.append({'item_key': 'memory', 'quantity': float(s.mem_limit_gb)})
    if gpu_num > 0 and gpu_model and gpu_parent:
        if get_gpu_child(gpu_parent, gpu_model):
            resources.append({'item_key': gpu_parent.item_key, 'option_key': gpu_model, 'quantity': gpu_num})
        else:
            fallback = True   # 型号未配置价格：GPU 部分跳过，按兜底口径记录
    from myapp.views.view_billing import calc_resources
    calc_items, amount_fen = calc_resources(resources, int(round(delta * 3600)))
    if amount_fen <= 0:
        raise _Skip('amount_zero')

    return {
        'pod_uid': s.pod_uid,
        'pod_name': s.pod_name,
        'namespace': s.k8s_namespace or '',
        'task_name': s.pod_name or '',
        'username': user.username,
        'user_id': user.id,
        'org': user.org or '',
        'cpu': float(s.cpu_limit or 0),
        'memory': float(s.mem_limit_gb or 0),
        'gpu_num': gpu_num,
        'gpu_type': gpu_model or '',
        'gpu_memory': float(s.gpu_mem_usage_gb or 0),
        'duration_seconds': int(round(delta * 3600)),
        'amount_fen': amount_fen,
        'deduct_from_hours': billed_to,
        'deduct_to_hours': duration,
        'start_time': s.created_at,
        'end_time': s.update_at,
        'calc_items': calc_items,
        'gpu_fallback': bool(fallback),
    }


# ============================================================
# 结算与超时自动扣费
# ============================================================
def settle_bill(bill, operator=''):
    """扣费单入账：agreed → settled，钱包扣款 + consume 流水。
    幂等：已 settled 直接返回 False；user_id 为空只记账不扣款"""
    if not bill:
        return False
    if bill.status == 'settled':
        return False
    if bill.status not in ('agreed',):
        raise ValueError('bill %s status=%s 不能入账' % (bill.id, bill.status))
    user_id = bill.user_id
    if user_id and bill.amount_fen and bill.amount_fen > 0:
        wallet = db.session.query(Wallet).filter_by(user_id=user_id).with_for_update().first()
        if not wallet:
            wallet = Wallet(user_id=user_id, balance_fen=0)
            db.session.add(wallet)
            db.session.flush()
        before = wallet.balance_fen
        wallet.balance_fen -= bill.amount_fen
        db.session.add(AccountLog(
            type='consume',
            from_user_id=user_id,
            amount_fen=bill.amount_fen,
            balance_before_fen=before,
            balance_after_fen=wallet.balance_fen,
            bill_id=bill.id,
            operator=operator or 'history',
            remark='快照扣费单结算',
        ))
    bill.status = 'settled'
    bill.updated_on = datetime.datetime.now()
    db.session.commit()
    return True


def auto_settle_scan():
    """pushed 超过 auto_settle_days 天未处理 → 自动同意并入账，返回处理条数"""
    days = get_config_int('auto_settle_days', 7)
    deadline = datetime.datetime.now() - datetime.timedelta(days=days)
    bills = db.session.query(Bill).filter(
        Bill.status == 'pushed', Bill.updated_on < deadline).all()
    count = 0
    for b in bills:
        try:
            b.status = 'agreed'          # 超时未处理视为自动同意
            b.updated_on = datetime.datetime.now()
            db.session.flush()
            settle_bill(b, operator='auto_settle')
            count += 1
        except Exception as e:
            logger.warning('auto settle bill %s error: %s' % (b.id, e))
            db.session.rollback()
    return count


def find_bill(bill_id):
    return db.session.query(Bill).filter_by(id=bill_id).first()
