-- ============================================================
-- 计费系统（Billing）种子数据初始化脚本
-- 生成时间：2026-08-03
-- 内容：42 个用户（含中心-部门组织）+ 钱包余额 + 资金流水
--
-- 执行说明：
--   1. 计费三表（bill / wallet / account_log）会【先删除再重建】，幂等可重复执行
--   2. ab_user 为平台用户主表，【不会删除】；已存在的用户（如 admin）自动跳过（INSERT IGNORE）
--   3. 用户密码已含哈希，导入后可直接用 test123 / admin 登录
--   4. 建议在测试环境执行；生产环境请确认不影响真实用户
-- ============================================================

-- ---------- 1. 删除并重建计费表 ----------
DROP TABLE IF EXISTS `account_log`;
DROP TABLE IF EXISTS `wallet`;
DROP TABLE IF EXISTS `bill`;

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

-- ---------- 2. 用户（已存在则跳过） ----------

INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (1,'admin','admin','admin','pbkdf2:sha256:150000$qKsPHvWL$d131589d1770697c8c00121820b370bf9f8b125d98a1a631d393ab39eaa3933a',1,'admin@tencent.com','2026-08-03 13:31:36',7,0,'2026-08-03 10:42:56','2026-08-03 10:42:56',NULL,NULL,NULL);
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (3,'test','user','testuser','pbkdf2:sha256:150000$QXfy4tHM$57132c27f16dfed291a1f4accc6b7ba6a8166ad78c4e418e06c5104c5ac43123',1,'testuser@test.com','2026-08-03 13:22:42',2,0,'2026-08-03 13:02:38','2026-08-03 13:02:38',NULL,NULL,NULL);
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (5,'张伟','','zhangwei','pbkdf2:sha256:150000$c80ykS6V$3b25d2d93cb0cfaadb3a2192b464690203cb161f090fa4208df5818dc70a5039',1,'zhangwei@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (6,'李强','','liqiang','pbkdf2:sha256:150000$XqSz1SuD$dc6e8b3881d0dc266ee44e16b0edc9ed82a49d3461caef9e9bbbb3a95879340d',1,'liqiang@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (7,'王芳','','wangfang','pbkdf2:sha256:150000$GQr3vo1o$15c6420cd62295e86c6d3e525c26664c937b19d34eca38d29170bd415937a76e',1,'wangfang@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (8,'刘洋','','liuyang','pbkdf2:sha256:150000$77Mel3xn$4b03e132462d4afe6776900fcfff14b8156536aa5fc759540c8dd0454cd38b15',1,'liuyang@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (9,'陈静','','chenjing','pbkdf2:sha256:150000$67B4uhbY$248bf48c743e5237a91b4623408e0b56e07970142bd4dadbcab91281f6c05d0a',1,'chenjing@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'算法部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (10,'赵磊','','zhaolei','pbkdf2:sha256:150000$jSgvMQzL$ca05be40a63b8fd3f5443a02e9d1c427e7da4c0b85a1d785a1e326e616d6d97f',1,'zhaolei@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'算法部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (11,'孙丽','','sunli','pbkdf2:sha256:150000$8R2tB5kG$48868692e8b375e0b68289443fda354d2df0c02cf5e39365bb9fbd6cba00efc7',1,'sunli@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'算法部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (12,'周宇','','zhouyu','pbkdf2:sha256:150000$JF2dMM1I$7dc0ee7cdda982e60c5f525c39fe975fba75c5c84b2610341c2c2d6576acee51',1,'zhouyu@test.com',NULL,NULL,NULL,'2026-08-03 13:11:42','2026-08-03 13:11:42',NULL,NULL,'算法部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (13,'吴鑫','','wuxin','pbkdf2:sha256:150000$H23lgDnm$22d30c9be786da8ac1848eac3c7b208315c1c01b479471997eaf59676345d1de',1,'wuxin@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'数据部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (14,'徐明','','xuming','pbkdf2:sha256:150000$yngNxkKu$8df81eec63c2b2d3703af351756ced60eeb0b2c133ab3c5d337d3f4bdcdab7e2',1,'xuming@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'数据部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (15,'朱华','','zhuhua','pbkdf2:sha256:150000$uhSc2TyL$311c73dab20369809634d57e24525d4c2b796635aabad4a13a08007fa435297e',1,'zhuhua@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'数据部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (16,'胡刚','','hugang','pbkdf2:sha256:150000$VfokD67V$45158f6a0ee0ae8c0728c05fc9e3cd5d9f5bc376f232186577da90d48277a903',1,'hugang@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'数据部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (17,'高飞','','gaofei','pbkdf2:sha256:150000$oXiGRdgm$811f103884ae62856bd1402c86743aecbdd6cf0a8baa3db73df0a432848d45c8',1,'gaofei@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (18,'林琳','','linlin','pbkdf2:sha256:150000$yOavzhJ5$0d516b3e5c0cc72fed1f8b48babd8346f41f371a4b08e221ea472d1917af6348',1,'linlin@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (19,'何俊','','hejun','pbkdf2:sha256:150000$POGATsY7$e6932574a00061adf3bfea1cab7421bc9f9588062de82572160dd9003069e838',1,'hejun@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (20,'郭宇','','guoyu','pbkdf2:sha256:150000$LHLTEzSZ$e64fe6cf8a6e6ffe6c133b4075dd24012646696e50f76a477207924afe164734',1,'guoyu@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (21,'罗雪','','luoxue','pbkdf2:sha256:150000$zk9TETOK$6eb0e6467a442f6d069948d7c97fd7266492450c915083bc6b360cff16f2352e',1,'luoxue@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'运营部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (22,'宋娟','','songjuan','pbkdf2:sha256:150000$KGNIG6Qj$089e284bd07ecb7a4e5efed5fac1d279fb0af13898f91f5cdd01cf9babc9a6b6',1,'songjuan@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'运营部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (23,'邓超','','dengchao','pbkdf2:sha256:150000$EhsjPWZI$095ab6656a39a55ac338a0a744ed63e858e80ff1f18c07238ff5e2bef9bb7eef',1,'dengchao@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'运营部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (24,'黄敏','','huangmin','pbkdf2:sha256:150000$ryGLNw7J$40ac28c2b6991ba92afc812c97923fae2c6358a4f7ca16bebc82e680c099fffd',1,'huangmin@test.com',NULL,NULL,NULL,'2026-08-03 13:11:43','2026-08-03 13:11:43',NULL,NULL,'运营部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (28,'张三','','zhangsan','pbkdf2:sha256:150000$jPvxgMZ8$a4925cffc1adf96ed73597cc7083705f768a22b39d3363674364b54b3d67e57c',1,'zhangsan@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'软件与数字化中心-AI技术应用部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (29,'李四','','lisi','pbkdf2:sha256:150000$dXQ0Sm1H$c49d7f1ea3c881a0db11074c39372e9165abcf2513cfe1abcaa5fb2dcef9ac19',1,'lisi@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'软件与数字化中心-AI技术应用部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (30,'王五','','wangwu','pbkdf2:sha256:150000$6GokQBco$38b25ed86159021a54b91dcb8190dccbdd7c92c13b31c80ae5fa817b568163cc',1,'wangwu@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'软件与数字化中心-数据平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (31,'赵六','','zhaoliu','pbkdf2:sha256:150000$h4ZBPkYm$9410d48dd3654206b467d0d56ff928d2f48b09eec19c3d86fca02ad1995c9fb2',1,'zhaoliu@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'软件与数字化中心-数据平台部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (32,'钱七','','qianqi','pbkdf2:sha256:150000$zSmnIxdy$10b690e6301c1004cd2dbe295dd62b774e6de3f37f5faad25165f71bbc9b5d24',1,'qianqi@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'基础设施中心-云计算部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (33,'孙八','','sunba','pbkdf2:sha256:150000$O79SHoyn$82d3bef91d9753891fa4dff80e04c4bbf7552d61e28551881e30dd3a0c631aed',1,'sunba@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'基础设施中心-云计算部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (34,'周九','','zhoujiu','pbkdf2:sha256:150000$LdZ3oDYp$49176daea819219fab0ee4aace21e1431538db89dc2d392be69314bd6a80a79b',1,'zhoujiu@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'基础设施中心-网络工程部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (35,'吴十','','wushi','pbkdf2:sha256:150000$AqQrDvMu$8207c3be399108f787ea24ba55c8f11d6d4265d76bb5ff332c5c480e7ca023bf',1,'wushi@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'基础设施中心-网络工程部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (36,'郑飞','','zhengfei','pbkdf2:sha256:150000$NXPK8fXx$a08e92b9ecd6ea6fdff054ef22c4b3e0c65c41bf7ec0a33fccd4d7d197973e25',1,'zhengfei@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'数据智能中心-算法研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (37,'冯远','','fengyuan','pbkdf2:sha256:150000$lBqbSY1q$07cd6da369eb00e06d9979e3691a7a7c207e21bd727dfb0fcd94c89eebf396ad',1,'fengyuan@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'数据智能中心-算法研发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (38,'陈浩','','chenhao','pbkdf2:sha256:150000$8uHM60i2$a8877857c0e2952689e4ec20e2706ee92382f9fba30b8bde4d2d250358bfa288',1,'chenhao@test.com',NULL,NULL,NULL,'2026-08-03 13:55:24','2026-08-03 13:55:24',NULL,NULL,'数据智能中心-数据分析部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (39,'杨瑞','','yangrui','pbkdf2:sha256:150000$583Xp3Xl$2f1e7007ce72ad7f294b946a7834bf7b83e7b5c5f4badf476300b53e3fdaafa0',1,'yangrui@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'数据智能中心-数据分析部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (40,'张涛','','zhangtao','pbkdf2:sha256:150000$4asuuGlV$3cecf5d1d918efa159ef8ffd0f30a0edbe12597738661a923474a757a8f2c264',1,'zhangtao@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'产品研发中心-前端开发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (41,'刘鹏','','liupeng','pbkdf2:sha256:150000$2EZck3oV$2bac93de418195fcf69c1453d2800218c433f3d2cdc7854c2f037e162e42e9df',1,'liupeng@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'产品研发中心-前端开发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (42,'梁静','','liangjing','pbkdf2:sha256:150000$RpPB9L8N$c39900717d02026dc9cb4238a4142e82bc4ba0af78b0be9a85f9d89aee0ae519',1,'liangjing@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'产品研发中心-后端开发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (43,'谢燕','','xieyan','pbkdf2:sha256:150000$aUCahsuD$2b130ec6fcbc333ba31c7a9bba2860b076f8f695e25ae01c742b18710647505b',1,'xieyan@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'产品研发中心-后端开发部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (44,'唐丽','','tangli','pbkdf2:sha256:150000$KXWZAoY4$daa1d3cb7bbe3af903f6ed88c18397dfaa193762e53f511b812f5a4531099e62',1,'tangli@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'数字化运营中心-运营支撑部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (45,'曹伟','','caowei','pbkdf2:sha256:150000$iiQVGpga$10731b841e367260b65daccf31a270c1b0ae245bb9e7f701042339dcd96ea049',1,'caowei@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'数字化运营中心-运营支撑部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (46,'袁磊','','yuanlei','pbkdf2:sha256:150000$8CevC1nX$0f0085c87c71bae8a0b9bffebf299c75d67b2c85c2650873a530f9bad3ad020c',1,'yuanlei@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'数字化运营中心-质量保障部');
INSERT IGNORE INTO `ab_user` (`id`, `first_name`, `last_name`, `username`, `password`, `active`, `email`, `last_login`, `login_count`, `fail_login_count`, `created_on`, `changed_on`, `created_by_fk`, `changed_by_fk`, `org`) VALUES (47,'肖青','','xiaoqing','pbkdf2:sha256:150000$pZvq4BhB$6c0a85c7a45ee144eef2da44b4bc904616443276beec3dbeda9e0ae1b91f3531',1,'xiaoqing@test.com',NULL,NULL,NULL,'2026-08-03 13:55:25','2026-08-03 13:55:25',NULL,NULL,'数字化运营中心-质量保障部');

-- ---------- 3. 用户-角色关联（已存在则跳过） ----------

INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (1,1,1);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (2,3,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (3,5,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (4,6,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (5,7,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (6,8,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (7,9,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (8,10,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (9,11,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (10,12,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (11,13,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (12,14,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (13,15,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (14,16,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (15,17,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (16,18,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (17,19,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (18,20,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (19,21,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (20,22,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (21,23,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (22,24,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (24,28,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (25,29,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (26,30,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (27,31,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (28,32,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (29,33,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (30,34,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (31,35,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (32,36,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (33,37,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (34,38,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (35,39,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (36,40,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (37,41,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (38,42,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (39,43,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (40,44,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (41,45,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (42,46,3);
INSERT IGNORE INTO `ab_user_role` (`id`, `user_id`, `role_id`) VALUES (43,47,3);

-- ---------- 4. 钱包余额 ----------

INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (1,1,6600,'2026-08-03 13:24:57');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (2,3,7000,'2026-08-03 13:02:52');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (3,5,47339,'2026-08-03 13:51:55');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (4,6,38522,'2026-08-03 13:51:55');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (5,7,17883,'2026-08-03 13:30:33');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (6,8,31786,'2026-08-03 13:11:42');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (7,9,49553,'2026-08-03 13:41:51');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (8,10,42757,'2026-08-03 13:11:42');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (9,11,35133,'2026-08-03 13:11:42');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (10,12,34691,'2026-08-03 13:33:38');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (11,13,40491,'2026-08-03 13:15:12');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (12,14,32470,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (13,15,14749,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (14,16,43439,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (15,17,5383,'2026-08-03 13:41:51');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (16,18,47200,'2026-08-03 13:35:00');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (17,19,21395,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (18,20,30402,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (19,21,34142,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (20,22,27971,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (21,23,8872,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (22,24,6637,'2026-08-03 13:11:43');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (25,28,48365,'2026-08-03 14:08:05');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (26,29,41469,'2026-08-03 14:08:05');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (27,30,26429,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (28,31,17731,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (29,32,21431,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (30,33,13620,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (31,34,40818,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (32,35,20912,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (33,36,24868,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (34,37,23437,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (35,38,42367,'2026-08-03 13:55:24');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (36,39,47165,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (37,40,19615,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (38,41,22881,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (39,42,18408,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (40,43,27831,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (41,44,29213,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (42,45,41493,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (43,46,16607,'2026-08-03 13:55:25');
INSERT IGNORE INTO `wallet` (`id`, `user_id`, `balance_fen`, `updated_on`) VALUES (44,47,32627,'2026-08-03 13:55:25');

-- ---------- 5. 资金流水 ----------

INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (2,'recharge',NULL,1,500,3100,3600,NULL,'token','测试充值','2026-08-03 13:01:27',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (3,'recharge',NULL,3,10000,0,10000,NULL,'token','测试','2026-08-03 13:02:52',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (4,'transfer_out',3,1,3000,10000,7000,NULL,'token','测试转账','2026-08-03 13:02:52',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (5,'transfer_in',3,1,3000,3600,6600,NULL,'token','测试转账','2026-08-03 13:02:52',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (6,'recharge',NULL,5,47339,0,47339,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (7,'recharge',NULL,6,38522,0,38522,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (8,'recharge',NULL,7,17883,0,17883,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (9,'recharge',NULL,8,31786,0,31786,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (10,'recharge',NULL,9,49553,0,49553,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (11,'recharge',NULL,10,42757,0,42757,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (12,'recharge',NULL,11,35133,0,35133,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (13,'recharge',NULL,12,34691,0,34691,NULL,'init','测试用户初始余额','2026-08-03 13:11:42',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (14,'recharge',NULL,13,31691,0,31691,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (15,'recharge',NULL,14,32470,0,32470,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (16,'recharge',NULL,15,14749,0,14749,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (17,'recharge',NULL,16,43439,0,43439,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (18,'recharge',NULL,17,5383,0,5383,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (19,'recharge',NULL,18,47200,0,47200,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (20,'recharge',NULL,19,21395,0,21395,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (21,'recharge',NULL,20,30402,0,30402,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (22,'recharge',NULL,21,34142,0,34142,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (23,'recharge',NULL,22,27971,0,27971,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (24,'recharge',NULL,23,8872,0,8872,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (25,'recharge',NULL,24,6637,0,6637,NULL,'init','测试用户初始余额','2026-08-03 13:11:43',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (26,'recharge',NULL,13,8800,31691,40491,NULL,'admin','前端链路测试','2026-08-03 13:15:12',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (44,'recharge',NULL,28,48365,0,48365,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (45,'recharge',NULL,29,41469,0,41469,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (46,'recharge',NULL,30,26429,0,26429,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (47,'recharge',NULL,31,17731,0,17731,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (48,'recharge',NULL,32,21431,0,21431,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (49,'recharge',NULL,33,13620,0,13620,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (50,'recharge',NULL,34,40818,0,40818,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (51,'recharge',NULL,35,20912,0,20912,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (52,'recharge',NULL,36,24868,0,24868,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (53,'recharge',NULL,37,23437,0,23437,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (54,'recharge',NULL,38,42367,0,42367,NULL,'init','测试用户初始余额','2026-08-03 13:55:24',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (55,'recharge',NULL,39,47165,0,47165,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (56,'recharge',NULL,40,19615,0,19615,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (57,'recharge',NULL,41,22881,0,22881,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (58,'recharge',NULL,42,18408,0,18408,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (59,'recharge',NULL,43,27831,0,27831,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (60,'recharge',NULL,44,29213,0,29213,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (61,'recharge',NULL,45,41493,0,41493,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (62,'recharge',NULL,46,16607,0,16607,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
INSERT INTO `account_log` (`id`, `type`, `from_user_id`, `to_user_id`, `amount_fen`, `balance_before_fen`, `balance_after_fen`, `bill_id`, `operator`, `remark`, `created_on`, `reversed`, `ref_log_id`) VALUES (63,'recharge',NULL,47,32627,0,32627,NULL,'init','测试用户初始余额','2026-08-03 13:55:25',0,NULL);
