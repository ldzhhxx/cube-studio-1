# -*- coding: utf-8 -*-
"""快照自动扣费引擎（数据源：pod_info_history_v2 + all_node_memory）

一轮扣费 = run_deduct()：
  遍历所有 pod_uid → 锁定最新快照行（FOR UPDATE 防并发重复扣）
  → 过滤（Running / 最低时长 / 白名单 / 用户匹配）
  → JOIN all_node_memory 取显卡型号（NULL=CPU 节点不收 GPU 费；查不到按 gpu_fallback 兜底）
  → 增量结算（最新 duration − billed_duration）→ 生成/更新 draft 扣费单
  → 同一事务写入扣费指针（最新行的 billed_duration/billed_count/last_billed_at）

指针规则（挂在 pod_info_history_v2 上）：
  - 写：只写"最新快照行"（update_at / id 最大）
  - 读：MAX(billed_duration) 兜底——扫描器新增快照行（NULL）不会丢失指针
  - 作废回退：rollback_billed() 把 billed_duration 退到该单起点

结算 = settle_bill()：agreed → settled，钱包扣款 + consume 流水（幂等，不动指针）
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


def all_pod_uids():
    """全部有快照的 pod_uid（去重）"""
    rows = db.session.query(PodInfoHistoryV2.pod_uid).distinct().all()
    return [r[0] for r in rows if r[0]]


def latest_snapshot(pod_uid, for_update=False):
    """某任务的最新快照行（update_at / id 最大）。
    for_update=True 时加行锁，防并发重复扣费"""
    q = db.session.query(PodInfoHistoryV2).filter_by(pod_uid=pod_uid).order_by(
        PodInfoHistoryV2.update_at.desc(), PodInfoHistoryV2.id.desc())
    if for_update:
        q = q.with_for_update()
    return q.first()


def rollback_billed(pod_uid, deduct_from_hours):
    """作废扣费单时回退指针：billed_duration 回到该单起点。
    若该 pod 还有计费终点更大的生效单，则回退到最大终点（不破坏已生效区间）"""
    if not pod_uid:
        return
    remain = db.session.query(db.func.max(Bill.deduct_to_hours)).filter(
        Bill.pod_uid == pod_uid,
        Bill.status.notin_(('draft', 'cancelled', 'failed'))).scalar() or 0
    target = max(float(remain), float(deduct_from_hours or 0))
    snap = latest_snapshot(pod_uid)
    if not snap:
        return
    snap.billed_duration = target
    snap.billed_count = max(0, (snap.billed_count or 0) - 1)


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
    """计算主体：逐 pod 锁定最新行计算（FOR UPDATE），再统一写入，单事务"""
    from myapp.views.view_billing import calc_resources, _write_bill_items

    whitelist = build_whitelist()
    gpu_parent = get_gpu_parent()
    min_duration_hours = get_config_float('min_duration_minutes', 10) / 60.0

    computed = []       # (bill_data, 锁定的快照行) 待写入
    errors = []
    for pod_uid in all_pod_uids():
        try:
            data = _compute_pod(pod_uid, whitelist, gpu_parent, min_duration_hours)
        except _Skip as sk:
            counter = _SKIP_COUNTERS.get(sk.reason)
            if counter:
                setattr(run, counter, (getattr(run, counter) or 0) + 1)
            continue
        except Exception as e:
            logger.warning('billing deduct pod %s error: %s' % (pod_uid, e))
            errors.append('%s:%s' % (str(pod_uid)[:20], str(e)[:60]))
            continue
        computed.append(data)
        if data['_bill_data'].get('gpu_fallback'):
            run.skipped_fallback_gpu = (run.skipped_fallback_gpu or 0) + 1

    # 统一写入：生成/更新 draft 单（同 pod 的旧 draft 直接更新，不重复建单）+ 写扣费指针
    for data in computed:
        bill_data, snap = data['_bill_data'], data['_snapshot']
        bill = db.session.query(Bill).filter_by(
            pod_uid=bill_data['pod_uid'], source='history', status='draft').first()
        if not bill:
            bill = Bill(pod_uid=bill_data['pod_uid'], source='history', status='draft')
        for k, v in bill_data.items():
            if k in ('calc_items', 'gpu_fallback'):
                continue
            setattr(bill, k, v)
        bill.billing_run_id = run.id
        bill.updated_on = datetime.datetime.now()
        db.session.add(bill)
        db.session.flush()
        _write_bill_items(bill.id, bill_data['calc_items'])
        # 写扣费指针（最新快照行，计算阶段已加锁）
        if snap is not None:
            snap.billed_duration = bill_data['deduct_to_hours']
            snap.billed_count = (snap.billed_count or 0) + 1
            snap.last_billed_at = datetime.datetime.now()

    run.generated_count = len(computed)
    if errors:
        run.remark = ((run.remark or '') + '; 异常pod: ' + '; '.join(errors))[:500]


def _compute_pod(pod_uid, whitelist, gpu_parent, min_duration_hours):
    """单个 pod 计算：锁定最新快照行 → 过滤 → 增量 → 金额。
    返回 {'_bill_data': bill_data, '_snapshot': snap}；跳过抛 _Skip"""
    # 行锁：并发执行扣费时，第二个事务会阻塞到这里，看到已更新的 billed_duration 后增量=0 跳过
    snap = latest_snapshot(pod_uid, for_update=True)
    if snap is None:
        raise _Skip('not_running')

    # 1. Running 过滤
    if (snap.status or '') != 'Running':
        raise _Skip('not_running')

    # 2. 时长解析 + 最低付费时长
    try:
        duration = float(str(snap.duration or '').strip())
    except Exception:
        duration = 0
    if duration <= 0 or duration < min_duration_hours:
        raise _Skip('below_min')

    # 3. 用户匹配（白名单需要 org）
    user = get_user_by_username(snap.username)
    if not user:
        raise _Skip('no_user')

    # 4. 白名单（user / org / cluster 任一命中即跳过）
    if is_whitelisted(whitelist, user.username, user.org, snap.cluster):
        raise _Skip('whitelist')

    # 5. 显卡型号（NULL=CPU 节点不收 GPU 费；查不到兜底）
    gpu_model, fallback = get_gpu_type(snap.node_name)
    try:
        gpu_num = float(snap.gpu_usage or 0) / 100.0
    except Exception:
        gpu_num = 0.0

    # 6. 增量结算：最新 duration − 已扣时长（指针就在最新行上）
    #    注意 billed_duration 存 MySQL float 列（float32），duration 是 varchar 解析（float64），
    #    直接相减有 1e-5 级误差，归整到 4 位小数（0.0001h=0.36s）避免"幽灵增量"重复计费
    billed_to = float(snap.billed_duration or 0)
    delta = round(duration - billed_to, 4)
    if delta <= 0:
        raise _Skip('no_delta')

    # 7. 资源与金额（复用前端算价逻辑：Σ 数量 × 月单价 × 时长/720h）
    resources = []
    if snap.cpu_limit and float(snap.cpu_limit) > 0:
        resources.append({'item_key': 'cpu', 'quantity': float(snap.cpu_limit)})
    if snap.mem_limit_gb and float(snap.mem_limit_gb) > 0:
        resources.append({'item_key': 'memory', 'quantity': float(snap.mem_limit_gb)})
    if gpu_num > 0 and gpu_model and gpu_parent:
        if get_gpu_child(gpu_parent, gpu_model):
            resources.append({'item_key': gpu_parent.item_key, 'option_key': gpu_model, 'quantity': gpu_num})
        else:
            fallback = True   # 型号未配置价格：GPU 部分跳过，按兜底口径记录
    from myapp.views.view_billing import calc_resources
    calc_items, amount_fen = calc_resources(resources, int(round(delta * 3600)))
    if amount_fen <= 0:
        raise _Skip('amount_zero')

    bill_data = {
        'pod_uid': snap.pod_uid,
        'pod_name': snap.pod_name,
        'namespace': snap.k8s_namespace or '',
        'task_name': snap.pod_name or '',
        'username': user.username,
        'user_id': user.id,
        'org': user.org or '',
        'cpu': float(snap.cpu_limit or 0),
        'memory': float(snap.mem_limit_gb or 0),
        'gpu_num': gpu_num,
        'gpu_type': gpu_model or '',
        'gpu_memory': float(snap.gpu_mem_usage_gb or 0),
        'duration_seconds': int(round(delta * 3600)),
        'amount_fen': amount_fen,
        'deduct_from_hours': billed_to,
        'deduct_to_hours': duration,
        'start_time': snap.created_at,
        'end_time': snap.update_at,
        'calc_items': calc_items,
        'gpu_fallback': bool(fallback),
    }
    return {'_bill_data': bill_data, '_snapshot': snap}


# ============================================================
# 结算与超时自动扣费
# ============================================================
def settle_bill(bill, operator=''):
    """扣费单入账：agreed → settled，钱包扣款 + consume 流水。
    幂等：已 settled 直接返回 False；user_id 为空只记账不扣款。不动扣费指针"""
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


def cancel_bill(bill, operator=''):
    """作废扣费单（draft/pushed/disputed）：状态置 cancelled + 回退扣费指针"""
    if not bill:
        return False
    if bill.status == 'settled':
        raise ValueError('已入账的扣费单不能作废，请走冲正流程')
    if bill.status == 'cancelled':
        return False
    rollback_billed(bill.pod_uid, bill.deduct_from_hours)
    bill.status = 'cancelled'
    bill.updated_on = datetime.datetime.now()
    db.session.commit()
    return True


def find_bill(bill_id):
    return db.session.query(Bill).filter_by(id=bill_id).first()
