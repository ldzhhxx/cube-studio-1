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
from sqlalchemy.exc import IntegrityError

from myapp import app, appbuilder, db, conf
from myapp.models.model_billing import Bill, Wallet, AccountLog
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
                username=username,
                user_id=user_id,
                org=org,
                cpu=safe_float(item.get('cpu')),
                memory=safe_float(item.get('memory')),
                gpu_num=safe_float(item.get('gpu_num')),
                gpu_memory=safe_float(item.get('gpu_memory')),
                duration_seconds=safe_int(item.get('duration_seconds')),
                amount_fen=amount_fen,
                start_time=parse_time(item.get('start_time')),
                end_time=parse_time(item.get('end_time')),
                source='external',
            )
            bill = db.session.query(Bill).filter_by(pod_name=pod_name).first()
            if bill:
                # 重复推送：修正数据；金额变化时结算差额（补扣/退回），不重复扣全额
                old_amount = bill.amount_fen or 0
                for k, v in bill_fields.items():
                    setattr(bill, k, v)
                bill.status = 'settled'
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
    """单笔手动扣费：写入 bill 账本 + 扣钱包 + consume 流水，返回结果 dict"""
    username = str(item.get('username', '') or '').strip()
    amount_fen = safe_int(item.get('amount_fen'))
    remark = str(item.get('remark', '') or '')[:500]
    task_name = str(item.get('task_name', '') or '')[:200]
    pod_name = str(item.get('pod_name', '') or '').strip()
    if not username or amount_fen <= 0:
        raise ValueError('username and positive amount_fen required')
    if amount_fen > MAX_TRANSFER_FEN:
        raise ValueError('amount_fen exceeds limit %s' % MAX_TRANSFER_FEN)
    user = get_user_by_username(username)
    if not user:
        raise ValueError('user %s not found' % username)
    # pod_name 不传则自动生成（bill 账本要求 pod_name 唯一）
    if not pod_name:
        pod_name = 'manual-%s-%s' % (user.username, datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17])
    exist = db.session.query(Bill).filter_by(pod_name=pod_name).first()
    if exist:
        raise ValueError('pod_name %s already exists, use another pod_name' % pod_name)
    bill = Bill(pod_name=pod_name, username=user.username, user_id=user.id, org=user.org,
                task_name=task_name, amount_fen=amount_fen, status='settled', source='manual')
    db.session.add(bill)
    db.session.flush()
    wallet = lock_wallet(user.id)
    before = wallet.balance_fen
    wallet.balance_fen -= amount_fen
    db.session.add(AccountLog(
        type='consume', from_user_id=user.id, amount_fen=amount_fen,
        balance_before_fen=before, balance_after_fen=wallet.balance_fen,
        bill_id=bill.id, operator=current_operator(), remark=remark or '管理员手动扣费',
    ))
    db.session.commit()
    return {'username': username, 'amount_fen': amount_fen, 'balance_fen': wallet.balance_fen, 'result': 'settled'}


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
        'pod_name': b.pod_name, 'task_name': b.task_name, 'run_id': b.run_id,
        'cpu': b.cpu, 'memory': b.memory, 'gpu_num': b.gpu_num, 'gpu_memory': b.gpu_memory,
        'duration_seconds': b.duration_seconds, 'amount_fen': b.amount_fen, 'amount_yuan': round(b.amount_fen / 100.0, 2),
        'status': b.status,
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
# 管理端数据接口（管理员会话或 token 鉴权）
# ============================================================
def _bill_to_dict(b):
    return {
        'id': b.id,
        'pod_name': b.pod_name,
        'task_name': b.task_name,
        'run_id': b.run_id,
        'username': b.username,
        'org': b.org,
        'cpu': b.cpu,
        'memory': b.memory,
        'gpu_num': b.gpu_num,
        'gpu_memory': b.gpu_memory,
        'duration_seconds': b.duration_seconds,
        'amount_fen': b.amount_fen,
        'amount_yuan': round(b.amount_fen / 100.0, 2) if b.amount_fen else 0,
        'start_time': b.start_time.strftime('%Y-%m-%d %H:%M:%S') if b.start_time else '',
        'end_time': b.end_time.strftime('%Y-%m-%d %H:%M:%S') if b.end_time else '',
        'status': b.status,
        'source': b.source or '',
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
        writer.writerow(['ID', 'pod名', '任务名', 'run_id', '用户', '部门', 'cpu核', '内存G', 'GPU卡', '显存G',
                         '时长(秒)', '金额(分)', '金额(元)', '开始时间', '结束时间', '状态', '入账时间'])
        for b in bills:
            writer.writerow([
                b.id, b.pod_name, b.task_name or '', b.run_id or '', b.username or '', b.org or '',
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
