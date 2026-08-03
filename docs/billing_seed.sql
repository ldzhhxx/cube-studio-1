-- ============================================================
-- 计费系统（Billing）建表脚本（纯建表，无任何测试数据）
-- 生成时间：2026-08-03
--
-- 执行说明：
--   1. 计费表（bill / wallet / account_log / price_config / bill_item）会【先删除再重建】，幂等可重复执行
--   2. 本脚本【不包含任何数据】：价格、GPU 型号、用户数据请在前端页面自行添加
--      （控制台「计费标准」面板可添加 CPU/内存价格与 GPU 型号；用户由平台注册）
--   3. account_log 含冲正字段（reversed / ref_log_id）
-- ============================================================

-- ---------- 1. 删除并重建计费表 ----------
DROP TABLE IF EXISTS `account_log`;
DROP TABLE IF EXISTS `bill`;
DROP TABLE IF EXISTS `wallet`;
DROP TABLE IF EXISTS `price_config`;

CREATE TABLE `price_config` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `item_key` varchar(50) NOT NULL,           -- 计费项标识：cpu / memory / gpu / storage ...
  `item_name` varchar(100) DEFAULT NULL,     -- 显示名：CPU / 内存 / GPU / 存储
  `item_type` varchar(20) DEFAULT 'quantity',-- quantity 数量型 / model 型号型（分组）
  `parent_key` varchar(50) DEFAULT NULL,     -- 父计费项标识（型号分组下的子型号）
  `price_fen` int(11) DEFAULT NULL,          -- 数量型单价（分/单位/月）
  `unit` varchar(50) DEFAULT NULL,           -- 如 元/核/月
  `sort_order` int(11) DEFAULT NULL,
  `enabled` int(11) DEFAULT 1,
  `updated_by` varchar(100) DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_price_resource` (`item_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;





CREATE TABLE `bill` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `pod_name` varchar(200) NOT NULL,
  `task_name` varchar(200) DEFAULT NULL,
  `run_id` varchar(200) DEFAULT NULL,
  `username` varchar(100) DEFAULT NULL,
  `user_id` int(11) DEFAULT NULL,
  `org` varchar(200) DEFAULT NULL,
  `cpu` float DEFAULT NULL,
  `memory` float DEFAULT NULL,
  `gpu_num` float DEFAULT NULL,
  `gpu_type` varchar(50) DEFAULT NULL,
  `gpu_memory` float DEFAULT NULL,
  `duration_seconds` int(11) DEFAULT NULL,
  `amount_fen` int(11) DEFAULT NULL,
  `start_time` datetime DEFAULT NULL,
  `end_time` datetime DEFAULT NULL,
  `status` varchar(50) DEFAULT NULL,
  `source` varchar(50) DEFAULT NULL,
  `created_on` datetime NOT NULL,
  `updated_on` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_bill_pod_name` (`pod_name`),
  KEY `ix_bill_username` (`username`),
  KEY `ix_bill_org` (`org`),
  KEY `ix_bill_created_on` (`created_on`),
  KEY `fk_bill_user` (`user_id`),
  CONSTRAINT `fk_bill_user` FOREIGN KEY (`user_id`) REFERENCES `ab_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE `bill_item` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `bill_id` int(11) NOT NULL,                -- FK bill.id
  `item_key` varchar(50) DEFAULT NULL,
  `item_name` varchar(100) DEFAULT NULL,
  `option_key` varchar(50) DEFAULT NULL,     -- 型号
  `quantity` float DEFAULT NULL,
  `unit_price_fen` int(11) DEFAULT NULL,     -- 单价快照（分/单位/月）
  `amount_fen` int(11) DEFAULT NULL,         -- 该项费用（分）
  `created_on` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_bill_item_bill_id` (`bill_id`),
  CONSTRAINT `fk_bill_item_bill` FOREIGN KEY (`bill_id`) REFERENCES `bill` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


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


CREATE TABLE `account_log` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `type` varchar(50) NOT NULL,
  `from_user_id` int(11) DEFAULT NULL,
  `to_user_id` int(11) DEFAULT NULL,
  `amount_fen` int(11) DEFAULT NULL,
  `balance_before_fen` int(11) DEFAULT NULL,
  `balance_after_fen` int(11) DEFAULT NULL,
  `bill_id` int(11) DEFAULT NULL,
  `operator` varchar(100) DEFAULT NULL,
  `remark` varchar(500) DEFAULT NULL,
  `reversed` int(11) NOT NULL DEFAULT 0,
  `ref_log_id` int(11) DEFAULT NULL,
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
