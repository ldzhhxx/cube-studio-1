-- ============================================================
-- cube-studio 扣费模块演示数据播种（幂等：已存在则跳过，可重复执行）
-- 由 seed_demo.sh 调用（等待 MySQL + myapp 初始化完成后执行）
-- ============================================================

-- 1. 测试账号（密码 123456，FAB werkzeug 哈希）
INSERT INTO ab_user (first_name, last_name, username, password, active, email, created_on, org)
SELECT '周','俊驰','zhoujunchi','pbkdf2:sha256:150000$WLe4ZWAm$96c1754f4e957adf41b6e20d4106d877efcca1e3529799c8af79ebd7b97afc77',1,'zhoujunchi@tencent.com',NOW(),'AI中心'
WHERE NOT EXISTS (SELECT 1 FROM ab_user WHERE username='zhoujunchi');

INSERT INTO ab_user (first_name, last_name, username, password, active, email, created_on, org)
SELECT '陈','锦文','chenjinwen1','pbkdf2:sha256:150000$WLe4ZWAm$96c1754f4e957adf41b6e20d4106d877efcca1e3529799c8af79ebd7b97afc77',1,'chenjinwen1@tencent.com',NOW(),'AI中心'
WHERE NOT EXISTS (SELECT 1 FROM ab_user WHERE username='chenjinwen1');

-- 2. Gamma 角色绑定（普通用户角色）
INSERT INTO ab_user_role (user_id, role_id)
SELECT u.id, r.id FROM ab_user u, ab_role r
WHERE u.username IN ('zhoujunchi','chenjinwen1') AND r.name = 'Gamma'
  AND NOT EXISTS (SELECT 1 FROM ab_user_role ur WHERE ur.user_id = u.id AND ur.role_id = r.id);

-- 3. 节点 → 显卡型号示例（gpu_type 为 NULL = CPU 节点，不收 GPU 费）
INSERT INTO all_node_memory (node_name, gpu_type, gpu_num) VALUES
('bydai-l20x8-144ip105-r740g', 'L20',  8),
('bydai-a100x4-145ip201-r740g', 'A100', 4),
('bydai-v100x8-146ip88-r730',  'V100', 8),
('bydai-h800x4-148ip66-r740g', 'H800', 4),
('bydai-cpu-147ip66-r740',     NULL,   0)
ON DUPLICATE KEY UPDATE gpu_type = VALUES(gpu_type), gpu_num = VALUES(gpu_num);

-- 4. 样例任务快照（按天快照，duration 为累计小时）
INSERT INTO pod_info_history_v2 (username, k8s_namespace, pod_uid, pod_name, status, node_name, machine_ip, pod_ip, cluster, mem_usage_gb, cpu_usage, gpu_mem_usage_gb, gpu_usage, mem_limit_gb, cpu_limit, created_at, label, duration, pending_at, update_at)
SELECT 'zhoujunchi', 'service', 'aebce7cd-3af8-4509-867f-7211618c37a6', 'atrd2-799bc8c8f-hnvpm', 'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.204', 'dev2', 0, 0, 44.97, 100, 100, 50, '2025-09-12 18:35:07', 'public', '989.37', '2025-10-23 23:57:23', '2025-10-23 23:57:23'
WHERE NOT EXISTS (SELECT 1 FROM pod_info_history_v2 WHERE pod_uid = 'aebce7cd-3af8-4509-867f-7211618c37a6');

INSERT INTO pod_info_history_v2 (username, k8s_namespace, pod_uid, pod_name, status, node_name, machine_ip, pod_ip, cluster, mem_usage_gb, cpu_usage, gpu_mem_usage_gb, gpu_usage, mem_limit_gb, cpu_limit, created_at, label, duration, pending_at, update_at)
SELECT 'zhoujunchi', 'service', 'aebce7cd-3af8-4509-867f-7211618c37a6', 'atrd2-799bc8c8f-hnvpm', 'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.204', 'dev2', 0, 0, 44.97, 100, 100, 50, '2025-09-12 18:35:07', 'public', '1013.41', '2025-10-24 23:59:25', '2025-10-24 23:59:25'
WHERE NOT EXISTS (SELECT 1 FROM pod_info_history_v2 WHERE pod_uid = 'aebce7cd-3af8-4509-867f-7211618c37a6' AND update_at = '2025-10-24 23:59:25');

INSERT INTO pod_info_history_v2 (username, k8s_namespace, pod_uid, pod_name, status, node_name, machine_ip, pod_ip, cluster, mem_usage_gb, cpu_usage, gpu_mem_usage_gb, gpu_usage, mem_limit_gb, cpu_limit, created_at, label, duration, pending_at, update_at)
SELECT 'chenjinwen1', 'service', '3ee1e3d7-fbce-4f71-b7cf-b982c3595cbc', 'dota-img-7988f86c6f-j7lpb', 'Running', 'bydai-l20x8-144ip105-r740g', '10.0.144.105', '10.244.31.81', 'dev2', 0, 0, 44.97, 100, 40, 32, '2025-09-18 11:47:54', 'public', '852.16', '2025-10-23 23:57:23', '2025-10-23 23:57:23'
WHERE NOT EXISTS (SELECT 1 FROM pod_info_history_v2 WHERE pod_uid = '3ee1e3d7-fbce-4f71-b7cf-b982c3595cbc');
