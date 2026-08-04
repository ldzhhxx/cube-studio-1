# 计费系统视图层
# 对外接口（外部费用清单推送）：
#   POST /billing/api/push        外部推送费用明细（X-Billing-Token 鉴权），平台记账扣费
#   GET  /billing/api/list        对账：外部查询平台入账状态（token 或管理员）
# 管理操作（管理员或 token）：
#   POST /billing/api/recharge    给用户充值
#   POST /billing/api/transfer    把用户A的钱转给用户B（双向流水）
# 用户查询（会话登录）：
#   GET  /billing/api/my_balance  我的余额
#   GET  /billing/api/my_bills    我的费用明细
#   GET  /billing/api/my_logs     我的资金流水
# 管理页面（自研现代控制台，iframe 菜单）：
#   /billing/console    计费控制台（自包含 HTML，不走 FAB）
# 管理端数据接口（管理员会话或 token）：
#   GET /billing/api/admin/stats     汇总统计
#   GET /billing/api/admin/wallets   全部用户余额
#   GET /billing/api/admin/bills     全部费用明细
#   GET /billing/api/admin/logs      全部资金流水
import datetime
from flask import request, g, flash, redirect, jsonify, send_from_directory, Response
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError

from myapp import app, appbuilder, db, conf
from myapp.models.model_billing import (Bill, Wallet, AccountLog, PriceConfig, ItemPriceDetail, BillItem,
                                        BillingRun, BillDispute, BillWhitelist, BillingConfig,
                                        PodInfoHistoryV2, AllNodeMemory)
from myapp.security import MyUser

logging = app.logger


def get_user_by_username(username):
    if not username:
        return None
    return db.session.query(MyUser).filter_by(username=username).first()


def get_or_create_wallet(user_id):
    wallet = db.session.query(Wallet).filter_by(user_id=user_id).first()
    if not wallet:
        wallet = Wallet(user_id=user_id, balance_fen=0)
        db.session.add(wallet)
        db.session.flush()
    return wallet


def check_billing_token():
    token = conf.get('BILLING_TOKEN', '')
    return bool(token) and request.headers.get('X-Billing-Token', '') == token


def check_admin_user():
    if not g.user or not getattr(g.user, 'is_admin', lambda: False)():
        return False
    return True


def check_admin_or_token():
    return check_billing_token() or check_admin_user()


def current_operator():
    try:
        return g.user.username if g.user.is_authenticated else 'token'
    except Exception:
        return 'token'


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        try:
            return datetime.datetime.strptime(str(value)[:10], '%Y-%m-%d')
        except Exception:
            return None


def billing_menu_items():
    """计费中心顶级菜单（自包含，不依赖 home.py 的任何变量）。
    供 home.py 融合：只需在 return jsonify(menu) 前调用 menu.insert(0, billing_menu_items())。"""
    billing = {
        "name": 'billing',
        "title": '计费中心',
        "isMenu": True,
        "isExpand": True,
        "icon": '<svg class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="128" height="128"><path d="M912 320h-144v-48c0-84.8-67.2-152-152-152h-208C323.2 120 256 187.2 256 272v48H112c-17.6 0-32 14.4-32 32v448c0 88 72 160 160 160h544c88 0 160-72 160-160V352c0-17.6-14.4-32-32-32zM320 272c0-48 32-80 80-80h208c48 0 80 32 80 80v48H320v-48z m592 448c0 56-40 96-96 96H272c-56 0-96-40-96-96V384h736v336z m-368-80c-48 0-88-40-88-88s40-88 88-88 88 40 88 88-40 88-88 88z" p-id="billing"></path></svg>',
        "children": [
            {
                "name": 'billing-my',
                "title": '我的账单',
                "menu_type": "iframe",
                "url": '/billing/my',
            },
        ],
    }
    try:
        # 管理员另有"计费控制台"子项
        if g.user and g.user.is_authenticated and g.user.username in conf.get('ADMIN_USER', '').split(','):
            billing['children'].insert(0, {
                "name": 'billing-console',
                "title": '计费控制台',
                "menu_type": "iframe",
                "url": '/billing/console',
            })
    except Exception as e:
        logging.warning('billing menu admin check error: %s' % e)
    return billing


def err_response(msg, status=400):
    return jsonify({'message': msg, 'result': None, 'status': status}), status


def ok_response(result=None, message='ok'):
    return jsonify({'message': message, 'result': result, 'status': 200})


def require_json_content():
    """CSRF 防护：写操作必须携带 application/json（浏览器跨站表单无法伪造该头）"""
    ctype = (request.headers.get('Content-Type', '') or '').split(';')[0].strip().lower()
    return ctype == 'application/json'


MAX_TRANSFER_FEN = 100 * 10000 * 100  # 单笔金额上限 100 万元（分）


def safe_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def safe_float(value, default=0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def lock_wallet(user_id):
    """行锁获取钱包（并发安全），不存在则创建"""
    wallet = db.session.query(Wallet).filter_by(user_id=user_id).with_for_update().first()
    if not wallet:
        wallet = Wallet(user_id=user_id, balance_fen=0)
        db.session.add(wallet)
        db.session.flush()
    return wallet


# ============================================================
# 对外接口：外部费用清单推送 / 对账
# ============================================================
@app.route('/billing/api/push', methods=['POST'])
def billing_push():
    if not check_billing_token():
        return err_response('invalid billing token', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True)
    if not data:
        return err_response('empty json body')
    if isinstance(data, dict):
        data = [data]
    results = []
    for item in data:
        # 逐笔容错：一条坏数据不影响整批
        try:
            pod_name = str(item.get('pod_name', '') or '').strip()
            if not pod_name:
                results.append({'pod_name': '', 'result': 'skip'})
                continue
            username = str(item.get('username', '') or '').strip()
            amount_fen = safe_int(item.get('amount_fen'))
            # 商用校验：金额必须为非负整数，且不超过单笔上限
            if amount_fen < 0 or amount_fen > MAX_TRANSFER_FEN:
                results.append({'pod_name': pod_name, 'result': 'reject', 'reason': 'amount_fen must be 0~%s' % MAX_TRANSFER_FEN})
                continue
            user = get_user_by_username(username)
            user_id = user.id if user else None
            org = user.org if user else str(item.get('org', '') or '').strip()
            bill_fields = dict(
                task_name=str(item.get('task_name', '') or '')[:200],
                run_id=str(item.get('run_id', '') or '')[:200],
                namespace=str(item.get('namespace', '') or '').strip()[:200],
                username=username,
                user_id=user_id,
                org=org,
                cpu=safe_float(item.get('cpu')),
                memory=safe_float(item.get('memory')),
                gpu_num=safe_float(item.get('gpu_num')),
                gpu_type=str(item.get('gpu_type', '') or '').strip()[:50],
                gpu_memory=safe_float(item.get('gpu_memory')),
                duration_seconds=safe_int(item.get('duration_seconds')),
                amount_fen=amount_fen,
                start_time=parse_time(item.get('start_time')),
                end_time=parse_time(item.get('end_time')),
                source='external',
            )
            # 可选费用明细（展示用快照）：有 items 时按当前单价算价，金额仍以 amount_fen 为准
            calc_items = None
            if item.get('items'):
                calc_items, _ = calc_resources(item['items'], safe_int(item.get('duration_seconds')))
            bill = db.session.query(Bill).filter_by(pod_name=pod_name).first()
            if bill:
                # 重复推送：修正数据；金额变化时结算差额（补扣/退回），不重复扣全额
                old_amount = bill.amount_fen or 0
                for k, v in bill_fields.items():
                    setattr(bill, k, v)
                bill.status = 'settled'
                if calc_items is not None:
                    _write_bill_items(bill.id, calc_items)  # 明细快照重建（幂等）
                diff = bill.amount_fen - old_amount
                if user_id and diff != 0 and bill.amount_fen > 0:
                    wallet = lock_wallet(user_id)
                    before = wallet.balance_fen
                    wallet.balance_fen -= diff  # diff>0 补扣；diff<0 退回
                    db.session.add(AccountLog(
                        type='consume' if diff > 0 else 'refund',
                        from_user_id=user_id,
                        amount_fen=abs(diff),
                        balance_before_fen=before,
                        balance_after_fen=wallet.balance_fen,
                        bill_id=bill.id,
                        operator='external',
                        remark='费用修正%s' % ('补扣' if diff > 0 else '退回'),
                    ))
                db.session.commit()
                results.append({'pod_name': pod_name, 'result': 'updated'})
                continue
            bill = Bill(pod_name=pod_name, status='settled', **bill_fields)
            db.session.add(bill)
            try:
                db.session.flush()
            except IntegrityError:
                # 并发同 pod 推送：按重复推送处理
                db.session.rollback()
                bill = db.session.query(Bill).filter_by(pod_name=pod_name).first()
                old_amount = bill.amount_fen or 0
                for k, v in bill_fields.items():
                    setattr(bill, k, v)
                if calc_items is not None:
                    _write_bill_items(bill.id, calc_items)  # 明细快照重建（幂等）
                diff = bill.amount_fen - old_amount
                if user_id and diff != 0 and bill.amount_fen > 0:
                    wallet = lock_wallet(user_id)
                    before = wallet.balance_fen
                    wallet.balance_fen -= diff
                    db.session.add(AccountLog(
                        type='consume' if diff > 0 else 'refund',
                        from_user_id=user_id,
                        amount_fen=abs(diff),
                        balance_before_fen=before,
                        balance_after_fen=wallet.balance_fen,
                        bill_id=bill.id,
                        operator='external',
                        remark='费用修正%s' % ('补扣' if diff > 0 else '退回'),
                    ))
                db.session.commit()
                results.append({'pod_name': pod_name, 'result': 'updated'})
                continue
            if calc_items is not None:
                _write_bill_items(bill.id, calc_items)  # 新账单明细快照
            if user_id and bill.amount_fen > 0:
                wallet = lock_wallet(user_id)
                before = wallet.balance_fen
                wallet.balance_fen -= bill.amount_fen
                db.session.add(AccountLog(
                    type='consume',
                    from_user_id=user_id,
                    amount_fen=bill.amount_fen,
                    balance_before_fen=before,
                    balance_after_fen=wallet.balance_fen,
                    bill_id=bill.id,
                    operator='external',
                    remark='费用清单推送扣费',
                ))
            db.session.commit()
            if user_id:
                results.append({'pod_name': pod_name, 'result': 'settled'})
            else:
                results.append({'pod_name': pod_name, 'result': 'settled_no_user'})
        except Exception as e:
            db.session.rollback()
            logging.warning('billing push item error: %s %s' % (pod_name, e))
            results.append({'pod_name': pod_name, 'result': 'error', 'reason': str(e)[:200]})
    return ok_response(results)


@app.route('/billing/api/list', methods=['GET', 'POST'])
def billing_list():
    # 对账接口：外部系统可查平台入账状态（token 鉴权），管理员也可查
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if request.method == 'POST':
        params = request.get_json(force=True, silent=True) or {}
    else:
        params = request.args.to_dict()
    query = db.session.query(Bill)
    if params.get('pod_name'):
        query = query.filter(Bill.pod_name.like('%%%s%%' % params['pod_name']))
    if params.get('username'):
        query = query.filter(Bill.username == params['username'])
    if params.get('task_name'):
        query = query.filter(Bill.task_name.like('%%%s%%' % params['task_name']))
    if params.get('start_time'):
        query = query.filter(Bill.created_on >= parse_time(params['start_time']))
    if params.get('end_time'):
        query = query.filter(Bill.created_on <= parse_time(params['end_time']))
    bills = query.order_by(Bill.id.desc()).limit(int(params.get('limit', 200))).all()
    result = [{
        'pod_name': b.pod_name,
        'task_name': b.task_name,
        'run_id': b.run_id,
        'username': b.username,
        'org': b.org,
        'cpu': b.cpu,
        'memory': b.memory,
        'gpu_num': b.gpu_num,
        'gpu_type': b.gpu_type or '',
        'gpu_memory': b.gpu_memory,
        'duration_seconds': b.duration_seconds,
        'amount_fen': b.amount_fen,
        'start_time': b.start_time.strftime('%Y-%m-%d %H:%M:%S') if b.start_time else '',
        'end_time': b.end_time.strftime('%Y-%m-%d %H:%M:%S') if b.end_time else '',
        'status': b.status,
        'created_on': b.created_on.strftime('%Y-%m-%d %H:%M:%S') if b.created_on else '',
    } for b in bills]
    return ok_response({'count': len(result), 'bills': result})


# ============================================================
# 管理操作：充值 / 转账
# ============================================================
@app.route('/billing/api/recharge', methods=['POST'])
def billing_recharge():
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get('username', '') or '').strip()
    amount_fen = safe_int(data.get('amount_fen'))
    remark = str(data.get('remark', '') or '')[:500]
    if not username or amount_fen <= 0:
        return err_response('username and positive amount_fen required')
    if amount_fen > MAX_TRANSFER_FEN:
        return err_response('amount_fen exceeds limit %s' % MAX_TRANSFER_FEN)
    user = get_user_by_username(username)
    if not user:
        return err_response('user %s not found' % username)
    wallet = lock_wallet(user.id)
    before = wallet.balance_fen
    wallet.balance_fen += amount_fen
    db.session.add(AccountLog(
        type='recharge',
        to_user_id=user.id,
        amount_fen=amount_fen,
        balance_before_fen=before,
        balance_after_fen=wallet.balance_fen,
        operator=current_operator(),
        remark=remark or '管理员充值',
    ))
    db.session.commit()
    return ok_response({'username': username, 'amount_fen': amount_fen, 'balance_fen': wallet.balance_fen})


@app.route('/billing/api/transfer', methods=['POST'])
def billing_transfer():
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    from_username = str(data.get('from_username', '') or '').strip()
    to_username = str(data.get('to_username', '') or '').strip()
    amount_fen = safe_int(data.get('amount_fen'))
    remark = str(data.get('remark', '') or '')[:500]
    if not from_username or not to_username or amount_fen <= 0:
        return err_response('from_username, to_username and positive amount_fen required')
    if amount_fen > MAX_TRANSFER_FEN:
        return err_response('amount_fen exceeds limit %s' % MAX_TRANSFER_FEN)
    if from_username == to_username:
        return err_response('from and to user must be different')
    from_user = get_user_by_username(from_username)
    to_user = get_user_by_username(to_username)
    if not from_user:
        return err_response('user %s not found' % from_username)
    if not to_user:
        return err_response('user %s not found' % to_username)
    # 按 user_id 升序加锁，避免死锁
    lock_ids = sorted([from_user.id, to_user.id])
    for uid in lock_ids:
        lock_wallet(uid)
    from_wallet = db.session.query(Wallet).filter_by(user_id=from_user.id).first()
    to_wallet = db.session.query(Wallet).filter_by(user_id=to_user.id).first()
    if from_wallet.balance_fen < amount_fen:
        return err_response('insufficient balance of %s' % from_username)
    operator = current_operator()
    from_before = from_wallet.balance_fen
    from_wallet.balance_fen -= amount_fen
    db.session.add(AccountLog(
        type='transfer_out',
        from_user_id=from_user.id,
        to_user_id=to_user.id,
        amount_fen=amount_fen,
        balance_before_fen=from_before,
        balance_after_fen=from_wallet.balance_fen,
        operator=operator,
        remark=remark or '管理员转账',
    ))
    to_before = to_wallet.balance_fen
    to_wallet.balance_fen += amount_fen
    db.session.add(AccountLog(
        type='transfer_in',
        from_user_id=from_user.id,
        to_user_id=to_user.id,
        amount_fen=amount_fen,
        balance_before_fen=to_before,
        balance_after_fen=to_wallet.balance_fen,
        operator=operator,
        remark=remark or '管理员转账',
    ))
    db.session.commit()
    return ok_response({
        'from_username': from_username, 'from_balance_fen': from_wallet.balance_fen,
        'to_username': to_username, 'to_balance_fen': to_wallet.balance_fen,
    })


def _do_deduct(item):
    """单笔手动扣费：resources 后端自动算价 → bill 账本 + bill_item 明细快照 + 扣钱包 + consume 流水
    兼容旧调用：无 resources 时沿用 amount_fen（旧字段 cpu/memory/gpu_num/gpu_type 自动转换）
    pod_name 选填（为空存 NULL，不自动生成）；namespace 选填"""
    username = str(item.get('username', '') or '').strip()
    remark = str(item.get('remark', '') or '')[:500]
    task_name = str(item.get('task_name', '') or '')[:200]
    namespace = str(item.get('namespace', '') or '').strip()[:200]
    pod_name = str(item.get('pod_name', '') or '').strip() or None  # 选填：为空存 NULL，不自动生成
    duration_seconds = safe_int(item.get('duration_seconds'))
    resources = item.get('resources')
    # 旧字段兼容：cpu/memory/gpu_num/gpu_type → resources（GPU 父项按实际 model 型分组查找）
    if not resources and (item.get('cpu') or item.get('memory') or item.get('gpu_num')):
        resources = []
        if safe_float(item.get('cpu')) > 0:
            resources.append({'item_key': 'cpu', 'quantity': safe_float(item.get('cpu'))})
        if safe_float(item.get('memory')) > 0:
            resources.append({'item_key': 'memory', 'quantity': safe_float(item.get('memory'))})
        if safe_float(item.get('gpu_num')) > 0:
            gpu_parent = db.session.query(PriceConfig).filter(
                PriceConfig.item_type == 'model', PriceConfig.parent_key.is_(None)).first()
            resources.append({'item_key': gpu_parent.item_key if gpu_parent else 'gpu',
                              'option_key': str(item.get('gpu_type', '') or '').strip(),
                              'quantity': safe_float(item.get('gpu_num'))})
    # 算价：resources 存在则后端权威计算；否则沿用 amount_fen（外部指定）
    calc_items = []
    if resources:
        try:
            calc_items, amount_fen = calc_resources(resources, duration_seconds)
        except ValueError as e:
            raise ValueError(str(e))
        if amount_fen <= 0:
            raise ValueError('resources 算价为 0，请检查资源数与计费项配置')
    else:
        amount_fen = safe_int(item.get('amount_fen'))
        if amount_fen <= 0:
            raise ValueError('username and positive amount_fen required')
    if amount_fen > MAX_TRANSFER_FEN:
        raise ValueError('amount_fen exceeds limit %s' % MAX_TRANSFER_FEN)
    user = get_user_by_username(username)
    if not user:
        raise ValueError('user %s not found' % username)
    # 基础列回填（展示用）：从算价明细映射 cpu/memory/gpu（按配置匹配，不硬编码大小写；
    # GPU 汇总按"子型号挂载在型号型分组下"归并，分组名/子型号名任意都生效）
    cpu = memory = gpu_num = gpu_memory = 0.0
    gpu_type = ''
    pc_map = {p.item_key: p for p in db.session.query(PriceConfig).all()}
    for ci in calc_items:
        key = (ci['item_key'] or '').lower()
        if key == 'cpu':
            cpu = ci['quantity']
        elif key == 'memory':
            memory = ci['quantity']
        else:
            conf = pc_map.get(ci['item_key'])
            parent = pc_map.get(conf.parent_key) if conf and conf.parent_key else None
            if conf and parent and parent.item_type == 'model':
                gpu_num += ci['quantity']
                gpu_type = ci['option_key'] or ci['item_name']
    # pod_name 选填：为空存 NULL（唯一索引对 NULL 不生效，可多条）；填写则校验唯一
    if pod_name:
        exist = db.session.query(Bill).filter_by(pod_name=pod_name).first()
        if exist:
            raise ValueError('pod_name %s already exists, use another pod_name' % pod_name)
    bill = Bill(pod_name=pod_name, namespace=namespace, username=user.username, user_id=user.id, org=user.org,
                task_name=task_name, amount_fen=amount_fen, status='settled', source='manual',
                cpu=cpu, memory=memory, gpu_num=gpu_num, gpu_type=gpu_type, gpu_memory=gpu_memory,
                duration_seconds=duration_seconds)
    db.session.add(bill)
    db.session.flush()
    # 明细快照（历史价格不可变）
    _write_bill_items(bill.id, calc_items)
    wallet = lock_wallet(user.id)
    before = wallet.balance_fen
    wallet.balance_fen -= amount_fen
    db.session.add(AccountLog(
        type='consume', from_user_id=user.id, amount_fen=amount_fen,
        balance_before_fen=before, balance_after_fen=wallet.balance_fen,
        bill_id=bill.id, operator=current_operator(), remark=remark or '管理员手动扣费',
    ))
    db.session.commit()
    return {
        'username': username, 'amount_fen': amount_fen, 'balance_fen': wallet.balance_fen,
        'cpu': cpu, 'memory': memory, 'gpu_num': gpu_num, 'gpu_type': gpu_type, 'gpu_memory': gpu_memory,
        'duration_seconds': duration_seconds, 'items': calc_items, 'result': 'settled',
    }


def _write_bill_items(bill_id, calc_items):
    """写入账单明细快照：先清空再写，重复推送/修正时幂等重建"""
    db.session.query(BillItem).filter_by(bill_id=bill_id).delete()
    for ci in calc_items:
        db.session.add(BillItem(
            bill_id=bill_id, item_key=ci['item_key'], item_name=ci['item_name'],
            option_key=ci['option_key'], quantity=ci['quantity'],
            unit_price_fen=ci['unit_price_fen'], unit=ci.get('unit', ''),
            amount_fen=ci['amount_fen'],
        ))


@app.route('/billing/api/deduct', methods=['POST'])
def billing_deduct():
    """管理员手动扣费：单个对象或对象数组（批量），逐笔容错互不影响"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    items = data if isinstance(data, list) else [data]
    if not items:
        return err_response('empty body')
    results = []
    for item in items:
        try:
            results.append(_do_deduct(item))
        except Exception as e:
            db.session.rollback()
            results.append({
                'username': str(item.get('username', '') or '').strip(),
                'amount_fen': safe_int(item.get('amount_fen')),
                'result': 'error',
                'reason': str(e)[:200],
            })
    ok_count = len([r for r in results if r['result'] == 'settled'])
    return ok_response({'count': len(results), 'ok': ok_count, 'failed': len(results) - ok_count, 'results': results})


# ============================================================
# 用户查询（会话登录）
# ============================================================
@app.route('/billing/api/my_balance', methods=['GET'])
def billing_my_balance():
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    wallet = get_or_create_wallet(g.user.id)
    min_fen = conf.get('BILLING_MIN_BALANCE', -10000)
    balance = wallet.balance_fen
    status = 'normal' if balance >= 0 else ('blocked' if balance < min_fen else 'overdue')
    # 聚合统计（SQL 求和，全量准确，不依赖流水条数）
    def _sum(*flts):
        return int(db.session.query(db.func.coalesce(db.func.sum(AccountLog.amount_fen), 0)).filter(*flts).scalar() or 0)
    return ok_response({
        'username': g.user.username,
        'org': getattr(g.user, 'org', ''),
        'balance_fen': balance,
        'balance_yuan': round(balance / 100.0, 2),
        'min_balance_fen': min_fen,
        'min_balance_yuan': round(min_fen / 100.0, 2),
        'status': status,   # normal 正常 / overdue 欠费中 / blocked 欠费超限被拦截
        'total_consume_fen': _sum(AccountLog.type == 'consume', AccountLog.from_user_id == g.user.id),
        'total_consume_yuan': round(_sum(AccountLog.type == 'consume', AccountLog.from_user_id == g.user.id) / 100.0, 2),
        'total_recharge_fen': _sum(AccountLog.type == 'recharge', AccountLog.to_user_id == g.user.id),
        'total_recharge_yuan': round(_sum(AccountLog.type == 'recharge', AccountLog.to_user_id == g.user.id) / 100.0, 2),
        'total_refund_fen': _sum(AccountLog.type == 'refund', AccountLog.to_user_id == g.user.id),
        'total_refund_yuan': round(_sum(AccountLog.type == 'refund', AccountLog.to_user_id == g.user.id) / 100.0, 2),
    })


@app.route('/billing/api/my_bills', methods=['GET'])
def billing_my_bills():
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    query = db.session.query(Bill).filter_by(user_id=g.user.id)
    total = query.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    bills = _sort_query(query, Bill, request.args.to_dict(), Bill.id).offset((page - 1) * page_size).limit(page_size).all()
    result = [{
        'id': b.id,
        'pod_name': b.pod_name, 'namespace': b.namespace or '',
        'task_name': b.task_name, 'run_id': b.run_id,
        'cpu': b.cpu, 'memory': b.memory, 'gpu_num': b.gpu_num, 'gpu_memory': b.gpu_memory,
        'duration_seconds': b.duration_seconds, 'amount_fen': b.amount_fen, 'amount_yuan': round(b.amount_fen / 100.0, 2),
        'status': b.status,
        'items': [{
            'item_key': i.item_key, 'item_name': i.item_name, 'option_key': i.option_key,
            'quantity': i.quantity, 'unit_price_fen': i.unit_price_fen, 'unit': i.unit or '',
            'amount_fen': i.amount_fen,
        } for i in db.session.query(BillItem).filter_by(bill_id=b.id).all()],
        'created_on': b.created_on.strftime('%Y-%m-%d %H:%M:%S') if b.created_on else '',
    } for b in bills]
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'bills': result})


@app.route('/billing/api/my_logs', methods=['GET'])
def billing_my_logs():
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    query = db.session.query(AccountLog).filter(
        (AccountLog.from_user_id == g.user.id) | (AccountLog.to_user_id == g.user.id)
    )
    total = query.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    logs = _sort_query(query, AccountLog, request.args.to_dict(), AccountLog.id).offset((page - 1) * page_size).limit(page_size).all()
    result = [{
        'id': log.id, 'type': log.type,
        'type_name': {'recharge': '充值', 'consume': '消费', 'transfer_in': '转入', 'transfer_out': '转出'}.get(log.type, log.type),
        'amount_fen': log.amount_fen, 'amount_yuan': round(log.amount_fen / 100.0, 2),
        'balance_before_fen': log.balance_before_fen, 'balance_after_fen': log.balance_after_fen,
        'remark': log.remark, 'operator': log.operator,
        'created_on': log.created_on.strftime('%Y-%m-%d %H:%M:%S') if log.created_on else '',
    } for log in logs]
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'logs': result})


# ============================================================
# 动态计费项（数据驱动）：数量型 quantity / 型号型 model
# 后期新增计费项（存储/服务运维等）前端添加配置即可，无需改代码
# ============================================================
def _item_dict(p):
    # 型号型（分组）：children = 挂在该项下的子型号（独立数量型计费项）
    children = db.session.query(PriceConfig).filter_by(parent_key=p.item_key).order_by(PriceConfig.id.asc()).all()
    return {
        'item_key': p.item_key,
        'item_name': p.item_name or p.item_key,
        'item_type': p.item_type or 'quantity',
        'parent_key': p.parent_key or '',
        'price_fen': p.price_fen or 0,
        'price_yuan': round((p.price_fen or 0) / 100.0, 4),
        'unit': p.unit or '',
        'sort_order': p.sort_order or 0,
        'enabled': p.enabled if p.enabled is not None else 1,
        'updated_by': p.updated_by or '',
        'updated_on': p.updated_on.strftime('%Y-%m-%d %H:%M:%S') if p.updated_on else '',
        'children': [_item_dict(c) for c in children],
    }


def _all_prices():
    items = db.session.query(PriceConfig).filter(PriceConfig.parent_key.is_(None)).order_by(PriceConfig.sort_order.asc(), PriceConfig.id.asc()).all()
    return {'items': [_item_dict(p) for p in items]}


@app.route('/billing/api/prices', methods=['GET'])
def billing_prices():
    """计费项查询（所有登录用户可见，普通用户在我的账单页查看）"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    return ok_response(_all_prices())


@app.route('/billing/api/admin/items', methods=['POST', 'DELETE'])
def billing_admin_items():
    """计费项管理：POST 创建 {item_key, item_name, item_type, unit, price_fen, sort_order}；DELETE ?item_key= 删除"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    if request.method == 'DELETE':
        item_key = (request.args.get('item_key', '') or '').strip()
        p = db.session.query(PriceConfig).filter_by(item_key=item_key).first()
        if not p:
            return err_response('item %s not found' % item_key)
        # 级联删除子型号
        db.session.query(PriceConfig).filter_by(parent_key=item_key).delete()
        db.session.delete(p)
        db.session.commit()
        return ok_response({'deleted': item_key, **_all_prices()})
    data = request.get_json(force=True, silent=True) or {}
    item_key = str(data.get('item_key', '') or '').strip()
    if not item_key:
        return err_response('item_key required')
    if db.session.query(PriceConfig).filter_by(item_key=item_key).first():
        return err_response('item %s already exists' % item_key)
    item_type = str(data.get('item_type', 'quantity') or 'quantity').strip()
    parent_key = str(data.get('parent_key', '') or '').strip() or None
    if parent_key:
        # 子型号：挂在型号型分组下，强制数量型，单位继承父项
        parent = db.session.query(PriceConfig).filter_by(item_key=parent_key).first()
        if not parent:
            return err_response('parent %s not found' % parent_key)
        item_type = 'quantity'
    elif item_type not in ('quantity', 'model'):
        return err_response('item_type must be quantity or model')
    p = PriceConfig(
        item_key=item_key,
        item_name=str(data.get('item_name', '') or item_key)[:100],
        item_type=item_type,
        parent_key=parent_key,
        price_fen=safe_int(data.get('price_fen')),
        unit=str(data.get('unit', '') or '')[:50],
        sort_order=safe_int(data.get('sort_order')),
        updated_by=current_operator(),
    )
    db.session.add(p)
    db.session.commit()
    return ok_response({'created': item_key, **_all_prices()})


@app.route('/billing/api/admin/items/price', methods=['POST'])
def billing_admin_item_price():
    """改价：数量型 {item_key, price_fen}；型号细项 {item_key, option_key, price_fen}"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    item_key = str(data.get('item_key', '') or '').strip()
    price_fen = safe_int(data.get('price_fen'))
    if price_fen < 0 or price_fen > MAX_TRANSFER_FEN:
        return err_response('price invalid (0~%s)' % MAX_TRANSFER_FEN)
    p = db.session.query(PriceConfig).filter_by(item_key=item_key).first()
    if not p:
        return err_response('item %s not found' % item_key)
    option_key = str(data.get('option_key', '') or '').strip()
    if option_key:
        # 旧格式兼容：父项+型号 → 子型号计费项
        d = db.session.query(PriceConfig).filter_by(parent_key=item_key, item_name=option_key).first() \
            or db.session.query(PriceConfig).filter_by(parent_key=item_key, item_key=option_key).first()
        if not d:
            return err_response('option %s not found for %s' % (option_key, item_key))
        d.price_fen = price_fen
        d.updated_by = current_operator()
    else:
        p.price_fen = price_fen
        p.updated_by = current_operator()
    db.session.commit()
    return ok_response({'item_key': item_key, 'option_key': option_key, 'price_fen': price_fen, **_all_prices()})


@app.route('/billing/api/admin/items/options', methods=['POST', 'DELETE'])
def billing_admin_item_options():
    """兼容旧接口：型号细项 → 现在实现为父子计费项（子型号是独立数量型计费项）
    POST {item_key(父分组), option_key(型号名), price_fen} 创建/更新子项；
    DELETE ?item_key=&option_key= 删除子项"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    if request.method == 'DELETE':
        item_key = (request.args.get('item_key', '') or '').strip()
        option_key = (request.args.get('option_key', '') or '').strip()
        child = db.session.query(PriceConfig).filter_by(parent_key=item_key, item_name=option_key).first()
        if not child:
            return err_response('option %s not found under %s' % (option_key, item_key))
        db.session.delete(child)
        db.session.commit()
        return ok_response({'deleted': option_key, **_all_prices()})
    data = request.get_json(force=True, silent=True) or {}
    item_key = str(data.get('item_key', '') or '').strip()
    option_key = str(data.get('option_key', '') or '').strip()
    price_fen = safe_int(data.get('price_fen'))
    if not item_key or not option_key:
        return err_response('item_key and option_key required')
    if price_fen < 0 or price_fen > MAX_TRANSFER_FEN:
        return err_response('price invalid (0~%s)' % MAX_TRANSFER_FEN)
    parent = db.session.query(PriceConfig).filter_by(item_key=item_key).first()
    if not parent:
        return err_response('item %s not found' % item_key)
    child_key = '%s_%s' % (item_key, option_key.lower())
    child = db.session.query(PriceConfig).filter_by(item_key=child_key).first() \
        or db.session.query(PriceConfig).filter_by(parent_key=item_key, item_name=option_key).first()
    if not child:
        child = PriceConfig(item_key=child_key, item_name=option_key, item_type='quantity',
                            parent_key=item_key, unit=parent.unit, sort_order=100)
        db.session.add(child)
    child.item_name = str(data.get('option_name', '') or option_key)[:100]
    child.price_fen = price_fen
    child.updated_by = current_operator()
    db.session.commit()
    return ok_response({'item_key': item_key, 'option_key': option_key, 'price_fen': price_fen, **_all_prices()})


# ============================================================
# 算价引擎（后端权威）：resources → 逐项金额 + 总额
# ============================================================
def calc_resources(resources, duration_seconds):
    """resources: [{'item_key','option_key','quantity'}] → (明细列表, 总金额分)
    按月计费：金额 = Σ(数量 × 单价(分/单位/月)) × 时长秒 / (720*3600)
    子型号为独立数量型计费项（item_key 如 gpu_l20）；兼容旧格式：父项+option_key 自动映射到子型号"""
    items = {p.item_key: p for p in db.session.query(PriceConfig).filter(PriceConfig.enabled == 1).all()}
    duration_month = safe_int(duration_seconds) / 720.0 / 3600.0
    result, total = [], 0
    for r in resources or []:
        item = items.get(str(r.get('item_key', '') or '').strip())
        if not item:
            raise ValueError('未知计费项: %s' % r.get('item_key'))
        quantity = safe_float(r.get('quantity'))
        if quantity <= 0:
            continue
        opt = str(r.get('option_key', '') or '').strip()
        # 型号型分组：必须落到具体子型号（旧格式 option_key 兼容映射）
        if item.item_type == 'model':
            if not opt:
                raise ValueError('计费项 %s 为型号分组，请选择具体型号' % item.item_key)
            child = db.session.query(PriceConfig).filter_by(parent_key=item.item_key, item_name=opt).first() \
                or db.session.query(PriceConfig).filter_by(parent_key=item.item_key, item_key=opt).first()
            if not child:
                raise ValueError('计费项 %s 下不存在型号 %s' % (item.item_key, opt))
            item = child
        unit_fen = item.price_fen or 0
        amount = int(round(quantity * unit_fen * duration_month))
        total += amount
        result.append({
            'item_key': item.item_key,
            'item_name': item.item_name or item.item_key,
            'option_key': opt,
            'quantity': quantity,
            'unit_price_fen': unit_fen,
            'unit': item.unit or '',
            'amount_fen': amount,
        })
    return result, total


@app.route('/billing/api/calc', methods=['POST'])
def billing_calc():
    """算价预览（登录用户）：后端权威计算，前端实时调用展示"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    try:
        items, total = calc_resources(data.get('resources'), safe_int(data.get('duration_seconds')))
    except ValueError as e:
        return err_response(str(e))
    return ok_response({'items': items, 'total_fen': total, 'total_yuan': round(total / 100.0, 2)})


# ============================================================
# 管理端数据接口（管理员会话或 token 鉴权）
# ============================================================
def _bill_to_dict(b):
    return {
        'id': b.id,
        'pod_name': b.pod_name,
        'namespace': b.namespace or '',
        'task_name': b.task_name,
        'run_id': b.run_id,
        'username': b.username,
        'org': b.org,
        'cpu': b.cpu,
        'memory': b.memory,
        'gpu_num': b.gpu_num,
        'gpu_type': b.gpu_type or '',
        'gpu_memory': b.gpu_memory,
        'duration_seconds': b.duration_seconds,
        'amount_fen': b.amount_fen,
        'amount_yuan': round(b.amount_fen / 100.0, 2) if b.amount_fen else 0,
        'start_time': b.start_time.strftime('%Y-%m-%d %H:%M:%S') if b.start_time else '',
        'end_time': b.end_time.strftime('%Y-%m-%d %H:%M:%S') if b.end_time else '',
        'status': b.status,
        'source': b.source or '',
        'items': [{
            'item_key': i.item_key, 'item_name': i.item_name, 'option_key': i.option_key,
            'quantity': i.quantity, 'unit_price_fen': i.unit_price_fen, 'unit': i.unit or '',
            'amount_fen': i.amount_fen,
        } for i in db.session.query(BillItem).filter_by(bill_id=b.id).all()],
        'created_on': b.created_on.strftime('%Y-%m-%d %H:%M:%S') if b.created_on else '',
    }


def _log_to_dict(log):
    return {
        'id': log.id,
        'type': log.type,
        'type_name': {
            'recharge': '充值', 'consume': '消费', 'transfer_in': '转入', 'transfer_out': '转出'
        }.get(log.type, log.type),
        'from_username': _user_username(log.from_user_id),
        'to_username': _user_username(log.to_user_id),
        'amount_fen': log.amount_fen,
        'amount_yuan': round(log.amount_fen / 100.0, 2) if log.amount_fen else 0,
        'balance_before_yuan': round(log.balance_before_fen / 100.0, 2) if log.balance_before_fen else 0,
        'balance_after_yuan': round(log.balance_after_fen / 100.0, 2) if log.balance_after_fen else 0,
        'operator': log.operator,
        'remark': log.remark,
        'reversed': log.reversed or 0,
        'ref_log_id': log.ref_log_id,
        'created_on': log.created_on.strftime('%Y-%m-%d %H:%M:%S') if log.created_on else '',
    }


def split_org(org):
    """组织层级拆分：'软件与数字化中心-AI技术应用部' → ('软件与数字化中心', 'AI技术应用部')
    仅支持"中心-部门"两级；单段 org / 空 org 返回 None 中心（不参与组织树展示）"""
    org = (org or '').strip()
    if not org:
        return (None, None)
    parts = [p.strip() for p in org.split('-') if p.strip()]
    if len(parts) >= 2:
        return (parts[0], '-'.join(parts[1:]))
    return (None, org)


def _user_username(user_id):
    if not user_id:
        return '-'
    user = db.session.query(MyUser).filter_by(id=user_id).first()
    return user.username if user else '-'


@app.route('/billing/api/admin/stats', methods=['GET'])
def billing_admin_stats():
    if not check_admin_or_token():
        return err_response('no permission', 401)
    # 用户/部门统计
    users = db.session.query(MyUser).all()
    orgs = {}
    for u in users:
        orgs[u.org or '未分组'] = orgs.get(u.org or '未分组', 0) + 1
    # 余额统计
    wallets = db.session.query(Wallet).all()
    total_balance_fen = sum(w.balance_fen or 0 for w in wallets)
    balance_users = len(wallets)
    # 资金统计（MySQL SUM 返回 Decimal，统一转 int）
    def _sum_fen(*flts):
        return int(db.session.query(db.func.coalesce(db.func.sum(AccountLog.amount_fen), 0)).filter(*flts).scalar() or 0)
    total_recharge_fen = _sum_fen(AccountLog.type == 'recharge')
    total_consume_fen = _sum_fen(AccountLog.type == 'consume')
    bill_count = db.session.query(db.func.count(Bill.id)).scalar()
    today = datetime.date.today()
    today_consume_fen = _sum_fen(AccountLog.type == 'consume', AccountLog.created_on >= datetime.datetime.combine(today, datetime.time.min))
    # 部门消费排行（按账单 org 汇总）
    org_consume = db.session.query(Bill.org, db.func.coalesce(db.func.sum(Bill.amount_fen), 0)).group_by(Bill.org).all()
    org_consume_map = {r[0] or '未分组': int(r[1] or 0) for r in org_consume}
    org_consume_list = [{
        'name': k, 'consume_fen': v, 'consume_yuan': round(v / 100.0, 2)
    } for k, v in org_consume_map.items()]
    org_consume_list.sort(key=lambda x: -x['consume_fen'])
    # 组织树：中心 → 部门（仅"中心-部门"两级，单段/空 org 不参与展示）；dept 带原始 org 供详情过滤
    center_map = {}
    for u in users:
        center, dept = split_org(u.org)
        if not center:
            continue
        c = center_map.setdefault(center, {'name': center, 'user_count': 0, 'consume_fen': 0, 'depts': {}})
        c['user_count'] += 1
        d = c['depts'].setdefault(dept, {'name': dept, 'user_count': 0, 'consume_fen': 0, 'org': u.org})
        d['user_count'] += 1
    for org, fen in org_consume_map.items():
        center, dept = split_org(org)
        if not center:
            continue
        c = center_map.setdefault(center, {'name': center, 'user_count': 0, 'consume_fen': 0, 'depts': {}})
        c['consume_fen'] += fen
        d = c['depts'].setdefault(dept, {'name': dept, 'user_count': 0, 'consume_fen': 0, 'org': org})
        d['consume_fen'] += fen
    centers = [{
        'name': c['name'],
        'user_count': c['user_count'],
        'consume_fen': c['consume_fen'],
        'consume_yuan': round(c['consume_fen'] / 100.0, 2),
        'depts': [{
            'name': d['name'],
            'org': d['org'],
            'user_count': d['user_count'],
            'consume_fen': d['consume_fen'],
            'consume_yuan': round(d['consume_fen'] / 100.0, 2),
        } for d in sorted(c['depts'].values(), key=lambda x: -x['consume_fen'])],
    } for c in sorted(center_map.values(), key=lambda x: (-x['consume_fen'], -x['user_count']))]
    return ok_response({
        'user_count': len(users),
        'org_count': len(orgs),
        'orgs': [{'name': k, 'user_count': v} for k, v in sorted(orgs.items(), key=lambda x: -x[1])],
        'org_consume': org_consume_list,
        'centers': centers,   # 组织树：中心 → 部门（含成员数/累计消费）
        'balance_user_count': balance_users,
        'total_balance_fen': total_balance_fen,
        'total_balance_yuan': round(total_balance_fen / 100.0, 2),
        'total_recharge_fen': total_recharge_fen,
        'total_recharge_yuan': round(total_recharge_fen / 100.0, 2),
        'total_consume_fen': total_consume_fen,
        'total_consume_yuan': round(total_consume_fen / 100.0, 2),
        'today_consume_fen': today_consume_fen,
        'today_consume_yuan': round(today_consume_fen / 100.0, 2),
        'bill_count': bill_count,
    })


@app.route('/billing/api/admin/wallets', methods=['GET', 'POST'])
def billing_admin_wallets():
    # 以 ab_user 全表为准：每个用户一行，无钱包余额按 0 展示；SQL 分页/排序，支持几千用户
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if request.method == 'POST':
        params = request.get_json(force=True, silent=True) or {}
    else:
        params = request.args.to_dict()
    query = db.session.query(MyUser, Wallet).outerjoin(Wallet, Wallet.user_id == MyUser.id)
    if params.get('org'):
        query = query.filter(MyUser.org == params['org'])
    if params.get('center'):
        query = query.filter(MyUser.org.like(params['center'] + '%'))
    if params.get('username'):
        kw = params['username'].strip()
        query = query.filter((MyUser.username.like('%%%s%%' % kw)) | (MyUser.first_name.like('%%%s%%' % kw)))
    total = query.count()
    # 排序：balance(默认余额降序) / username / org / updated
    sort_by = params.get('sort_by', 'balance')
    order = params.get('order', 'desc')
    col = {'username': MyUser.username, 'org': MyUser.org, 'updated': Wallet.updated_on}.get(sort_by, Wallet.balance_fen)
    query = query.order_by(col.desc() if order == 'desc' else col.asc(), MyUser.id.asc())
    page = max(int(params.get('page', 1) or 1), 1)
    page_size = min(max(int(params.get('page_size', 20) or 20), 1), 200)
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    result = [{
        'user_id': u.id,
        'username': u.username or '-',
        'org': u.org or '-',
        'balance_fen': w.balance_fen if w else 0,
        'balance_yuan': round(w.balance_fen / 100.0, 2) if w else 0,
        'updated_on': w.updated_on.strftime('%Y-%m-%d %H:%M:%S') if w else '',
    } for u, w in rows]
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'wallets': result})


@app.route('/billing/api/admin/orgs', methods=['GET'])
def billing_admin_orgs():
    """搜索部门（跨中心按部门名模糊匹配，忘了中心名也能找到）：?keyword=部门名&center=限定中心"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    keyword = (request.args.get('keyword', '') or '').strip()
    center = (request.args.get('center', '') or '').strip()
    limit = min(max(int(request.args.get('limit', 20) or 20), 1), 100)
    org_map = {}
    for u in db.session.query(MyUser).all():
        org = (u.org or '').strip()
        if not org:
            continue
        c, d = split_org(org)
        if not c:
            continue
        if center and c != center:
            continue
        if keyword and keyword not in d:
            continue
        org_map.setdefault(org, {'org': org, 'center': c, 'name': d})
    result = sorted(org_map.values(), key=lambda x: (x['center'], x['name']))[:limit]
    return ok_response({'count': len(result), 'orgs': result})


@app.route('/billing/api/users', methods=['GET'])
def billing_users():
    # 搜索 ab_user 表用户（充值/转账选择用户用），模糊匹配 username
    if not check_admin_or_token():
        return err_response('no permission', 401)
    keyword = (request.args.get('keyword', '') or '').strip()
    limit = min(max(int(request.args.get('limit', 20) or 20), 1), 100)
    query = db.session.query(MyUser)
    if keyword:
        query = query.filter(MyUser.username.like('%%%s%%' % keyword))
    users = query.order_by(MyUser.id.asc()).limit(limit).all()
    return ok_response({'count': len(users), 'users': [{
        'username': u.username,
        'first_name': u.first_name or '',
        'org': u.org or '',
        'email': u.email or '',
    } for u in users]})


def _bill_query(params):
    query = db.session.query(Bill)
    if params.get('pod_name'):
        query = query.filter(Bill.pod_name.like('%%%s%%' % params['pod_name']))
    if params.get('username'):
        query = query.filter(Bill.username == params['username'])
    if params.get('task_name'):
        query = query.filter(Bill.task_name.like('%%%s%%' % params['task_name']))
    if params.get('org'):
        query = query.filter(Bill.org == params['org'])
    if params.get('center'):
        if params['center'] == '直属部门':
            query = query.filter(Bill.org.notlike('%-%'))
        else:
            query = query.filter(Bill.org.like(params['center'] + '%'))
    if params.get('start_time'):
        query = query.filter(Bill.created_on >= parse_time(params['start_time']))
    if params.get('end_time'):
        query = query.filter(Bill.created_on <= parse_time(params['end_time']))
    return query


def _org_user_ids(org=None, center=None):
    """返回某组织（org 精确 / center 中心前缀）下的全部用户 id"""
    users = db.session.query(MyUser).all()
    if org:
        return [u.id for u in users if (u.org or '') == org]
    if center:
        return [u.id for u in users if (u.org or '').startswith(center + '-')]
    return []


def _org_bill_filter(org=None, center=None):
    """组织维度的账单过滤条件（SQL）"""
    if org:
        return Bill.org == org
    if center:
        return Bill.org.like(center + '%')
    return None


def _log_query(params):
    query = db.session.query(AccountLog)
    if params.get('type'):
        query = query.filter(AccountLog.type == params['type'])
    if params.get('username'):
        user = get_user_by_username(params['username'])
        if user:
            query = query.filter(
                (AccountLog.from_user_id == user.id) | (AccountLog.to_user_id == user.id)
            )
    if params.get('org') or params.get('center'):
        user_ids = _org_user_ids(params.get('org') or '', params.get('center') or '')
        if not user_ids:
            query = query.filter(False)
        else:
            query = query.filter(
                AccountLog.from_user_id.in_(user_ids) | AccountLog.to_user_id.in_(user_ids)
            )
    if params.get('start_time'):
        query = query.filter(AccountLog.created_on >= parse_time(params['start_time']))
    if params.get('end_time'):
        query = query.filter(AccountLog.created_on <= parse_time(params['end_time']))
    return query


@app.route('/billing/api/admin/org_stats', methods=['GET'])
def billing_admin_org_stats():
    """组织维度汇总：成员数 / 累计消费 / 账单数（?org=部门名 或 ?center=中心名）"""
    if not check_admin_or_token():
        return err_response('no permission', 401)
    org = (request.args.get('org', '') or '').strip()
    center = (request.args.get('center', '') or '').strip()
    if not org and not center:
        return err_response('org or center required')
    user_ids = _org_user_ids(org, center)
    bill_filter = _org_bill_filter(org, center)
    total_consume = int(db.session.query(db.func.coalesce(db.func.sum(Bill.amount_fen), 0)).filter(bill_filter).scalar() or 0)
    bill_count = db.session.query(db.func.count(Bill.id)).filter(bill_filter).scalar()
    return ok_response({
        'user_count': len(user_ids),
        'total_consume_fen': total_consume,
        'total_consume_yuan': round(total_consume / 100.0, 2),
        'bill_count': bill_count,
    })


def _sort_query(query, model, params, default_col):
    """通用排序：sort_by / order 参数（created_on 时间 / amount 金额 / type 类型 / username 用户）"""
    sort_by = params.get('sort_by', '')
    order = params.get('order', 'desc')
    cols = {'created_on': model.created_on, 'amount': model.amount_fen}
    if hasattr(model, 'type'):
        cols['type'] = model.type
    if hasattr(model, 'username'):
        cols['username'] = model.username
    col = cols.get(sort_by, default_col)
    return query.order_by(col.desc() if order == 'desc' else col.asc(), model.id.desc())


@app.route('/billing/api/admin/bills', methods=['GET', 'POST'])
def billing_admin_bills():
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if request.method == 'POST':
        params = request.get_json(force=True, silent=True) or {}
    else:
        params = request.args.to_dict()
    query = _bill_query(params)
    total = query.count()
    page = max(int(params.get('page', 1) or 1), 1)
    page_size = min(max(int(params.get('page_size', 20) or 20), 1), 200)
    bills = _sort_query(query, Bill, params, Bill.id).offset((page - 1) * page_size).limit(page_size).all()
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'bills': [_bill_to_dict(b) for b in bills]})


@app.route('/billing/api/admin/logs', methods=['GET', 'POST'])
def billing_admin_logs():
    if not check_admin_or_token():
        return err_response('no permission', 401)
    if request.method == 'POST':
        params = request.get_json(force=True, silent=True) or {}
    else:
        params = request.args.to_dict()
    query = _log_query(params)
    total = query.count()
    page = max(int(params.get('page', 1) or 1), 1)
    page_size = min(max(int(params.get('page_size', 20) or 20), 1), 200)
    logs = _sort_query(query, AccountLog, params, AccountLog.id).offset((page - 1) * page_size).limit(page_size).all()
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'logs': [_log_to_dict(l) for l in logs]})


# ============================================================
# 计费控制台（自研现代页面，不走 FAB）
# ============================================================
@app.route('/billing/console', methods=['GET'])
def billing_console():
    if not check_admin_user():
        return err_response('no permission', 401)
    return send_from_directory(app.static_folder, 'billing/console.html')


# 我的账单（登录用户可见，只读自己的余额/明细/流水）
@app.route('/billing/my', methods=['GET'])
def billing_my():
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    return send_from_directory(app.static_folder, 'billing/my.html')


# ============================================================
# 撤销 / 冲正（审计友好：不物理删除，标记 reversed + 反向流水）
# ============================================================
@app.route('/billing/api/admin/bill/<int:bill_id>/reverse', methods=['POST'])
def billing_bill_reverse(bill_id):
    """账单撤销：仅手动账单可撤（外部账单由推送修正），回退余额 + refund 流水"""
    if not check_admin_user():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    bill = db.session.query(Bill).filter_by(id=bill_id).first()
    if not bill:
        return err_response('bill %s not found' % bill_id)
    if bill.status == 'reversed':
        return err_response('bill already reversed')
    if bill.source != 'manual':
        return err_response('only manual bills can be reversed, external bills should be corrected by push')
    if bill.user_id and bill.amount_fen > 0:
        wallet = lock_wallet(bill.user_id)
        before = wallet.balance_fen
        wallet.balance_fen += bill.amount_fen
        db.session.add(AccountLog(
            type='refund', to_user_id=bill.user_id, amount_fen=bill.amount_fen,
            balance_before_fen=before, balance_after_fen=wallet.balance_fen,
            bill_id=bill.id, operator=g.user.username, remark='账单撤销退回',
        ))
    bill.status = 'reversed'
    db.session.commit()
    return ok_response({'bill_id': bill.id, 'pod_name': bill.pod_name, 'amount_fen': bill.amount_fen})


@app.route('/billing/api/admin/log/<int:log_id>/reverse', methods=['POST'])
def billing_log_reverse(log_id):
    """流水冲正：充值冲正（扣回）；转账撤销（转入方扣回 + 转出方退回，双向）"""
    if not check_admin_user():
        return err_response('no permission', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    log = db.session.query(AccountLog).filter_by(id=log_id).first()
    if not log:
        return err_response('log %s not found' % log_id)
    if log.reversed:
        return err_response('log already reversed')
    operator = g.user.username
    if log.type == 'recharge':
        wallet = lock_wallet(log.to_user_id)
        if wallet.balance_fen < log.amount_fen:
            return err_response('insufficient balance to reverse the recharge')
        before = wallet.balance_fen
        wallet.balance_fen -= log.amount_fen
        log.reversed = 1
        db.session.add(AccountLog(
            type='reversal', to_user_id=log.to_user_id, amount_fen=log.amount_fen,
            balance_before_fen=before, balance_after_fen=wallet.balance_fen,
            operator=operator, remark='充值冲正，原流水#%s' % log.id, ref_log_id=log.id))
    elif log.type == 'transfer_out':
        from_user_id, to_user_id = log.from_user_id, log.to_user_id
        # 按 user_id 升序加锁避免死锁
        for uid in sorted([from_user_id, to_user_id]):
            lock_wallet(uid)
        to_wallet = db.session.query(Wallet).filter_by(user_id=to_user_id).first()
        if to_wallet.balance_fen < log.amount_fen:
            return err_response('insufficient balance of the receiver to reverse the transfer')
        to_before = to_wallet.balance_fen
        to_wallet.balance_fen -= log.amount_fen
        db.session.add(AccountLog(
            type='reversal', from_user_id=to_user_id, to_user_id=from_user_id, amount_fen=log.amount_fen,
            balance_before_fen=to_before, balance_after_fen=to_wallet.balance_fen,
            operator=operator, remark='转账撤销扣回，原流水#%s' % log.id, ref_log_id=log.id))
        from_wallet = db.session.query(Wallet).filter_by(user_id=from_user_id).first()
        f_before = from_wallet.balance_fen
        from_wallet.balance_fen += log.amount_fen
        db.session.add(AccountLog(
            type='reversal', from_user_id=from_user_id, to_user_id=to_user_id, amount_fen=log.amount_fen,
            balance_before_fen=f_before, balance_after_fen=from_wallet.balance_fen,
            operator=operator, remark='转账撤销退回，原流水#%s' % log.id, ref_log_id=log.id))
        log.reversed = 1
        # 关联的 transfer_in 流水一并标记（同方向/同金额/时间窗内）
        twin = db.session.query(AccountLog).filter(
            AccountLog.type == 'transfer_in',
            AccountLog.from_user_id == from_user_id,
            AccountLog.to_user_id == to_user_id,
            AccountLog.amount_fen == log.amount_fen,
            AccountLog.reversed == 0,
            AccountLog.id != log.id,
            AccountLog.created_on >= log.created_on - datetime.timedelta(seconds=10),
            AccountLog.created_on <= log.created_on + datetime.timedelta(seconds=10),
        ).first()
        if twin:
            twin.reversed = 1
    else:
        return err_response('only recharge or transfer_out logs can be reversed')
    db.session.commit()
    return ok_response({'log_id': log.id, 'type': log.type, 'amount_fen': log.amount_fen})


# ============================================================
# CSV 导出（管理员会话，带 BOM 供 Excel 正确识别中文）
# ============================================================
@app.route('/billing/api/admin/export', methods=['GET'])
def billing_admin_export():
    if not check_admin_user():
        return err_response('no permission', 401)
    import csv
    import io
    kind = request.args.get('kind', 'bills')
    params = request.args.to_dict()
    limit = min(max(int(params.pop('limit', 100000) or 100000), 1), 500000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    filename = 'billing_%s_%s.csv' % (kind, datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    if kind == 'logs':
        logs = _log_query(params).order_by(AccountLog.id.desc()).limit(limit).all()
        writer.writerow(['ID', '类型', '转出方', '转入方', '金额(分)', '金额(元)', '变动前(元)', '变动后(元)', '操作人', '备注', '时间'])
        type_names = {'recharge': '充值', 'consume': '消费', 'transfer_in': '转入', 'transfer_out': '转出', 'refund': '退款'}
        for l in logs:
            writer.writerow([
                l.id, type_names.get(l.type, l.type),
                _user_username(l.from_user_id), _user_username(l.to_user_id),
                l.amount_fen or 0, round((l.amount_fen or 0) / 100.0, 2),
                round((l.balance_before_fen or 0) / 100.0, 2), round((l.balance_after_fen or 0) / 100.0, 2),
                l.operator or '', l.remark or '',
                l.created_on.strftime('%Y-%m-%d %H:%M:%S') if l.created_on else '',
            ])
    else:
        bills = _bill_query(params).order_by(Bill.id.desc()).limit(limit).all()
        writer.writerow(['ID', 'pod名', '命名空间', '任务名', 'run_id', '用户', '部门', 'cpu核', '内存G', 'GPU卡', '显存G',
                         '时长(秒)', '金额(分)', '金额(元)', '开始时间', '结束时间', '状态', '入账时间'])
        for b in bills:
            writer.writerow([
                b.id, b.pod_name, b.namespace or '', b.task_name or '', b.run_id or '', b.username or '', b.org or '',
                b.cpu or 0, b.memory or 0, b.gpu_num or 0, b.gpu_memory or 0,
                b.duration_seconds or 0, b.amount_fen or 0, round((b.amount_fen or 0) / 100.0, 2),
                b.start_time.strftime('%Y-%m-%d %H:%M:%S') if b.start_time else '',
                b.end_time.strftime('%Y-%m-%d %H:%M:%S') if b.end_time else '',
                b.status or '',
                b.created_on.strftime('%Y-%m-%d %H:%M:%S') if b.created_on else '',
            ])
    resp = Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition'] = 'attachment; filename=%s' % filename
    return resp


# ============================================================
# 快照自动扣费（数据源 pod_info_history_v2，扣费单状态机：
#   draft → pushed → agreed → settled；质疑 disputed；作废 cancelled；超时自动同意）
# ============================================================
def _run_to_dict(run):
    return {
        'id': run.id,
        'execute_type': run.execute_type,
        'operator': run.operator,
        'generated_count': run.generated_count,
        'skipped_no_delta': run.skipped_no_delta,
        'skipped_not_running': run.skipped_not_running,
        'skipped_below_min': run.skipped_below_min,
        'skipped_whitelist': run.skipped_whitelist,
        'skipped_no_user': run.skipped_no_user,
        'skipped_fallback_gpu': run.skipped_fallback_gpu,
        'remark': run.remark or '',
        'created_on': run.created_on.strftime('%Y-%m-%d %H:%M:%S') if run.created_on else '',
    }


def _deduct_bill_to_dict(b):
    disputes = db.session.query(BillDispute).filter_by(bill_id=b.id).order_by(BillDispute.id.desc()).all()
    return {
        'id': b.id,
        'pod_name': b.pod_name or '',
        'pod_uid': b.pod_uid or '',
        'namespace': b.namespace or '',
        'username': b.username or '',
        'org': b.org or '',
        'cpu': b.cpu or 0,
        'memory': b.memory or 0,
        'gpu_num': b.gpu_num or 0,
        'gpu_type': b.gpu_type or '',
        'gpu_memory': b.gpu_memory or 0,
        'duration_seconds': b.duration_seconds or 0,
        'duration_hours': round((b.duration_seconds or 0) / 3600.0, 2),
        'deduct_from_hours': b.deduct_from_hours,
        'deduct_to_hours': b.deduct_to_hours,
        'amount_fen': b.amount_fen or 0,
        'amount_yuan': round((b.amount_fen or 0) / 100.0, 2),
        'status': b.status,
        'billing_run_id': b.billing_run_id,
        'start_time': b.start_time.strftime('%Y-%m-%d %H:%M:%S') if b.start_time else '',
        'end_time': b.end_time.strftime('%Y-%m-%d %H:%M:%S') if b.end_time else '',
        'created_on': b.created_on.strftime('%Y-%m-%d %H:%M:%S') if b.created_on else '',
        'items': [{
            'item_key': i.item_key, 'item_name': i.item_name, 'option_key': i.option_key,
            'quantity': i.quantity, 'unit_price_fen': i.unit_price_fen, 'unit': i.unit or '',
            'amount_fen': i.amount_fen,
        } for i in db.session.query(BillItem).filter_by(bill_id=b.id).all()],
        'disputes': [{
            'id': d.id, 'reason': d.reason or '', 'status': d.status,
            'resolution': d.resolution or '', 'resolution_note': d.resolution_note or '',
            'operator': d.operator or '',
            'created_on': d.created_on.strftime('%Y-%m-%d %H:%M:%S') if d.created_on else '',
            'processed_on': d.processed_on.strftime('%Y-%m-%d %H:%M:%S') if d.processed_on else '',
        } for d in disputes],
    }


# ---- 管理员端 ----
@app.route('/billing/api/admin/deduct/run', methods=['POST'])
def billing_admin_deduct_run():
    """手动执行一轮扣费：生成 draft 扣费单（幂等：增量=0 的任务自动跳过）"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    from myapp.tools.billing_deduct import run_deduct
    data = request.get_json(force=True, silent=True) or {}
    try:
        run = run_deduct(operator=current_operator(), execute_type='manual',
                         remark=str(data.get('remark', '') or '')[:200])
    except ValueError as e:
        return err_response(str(e))
    return ok_response(_run_to_dict(run))


@app.route('/billing/api/admin/deduct/runs', methods=['GET'])
def billing_admin_deduct_runs():
    """扣费批次列表"""
    if not check_admin_user():
        return err_response('admin required', 403)
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    query = db.session.query(BillingRun)
    total = query.count()
    runs = query.order_by(BillingRun.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok_response({'count': total, 'page': page, 'page_size': page_size,
                        'runs': [_run_to_dict(r) for r in runs]})


@app.route('/billing/api/admin/deduct/bills', methods=['GET'])
def billing_admin_deduct_bills():
    """扣费单列表（管理员）：run_id / status / username / keyword 筛选"""
    if not check_admin_user():
        return err_response('admin required', 403)
    query = db.session.query(Bill).filter_by(source='history')
    run_id = safe_int(request.args.get('run_id'))
    if run_id:
        query = query.filter_by(billing_run_id=run_id)
    status = request.args.get('status', '').strip()
    if status:
        query = query.filter_by(status=status)
    username = request.args.get('username', '').strip()
    if username:
        query = query.filter(Bill.username.like('%' + username + '%'))
    keyword = request.args.get('keyword', '').strip()
    if keyword:
        query = query.filter(or_(Bill.pod_name.like('%' + keyword + '%'),
                                 Bill.pod_uid.like('%' + keyword + '%')))
    total = query.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    bills = query.order_by(Bill.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok_response({'count': total, 'page': page, 'page_size': page_size,
                        'bills': [_deduct_bill_to_dict(b) for b in bills]})


@app.route('/billing/api/admin/deduct/push', methods=['POST'])
def billing_admin_deduct_push():
    """推送扣费单 draft → pushed：bill_ids 多选；不传或传空 = 一键全推当前所有 draft"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    bill_ids = [safe_int(i) for i in (data.get('bill_ids') or []) if safe_int(i) > 0]
    query = db.session.query(Bill).filter_by(source='history', status='draft')
    if bill_ids:
        query = query.filter(Bill.id.in_(bill_ids))
    bills = query.all()
    now = datetime.datetime.now()
    for b in bills:
        b.status = 'pushed'
        b.updated_on = now
    db.session.commit()
    return ok_response({'count': len(bills)})


@app.route('/billing/api/admin/deduct/dispute/resolve', methods=['POST'])
def billing_admin_deduct_dispute_resolve():
    """处理质疑：
    adjust 改价重推（new_amount_fen 指定新金额，回到 draft）
    reject 驳回（按原金额直接结算入账）
    cancel 作废（本次不扣费，指针不占用）"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    from myapp.tools.billing_deduct import settle_bill
    data = request.get_json(force=True, silent=True) or {}
    bill_id = safe_int(data.get('bill_id'))
    action = str(data.get('action', '') or '').strip()
    note = str(data.get('note', '') or '')[:500]
    bill = db.session.query(Bill).filter_by(id=bill_id).first()
    if not bill:
        return err_response('bill not found')
    dispute = db.session.query(BillDispute).filter_by(bill_id=bill_id, status='open').first()
    if action == 'adjust':
        new_amount = safe_int(data.get('new_amount_fen'))
        if new_amount <= 0:
            return err_response('new_amount_fen must be positive')
        bill.amount_fen = new_amount
        bill.status = 'draft'
        bill.updated_on = datetime.datetime.now()
    elif action == 'reject':
        bill.status = 'agreed'
        bill.updated_on = datetime.datetime.now()
        db.session.flush()
        settle_bill(bill, operator=current_operator())
    elif action == 'cancel':
        bill.status = 'cancelled'
        bill.updated_on = datetime.datetime.now()
    else:
        return err_response('invalid action (adjust/reject/cancel)')
    if dispute:
        dispute.status = 'processed'
        dispute.resolution = action
        dispute.resolution_note = note
        dispute.operator = current_operator()
        dispute.processed_on = datetime.datetime.now()
    db.session.commit()
    return ok_response({'bill_id': bill.id, 'status': bill.status, 'amount_fen': bill.amount_fen})


@app.route('/billing/api/admin/deduct/config', methods=['GET', 'POST'])
def billing_admin_deduct_config():
    """扣费规则配置读写：min_duration_minutes / month_hours / auto_settle_days / gpu_fallback / enabled"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if request.method == 'GET':
        rows = db.session.query(BillingConfig).all()
        return ok_response({r.cfg_key: r.cfg_value for r in rows})
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    allowed = ('min_duration_minutes', 'month_hours', 'auto_settle_days', 'gpu_fallback', 'enabled')
    for k, v in data.items():
        if k not in allowed:
            continue
        row = db.session.query(BillingConfig).filter_by(cfg_key=k).first()
        if not row:
            row = BillingConfig(cfg_key=k)
            db.session.add(row)
        row.cfg_value = str(v)
        row.updated_by = current_operator()
    db.session.commit()
    rows = db.session.query(BillingConfig).all()
    return ok_response({r.cfg_key: r.cfg_value for r in rows})


@app.route('/billing/api/admin/deduct/whitelist', methods=['GET'])
def billing_admin_deduct_whitelist():
    """白名单列表"""
    if not check_admin_user():
        return err_response('admin required', 403)
    rows = db.session.query(BillWhitelist).order_by(BillWhitelist.id.desc()).all()
    return ok_response([{
        'id': w.id, 'dimension': w.dimension, 'value': w.value,
        'note': w.note or '', 'enabled': w.enabled,
        'created_by': w.created_by or '',
        'created_on': w.created_on.strftime('%Y-%m-%d %H:%M:%S') if w.created_on else '',
    } for w in rows])


@app.route('/billing/api/admin/deduct/whitelist/add', methods=['POST'])
def billing_admin_deduct_whitelist_add():
    """添加白名单：dimension ∈ org 部门 / user 用户 / cluster 集群"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    dimension = str(data.get('dimension', '') or '').strip()
    value = str(data.get('value', '') or '').strip()
    if dimension not in ('org', 'user', 'cluster') or not value:
        return err_response('dimension(org/user/cluster) and value required')
    if db.session.query(BillWhitelist).filter_by(dimension=dimension, value=value).first():
        return err_response('白名单 %s:%s 已存在' % (dimension, value))
    w = BillWhitelist(dimension=dimension, value=value,
                      note=str(data.get('note', '') or '')[:200],
                      enabled=1 if safe_int(data.get('enabled', 1)) else 0,
                      created_by=current_operator())
    db.session.add(w)
    db.session.commit()
    return ok_response({'id': w.id})


@app.route('/billing/api/admin/deduct/whitelist/toggle', methods=['POST'])
def billing_admin_deduct_whitelist_toggle():
    """启用/停用白名单"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    w = db.session.query(BillWhitelist).filter_by(id=safe_int(data.get('id'))).first()
    if not w:
        return err_response('whitelist not found')
    w.enabled = 0 if (w.enabled or 0) else 1
    db.session.commit()
    return ok_response({'id': w.id, 'enabled': w.enabled})


@app.route('/billing/api/admin/deduct/whitelist/delete', methods=['POST'])
def billing_admin_deduct_whitelist_delete():
    """删除白名单"""
    if not check_admin_user():
        return err_response('admin required', 403)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    w = db.session.query(BillWhitelist).filter_by(id=safe_int(data.get('id'))).first()
    if not w:
        return err_response('whitelist not found')
    db.session.delete(w)
    db.session.commit()
    return ok_response({'id': data.get('id')})


# ---- 用户端 ----
@app.route('/billing/api/my/deduct_bills', methods=['GET'])
def billing_my_deduct_bills():
    """我的扣费单（history 来源）：status 筛选"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    query = db.session.query(Bill).filter_by(source='history', user_id=g.user.id)
    status = request.args.get('status', '').strip()
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    bills = query.order_by(Bill.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok_response({'count': total, 'page': page, 'page_size': page_size,
                        'bills': [_deduct_bill_to_dict(b) for b in bills]})


@app.route('/billing/api/my/deduct_bills/agree', methods=['POST'])
def billing_my_deduct_bills_agree():
    """用户同意扣费单：pushed → agreed → 立即结算入账"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    from myapp.tools.billing_deduct import settle_bill
    data = request.get_json(force=True, silent=True) or {}
    bill = db.session.query(Bill).filter_by(
        id=safe_int(data.get('bill_id')), user_id=g.user.id, status='pushed').first()
    if not bill:
        return err_response('bill not found or not pushed')
    bill.status = 'agreed'
    bill.updated_on = datetime.datetime.now()
    db.session.flush()
    settle_bill(bill, operator=g.user.username)
    return ok_response({'bill_id': bill.id, 'status': bill.status,
                        'amount_fen': bill.amount_fen})


@app.route('/billing/api/my/deduct_bills/dispute', methods=['POST'])
def billing_my_deduct_bills_dispute():
    """用户质疑扣费单：pushed → disputed + 质疑记录（reason 必填）"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    if not require_json_content():
        return err_response('Content-Type must be application/json', 415)
    data = request.get_json(force=True, silent=True) or {}
    reason = str(data.get('reason', '') or '').strip()
    if not reason:
        return err_response('reason required')
    bill = db.session.query(Bill).filter_by(
        id=safe_int(data.get('bill_id')), user_id=g.user.id, status='pushed').first()
    if not bill:
        return err_response('bill not found or not pushed')
    if db.session.query(BillDispute).filter_by(bill_id=bill.id, status='open').first():
        return err_response('该扣费单已有待处理质疑')
    bill.status = 'disputed'
    bill.updated_on = datetime.datetime.now()
    db.session.add(BillDispute(bill_id=bill.id, user_id=g.user.id, reason=reason))
    db.session.commit()
    return ok_response({'bill_id': bill.id, 'status': bill.status})


@app.route('/billing/api/my/pod_history', methods=['GET'])
def billing_my_pod_history():
    """我的历史 Pod 记录：按 pod_uid 聚合最新快照，任意组合筛选
    筛选：status / pod_name 模糊 / cluster / node_name 模糊 / gpu_type / start_time / end_time（update_at）"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    base = db.session.query(PodInfoHistoryV2.pod_uid,
                            db.func.max(PodInfoHistoryV2.update_at).label('max_update')).filter_by(
        username=g.user.username)
    status = request.args.get('status', '').strip()
    if status:
        base = base.filter(PodInfoHistoryV2.status == status)
    pod_name = request.args.get('pod_name', '').strip()
    if pod_name:
        base = base.filter(PodInfoHistoryV2.pod_name.like('%' + pod_name + '%'))
    cluster = request.args.get('cluster', '').strip()
    if cluster:
        base = base.filter(PodInfoHistoryV2.cluster == cluster)
    node = request.args.get('node_name', '').strip()
    if node:
        base = base.filter(PodInfoHistoryV2.node_name.like('%' + node + '%'))
    gpu_type = request.args.get('gpu_type', '').strip()
    if gpu_type:
        base = base.outerjoin(AllNodeMemory, AllNodeMemory.node_name == PodInfoHistoryV2.node_name)
        base = base.filter(AllNodeMemory.gpu_type == gpu_type)
    start_time = request.args.get('start_time', '').strip()
    if start_time:
        base = base.filter(PodInfoHistoryV2.update_at >= (start_time + ' 00:00:00' if len(start_time) == 10 else start_time))
    end_time = request.args.get('end_time', '').strip()
    if end_time:
        base = base.filter(PodInfoHistoryV2.update_at <= (end_time + ' 23:59:59' if len(end_time) == 10 else end_time))
    sub = base.group_by(PodInfoHistoryV2.pod_uid).subquery()
    q = db.session.query(PodInfoHistoryV2).join(
        sub, and_(PodInfoHistoryV2.pod_uid == sub.c.pod_uid,
                  PodInfoHistoryV2.update_at == sub.c.max_update))
    total = q.count()
    page = max(int(request.args.get('page', 1) or 1), 1)
    page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 200)
    rows = q.order_by(PodInfoHistoryV2.update_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # 批量关联显卡型号
    nodes = {n.node_name: n.gpu_type for n in db.session.query(AllNodeMemory).all()}
    result = [{
        'pod_uid': r.pod_uid, 'pod_name': r.pod_name or '', 'namespace': r.k8s_namespace or '',
        'status': r.status or '', 'node_name': r.node_name or '', 'cluster': r.cluster or '',
        'gpu_type': nodes.get(r.node_name) or '',
        'gpu_mem_usage_gb': r.gpu_mem_usage_gb or 0, 'gpu_usage': r.gpu_usage or 0,
        'mem_limit_gb': r.mem_limit_gb or 0, 'cpu_limit': r.cpu_limit or 0,
        'duration_hours': _parse_duration_hours(r.duration),
        'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
        'update_at': r.update_at.strftime('%Y-%m-%d %H:%M:%S') if r.update_at else '',
        'label': r.label or '',
    } for r in rows]
    return ok_response({'count': total, 'page': page, 'page_size': page_size, 'pods': result})


@app.route('/billing/api/my/pod_history/detail', methods=['GET'])
def billing_my_pod_history_detail():
    """某任务按天快照明细（本人）"""
    if not g.user or not g.user.is_authenticated:
        return err_response('please login', 401)
    pod_uid = request.args.get('pod_uid', '').strip()
    if not pod_uid:
        return err_response('pod_uid required')
    rows = db.session.query(PodInfoHistoryV2).filter_by(
        pod_uid=pod_uid, username=g.user.username).order_by(PodInfoHistoryV2.update_at.asc()).all()
    if not rows:
        return err_response('record not found')
    nodes = {n.node_name: n.gpu_type for n in db.session.query(AllNodeMemory).all()}
    result = [{
        'id': r.id, 'pod_uid': r.pod_uid, 'pod_name': r.pod_name or '',
        'namespace': r.k8s_namespace or '', 'status': r.status or '',
        'node_name': r.node_name or '', 'cluster': r.cluster or '',
        'gpu_type': nodes.get(r.node_name) or '',
        'gpu_mem_usage_gb': r.gpu_mem_usage_gb or 0, 'gpu_usage': r.gpu_usage or 0,
        'mem_limit_gb': r.mem_limit_gb or 0, 'cpu_limit': r.cpu_limit or 0,
        'duration_hours': _parse_duration_hours(r.duration),
        'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
        'update_at': r.update_at.strftime('%Y-%m-%d %H:%M:%S') if r.update_at else '',
        'label': r.label or '',
    } for r in rows]
    return ok_response({'pod_uid': pod_uid, 'count': len(result), 'rows': result})


def _parse_duration_hours(duration):
    """duration 是 varchar 小时数，容错解析"""
    try:
        return round(float(str(duration or '').strip()), 2)
    except Exception:
        return 0
