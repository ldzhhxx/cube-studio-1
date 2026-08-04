-- ============================================================
-- 计费系统（Billing）建表脚本（含快照自动扣费 + 数据源表）
-- 更新：2026-08-04
--
-- 执行说明：
--   1. 计费核心表（price_config / bill / bill_item / wallet / account_log
--      / billing_run / bill_dispute / bill_whitelist / billing_config）【先删除再重建】，幂等可重复执行
--   2. 数据源表 pod_info_history_v2 / all_node_memory 为【外部维护/采集】表：
--      全新环境可执行本脚本建表；生产已有该表时只执行文末的 ALTER 语句
--   3. 本脚本不含业务测试数据，仅含 billing_config 默认配置与 all_node_memory 示例节点
-- ============================================================

-- ---------- 1. 删除并重建计费核心表 ----------
DROP TABLE IF EXISTS `bill_dispute`;
DROP TABLE IF EXISTS `bill_item`;
DROP TABLE IF EXISTS `account_log`;
DROP TABLE IF EXISTS `bill`;
DROP TABLE IF EXISTS `billing_run`;
DROP TABLE IF EXISTS `bill_whitelist`;
DROP TABLE IF EXISTS `billing_config`;
DROP TABLE IF EXISTS `wallet`;
DROP TABLE IF EXISTS `price_config`;

-- 计费项配置：quantity 数量型 / model 型号型（分组，子型号为独立数量型计费项）
CREATE TABLE `price_config` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `item_key` varchar(50) NOT NULL,           -- 计费项标识：cpu / memory / gpu / gpu_l20 ...
  `item_name` varchar(100) DEFAULT NULL,     -- 显示名：CPU / 内存 / GPU / L20 ...
  `item_type` varchar(20) DEFAULT 'quantity',-- quantity 数量型 / model 型号型（分组）
  `parent_key` varchar(50) DEFAULT NULL,     -- 父计费项标识（型号分组下的子型号），NULL=顶级
  `price_fen` int(11) DEFAULT NULL,          -- 数量型单价（分/单位/月）
  `unit` varchar(50) DEFAULT NULL,           -- 如 元/核/月
  `sort_order` int(11) DEFAULT NULL,
  `enabled` int(11) DEFAULT 1,
  `updated_by` varchar(100) DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_price_resource` (`item_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扣费批次：一次执行生成一个批次，记录统计结果（先于 bill 创建，bill 引用其外键）
CREATE TABLE `billing_run` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `execute_type` varchar(20) DEFAULT 'manual', -- manual 手动 / scheduled 定时
  `operator` varchar(100) DEFAULT NULL,        -- 执行人
  `generated_count` int(11) DEFAULT 0,         -- 生成扣费单数
  `skipped_no_delta` int(11) DEFAULT 0,        -- 跳过：增量=0（已扣过）
  `skipped_not_running` int(11) DEFAULT 0,     -- 跳过：非 Running
  `skipped_below_min` int(11) DEFAULT 0,       -- 跳过：未达最低付费时长
  `skipped_whitelist` int(11) DEFAULT 0,       -- 跳过：命中白名单
  `skipped_no_user` int(11) DEFAULT 0,         -- 跳过：用户名对不上平台账号
  `skipped_fallback_gpu` int(11) DEFAULT 0,    -- 显卡型号走了兜底的数量
  `remark` varchar(500) DEFAULT NULL,
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 费用明细：外部推送一条一单；快照扣费同一 pod 可有多条（增量结算，一次扣费一条）
CREATE TABLE `bill` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `pod_name` varchar(200) DEFAULT NULL,       -- pod名：推送幂等键；手动扣费选填；快照扣费为任务 pod 名（不再唯一）
  `pod_uid` varchar(200) DEFAULT NULL,        -- 任务标识（快照扣费来源：pod_info_history_v2.pod_uid）
  `billing_run_id` int(11) DEFAULT NULL,      -- 扣费批次（billing_run.id）
  `deduct_from_hours` float DEFAULT NULL,     -- 本次计费起点（上次已扣时长，小时）
  `deduct_to_hours` float DEFAULT NULL,       -- 本次计费终点（最新快照 duration，小时）
  `namespace` varchar(200) DEFAULT NULL,      -- 命名空间（手动扣费/推送可选）
  `task_name` varchar(200) DEFAULT NULL,
  `run_id` varchar(200) DEFAULT NULL,
  `username` varchar(100) DEFAULT NULL,
  `user_id` int(11) DEFAULT NULL,
  `org` varchar(200) DEFAULT NULL,            -- 冗余部门（ab_user.org）
  `cpu` float DEFAULT NULL,                   -- cpu核数
  `memory` float DEFAULT NULL,                -- 内存GB
  `gpu_num` float DEFAULT NULL,               -- gpu卡数（gpu_usage/100，可为小数）
  `gpu_type` varchar(50) DEFAULT NULL,        -- GPU 型号（A40/L20/...）
  `gpu_memory` float DEFAULT NULL,            -- 显存GB
  `duration_seconds` int(11) DEFAULT NULL,    -- 本次计费时长（增量，秒）
  `amount_fen` int(11) DEFAULT NULL,          -- 费用（分）
  `start_time` datetime DEFAULT NULL,
  `end_time` datetime DEFAULT NULL,
  `status` varchar(50) DEFAULT NULL,          -- draft待推送 pushed已推送 agreed已同意 disputed有异议 settled已入账 cancelled作废 failed失败
  `source` varchar(50) DEFAULT NULL,          -- external外部推送 / manual手动扣费 / history快照扣费
  `created_on` datetime NOT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_bill_pod_uid` (`pod_uid`),
  KEY `ix_bill_billing_run_id` (`billing_run_id`),
  KEY `ix_bill_pod_name` (`pod_name`),
  KEY `ix_bill_username` (`username`),
  KEY `ix_bill_org` (`org`),
  KEY `ix_bill_created_on` (`created_on`),
  KEY `fk_bill_user` (`user_id`),
  CONSTRAINT `fk_bill_user` FOREIGN KEY (`user_id`) REFERENCES `ab_user` (`id`),
  CONSTRAINT `fk_bill_run` FOREIGN KEY (`billing_run_id`) REFERENCES `billing_run` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 账单明细项（快照）：每笔账单的每个计费项一行，价格以当时为准
CREATE TABLE `bill_item` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `bill_id` int(11) NOT NULL,                -- FK bill.id
  `item_key` varchar(50) DEFAULT NULL,
  `item_name` varchar(100) DEFAULT NULL,
  `option_key` varchar(50) DEFAULT NULL,     -- 型号
  `quantity` float DEFAULT NULL,
  `unit_price_fen` int(11) DEFAULT NULL,     -- 单价快照（分/单位/月）
  `unit` varchar(50) DEFAULT NULL,           -- 单位快照（如 元/GB/月）
  `amount_fen` int(11) DEFAULT NULL,         -- 该项费用（分）
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_bill_item_bill_id` (`bill_id`),
  CONSTRAINT `fk_bill_item_bill` FOREIGN KEY (`bill_id`) REFERENCES `bill` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户钱包余额（可为负：先扣后补）
CREATE TABLE `wallet` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `balance_fen` int(11) DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wallet_user` (`user_id`),
  KEY `fk_wallet_user` (`user_id`),
  CONSTRAINT `fk_wallet_user` FOREIGN KEY (`user_id`) REFERENCES `ab_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 资金流水：充值/消费/转账/退款全部走流水，双向审计
CREATE TABLE `account_log` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `type` varchar(50) NOT NULL,               -- recharge充值 consume消费 transfer_in转入 transfer_out转出 refund退款
  `from_user_id` int(11) DEFAULT NULL,
  `to_user_id` int(11) DEFAULT NULL,
  `amount_fen` int(11) DEFAULT NULL,
  `balance_before_fen` int(11) DEFAULT NULL,
  `balance_after_fen` int(11) DEFAULT NULL,
  `bill_id` int(11) DEFAULT NULL,
  `operator` varchar(100) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `reversed` int(11) NOT NULL DEFAULT 0,     -- 0 正常 / 1 已冲正
  `ref_log_id` int(11) DEFAULT NULL,         -- 冲正流水引用的原流水 id
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_account_log_from_user_id` (`from_user_id`),
  KEY `ix_account_log_to_user_id` (`to_user_id`),
  KEY `ix_account_log_created_on` (`created_on`),
  KEY `ix_account_log_reversed` (`reversed`),
  KEY `fk_al_from` (`from_user_id`),
  KEY `fk_al_to` (`to_user_id`),
  KEY `fk_al_bill` (`bill_id`),
  CONSTRAINT `fk_al_from` FOREIGN KEY (`from_user_id`) REFERENCES `ab_user` (`id`),
  CONSTRAINT `fk_al_to` FOREIGN KEY (`to_user_id`) REFERENCES `ab_user` (`id`),
  CONSTRAINT `fk_al_bill` FOREIGN KEY (`bill_id`) REFERENCES `bill` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扣费单质疑记录：用户质疑 → 管理员处理（改价/驳回/作废）
CREATE TABLE `bill_dispute` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `bill_id` int(11) NOT NULL,                 -- FK bill.id
  `user_id` int(11) DEFAULT NULL,             -- 质疑用户
  `reason` text,                              -- 质疑理由
  `status` varchar(20) DEFAULT 'open',        -- open 待处理 / processed 已处理
  `resolution` varchar(20) DEFAULT NULL,      -- adjust 改价 / reject 驳回 / cancel 作废
  `resolution_note` text,                     -- 处理意见
  `operator` varchar(100) DEFAULT NULL,       -- 处理人
  `created_on` datetime NOT NULL,
  `processed_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_dispute_bill` (`bill_id`),
  KEY `ix_dispute_status` (`status`),
  CONSTRAINT `fk_dispute_bill` FOREIGN KEY (`bill_id`) REFERENCES `bill` (`id`),
  CONSTRAINT `fk_dispute_user` FOREIGN KEY (`user_id`) REFERENCES `ab_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扣费白名单：维度 org 部门 / user 用户 / cluster 集群
CREATE TABLE `bill_whitelist` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `dimension` varchar(20) NOT NULL,           -- org 部门 / user 用户 / cluster 集群
  `value` varchar(200) NOT NULL,              -- 白名单值（部门名/用户名/集群名）
  `note` varchar(200) DEFAULT NULL,           -- 备注
  `enabled` int(11) DEFAULT 1,                -- 1 启用 / 0 停用
  `created_by` varchar(100) DEFAULT NULL,
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_whitelist_dim_value` (`dimension`, `value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扣费规则配置（key-value）
CREATE TABLE `billing_config` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `cfg_key` varchar(50) NOT NULL,             -- min_duration_minutes / month_hours / auto_settle_days / gpu_fallback / enabled ...
  `cfg_value` varchar(200) DEFAULT NULL,
  `cfg_desc` varchar(200) DEFAULT NULL,
  `updated_by` varchar(100) DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cfg_key` (`cfg_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 扣费规则默认配置（管理员可在页面修改）
INSERT INTO `billing_config` (`cfg_key`, `cfg_value`, `cfg_desc`) VALUES
('min_duration_minutes', '10',    '最低付费时长阈值（分钟）'),
('month_hours',          '720',   '月价→小时价折算系数'),
('auto_settle_days',     '7',     '扣费单超时自动扣费天数'),
('gpu_fallback',         'L20',   'node_name 查不到显卡型号时的兜底型号'),
('enabled',              '1',     '扣费功能总开关（0 关闭）'),
('schedule_interval_minutes', '0', '定时扣费周期（分钟，0=关闭，1440=每天，10080=每周）'),
('billing_start_time',   '',      '开始收费时间（YYYY-MM-DD HH:MM:SS，空=从任务创建起全部计费）'),
('last_scheduled_run',   '',      '上次定时扣费执行时间');

-- ---------- 2. 扣费数据源表（外部采集维护，全新环境才建） ----------

-- 任务资源占用历史（按天快照：同一天同一 pod_uid 只记一条，duration 为累计运行小时）
-- 扣费指针字段：billed_duration 只写"最新快照行"（update_at 最大），读取用 MAX 兜底
CREATE TABLE `pod_info_history_v2` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '唯一主键ID',
  `username` varchar(255) DEFAULT NULL COMMENT '提交任务的用户名',
  `k8s_namespace` varchar(255) DEFAULT NULL COMMENT 'k8s命名空间',
  `pod_uid` varchar(255) DEFAULT NULL COMMENT 'Pod的唯一UID',
  `pod_name` varchar(255) DEFAULT NULL COMMENT 'Pod的任务名称 (pod name)',
  `status` varchar(255) DEFAULT NULL COMMENT 'Pod的运行状态 (e.g., Running, Pending, Succeeded)',
  `node_name` varchar(255) DEFAULT NULL COMMENT 'Pod运行所在的节点名称',
  `machine_ip` varchar(255) DEFAULT NULL COMMENT '节点IP',
  `pod_ip` varchar(255) DEFAULT NULL COMMENT 'Pod的IP地址',
  `cluster` varchar(100) DEFAULT NULL COMMENT '集群信息',
  `mem_usage_gb` float DEFAULT NULL COMMENT 'Pod当前内存使用量 (单位: GB)',
  `cpu_usage` float DEFAULT NULL COMMENT 'Pod当前CPU使用量 (单位: cores)',
  `gpu_mem_usage_gb` float DEFAULT NULL COMMENT 'Pod当前GPU显存使用量 (单位: GB)',
  `gpu_usage` float DEFAULT NULL COMMENT 'Pod当前GPU使用率 (百分比, 100=整卡 50=半卡)',
  `mem_limit_gb` float DEFAULT NULL COMMENT 'Pod的内存限制 (单位: GB)',
  `cpu_limit` float DEFAULT NULL COMMENT 'Pod的CPU限制 (单位: cores)',
  `created_at` datetime DEFAULT NULL COMMENT 'Pod的创建时间戳',
  `label` varchar(255) DEFAULT NULL COMMENT 'Pod的标签',
  `duration` varchar(255) DEFAULT NULL COMMENT '任务运行总耗时（小时，累计值）',
  `gpu_type` varchar(255) DEFAULT NULL COMMENT 'GPU显卡型号 (e.g., A100, V100)',
  `tf32` varchar(255) DEFAULT NULL COMMENT '是否启用TF32 (e.g., "True", "False")',
  `gpu_mem_util` varchar(255) DEFAULT NULL COMMENT 'GPU显存的实际使用率 (百分比)',
  `gpu_util` varchar(255) DEFAULT NULL COMMENT 'GPU核心的实际使用率 (百分比)',
  `conversion_rate` varchar(255) DEFAULT NULL COMMENT '业务相关的转化率指标',
  `pending_at` datetime DEFAULT NULL COMMENT '任务进入Pending状态的时间',
  `pending_message` text COMMENT '任务Pending或Waiting的原因',
  `waiting_time` varchar(255) DEFAULT NULL COMMENT 'pending时长',
  `update_at` datetime DEFAULT NULL COMMENT '更新时间戳',
  `details` text COMMENT '详情',
  `billed_duration` float DEFAULT NULL COMMENT '该任务累计已扣费时长（小时，扣费指针：只写最新快照行，读取用MAX）',
  `billed_count` int(11) DEFAULT 0 COMMENT '已扣费次数',
  `last_billed_at` datetime DEFAULT NULL COMMENT '上次扣费时间',
  PRIMARY KEY (`id`),
  KEY `ix_pih_pod_uid_update` (`pod_uid`, `update_at`),
  KEY `ix_pih_username_update` (`username`, `update_at`)
) ENGINE=InnoDB AUTO_INCREMENT=624277 DEFAULT CHARSET=utf8 COMMENT='任务历史占用资源统计';

-- 节点信息表：node_name 与 pod_info_history_v2.node_name 关联，查询显卡型号 gpu_type
-- gpu_type 为 NULL 表示 CPU 节点（无显卡，不收 GPU 费）
CREATE TABLE `all_node_memory` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `node_name` varchar(255) DEFAULT NULL COMMENT '节点名称（关联键）',
  `gpu_type` varchar(100) DEFAULT NULL COMMENT '显卡型号 (e.g., A100, L20, V100)；NULL=CPU节点',
  `gpu_num` int(11) DEFAULT 0 COMMENT '节点显卡数量',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_node_name` (`node_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- 示例节点数据（按实际环境替换）
INSERT INTO `all_node_memory` (`node_name`, `gpu_type`, `gpu_num`) VALUES
('bydai-l20x8-144ip105-r740g', 'L20',  8),
('bydai-a100x4-145ip201-r740g', 'A100', 4),
('bydai-v100x8-146ip88-r730',  'V100', 8),
('bydai-h800x4-148ip66-r740g', 'H800', 4),
('bydai-cpu-147ip66-r740',     NULL,   0);

-- ---------- 3. 示例快照数据（可选，开发调试用） ----------
-- INSERT INTO `pod_info_history_v2` (username, k8s_namespace, pod_uid, pod_name, status, node_name, machine_ip, pod_ip, cluster, mem_usage_gb, cpu_usage, gpu_mem_usage_gb, gpu_usage, mem_limit_gb, cpu_limit, created_at, label, duration, pending_at, update_at) VALUES
-- ('zhoujunchi',  'service', 'aebce7cd-3af8-4509-867f-7211618c37a6', 'atrd2-799bc8c8f-hnvpm',     'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.204', 'dev2', 0, 0, 44.97, 100, 100, 50, '2025-09-12 18:35:07', 'public', '989.37',  '2025-10-23 23:57:23', '2025-10-23 23:57:23'),
-- ('zhoujunchi',  'service', 'aebce7cd-3af8-4509-867f-7211618c37a6', 'atrd2-799bc8c8f-hnvpm',     'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.204', 'dev2', 0, 0, 44.97, 100, 100, 50, '2025-09-12 18:35:07', 'public', '1013.41', '2025-10-24 23:59:25', '2025-10-24 23:59:25'),
-- ('chenjinwen1', 'service', '3ee1e3d7-fbce-4f71-b7cf-b982c3595cbc', 'dota-img-7988f86c6f-j7lpb', 'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.81',  'dev2', 0, 0, 44.97, 100, 40,  32, '2025-09-18 11:47:54', 'public', '852.16',  '2025-10-23 23:57:23', '2025-10-23 23:57:23');

-- ============================================================
-- 生产环境：pod_info_history_v2 已存在时，只执行下面的 ALTER（勿执行 CREATE）
-- ============================================================
-- ALTER TABLE `pod_info_history_v2`
--   ADD COLUMN `billed_duration` float DEFAULT NULL COMMENT '该任务累计已扣费时长（小时，扣费指针）' AFTER `details`,
--   ADD COLUMN `billed_count` int(11) DEFAULT 0 COMMENT '已扣费次数' AFTER `billed_duration`,
--   ADD COLUMN `last_billed_at` datetime DEFAULT NULL COMMENT '上次扣费时间' AFTER `billed_count`;
--
-- ALTER TABLE `pod_info_history_v2`
--   ADD INDEX `ix_pih_pod_uid_update` (`pod_uid`, `update_at`),
--   ADD INDEX `ix_pih_username_update` (`username`, `update_at`);
--
-- -- 存量回填（可选）：把已生效扣费单（非 draft/cancelled/failed）的指针回填，避免重复收费
-- UPDATE pod_info_history_v2 p
-- JOIN (SELECT pod_uid,
--              MAX(deduct_to_hours) AS billed_duration,
--              COUNT(*) AS billed_count,
--              MAX(created_on) AS last_billed_at
--       FROM bill
--       WHERE pod_uid IS NOT NULL AND pod_uid != ''
--         AND status NOT IN ('draft', 'cancelled', 'failed')
--       GROUP BY pod_uid) b ON b.pod_uid = p.pod_uid
-- SET p.billed_duration = b.billed_duration,
--     p.billed_count = b.billed_count,
--     p.last_billed_at = b.last_billed_at;
