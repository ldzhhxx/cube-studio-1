# -*- coding: utf-8 -*-
"""扣费定时任务（beat 每 10 分钟触发检查，实际周期由 billing_config 配置决定）：

1. 超时自动扣费扫描（始终执行）：pushed 超过 auto_settle_days 天未处理 → 自动同意并入账
2. 定时扣费（按 schedule_interval_minutes 判断是否到期）：
   管理员在"规则配置"设置周期（分钟，0=关闭，如 1440=每天、10080=每周），
   到期后执行一轮扣费（execute_type=scheduled），并记录 last_scheduled_run
"""
import datetime
import logging

from myapp import app, db
from myapp.tasks.celery_app import celery_app
from myapp.tools.billing_deduct import (get_config_int, get_config, run_deduct,
                                        auto_settle_scan)
from myapp.models.model_billing import BillingConfig

logger = logging.getLogger(__name__)


@celery_app.task(name='task.billing_deduct_check')
def billing_deduct_check():
    with app.app_context():
        # 1. 超时自动扣费（独立于周期开关，始终生效）
        settled = auto_settle_scan()
        # 2. 功能总开关
        if get_config_int('enabled', 1) != 1:
            return 'deduct disabled; auto_settle=%s' % settled
        # 3. 定时周期判断
        interval = get_config_int('schedule_interval_minutes', 0)
        if interval <= 0:
            return 'schedule off; auto_settle=%s' % settled
        now = datetime.datetime.now()
        last_raw = get_config('last_scheduled_run', '')
        last = None
        if last_raw:
            try:
                last = datetime.datetime.strptime(str(last_raw), '%Y-%m-%d %H:%M:%S')
            except Exception:
                last = None
        if last and (now - last).total_seconds() < interval * 60:
            return 'not due (last %s); auto_settle=%s' % (last_raw, settled)
        # 4. 执行一轮定时扣费
        run = run_deduct(operator='scheduler', execute_type='scheduled', remark='定时扣费')
        row = db.session.query(BillingConfig).filter_by(cfg_key='last_scheduled_run').first()
        if not row:
            row = BillingConfig(cfg_key='last_scheduled_run')
            db.session.add(row)
        row.cfg_value = now.strftime('%Y-%m-%d %H:%M:%S')
        row.updated_on = now
        db.session.commit()
        logger.info('scheduled deduct run #%s generated %s, auto_settle %s',
                    run.id, run.generated_count, settled)
        return 'run #%s generated=%s auto_settle=%s' % (run.id, run.generated_count, settled)
