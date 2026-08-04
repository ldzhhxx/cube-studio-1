# cube-studio 一键恢复指南（AI 助手操作手册）

> **给 AI 助手**：用户说"看 STARTUP.md 启动 / 看这个文件"时，按本文档从第 1 步**顺序执行**，全部完成后按"第 7 步汇报格式"向用户汇报。不要跳过验证、不要重复排查已修复问题。
>
> **给用户**：新开 codespace 后服务与演示数据会自动拉起（.devcontainer 配置），只需告诉 AI"看 STARTUP.md"，它会完成验证和功能演示。

---

## 1. 环境自检（服务应已自动拉起）

打开终端后先确认：

```bash
docker ps -a
# 期望：docker-mysql-1 / docker-myapp-1 / docker-redis-1 / docker-frontend-1 / docker-worker-1 / docker-beat-1 全部 Up
# （beat 可能因 restart:no 已退出，属正常；worker 首次启动需 1-2 分钟拉取 celery 依赖）

curl -s -o /dev/null -w '%{http_code}\n' http://localhost/frontend/
# 期望：200

curl -s -o /dev/null -w '%{http_code}\n' http://localhost/billing/deduct
# 期望：401（未登录属正常，说明路由存在）
```

**如果服务没起来**（poststart 未执行或失败）：

```bash
cd /workspaces/cube-studio-1/install/docker
docker compose up -d
# myapp 首次启动会自动：建库建表（含全部扣费迁移）、创建 admin/admin、初始化演示数据
# 等 myapp 日志出现 "Running on http://0.0.0.0:80/" 再继续（约 1-3 分钟）
```

**如果演示数据没播种**（幂等，可重复执行）：

```bash
bash /workspaces/cube-studio-1/install/docker/seed_demo.sh
```

## 2. 数据层验证（迁移 + 表结构）

```bash
# 迁移链应完整：运行最新迁移（幂等，全部带 has_table 守卫）
docker exec docker-myapp-1 bash -c 'cd /home/myapp && myapp db upgrade 2>&1 | tail -2'

# 核心表应存在
docker exec docker-mysql-1 mysql -uroot -padmin kubeflow -e "SHOW TABLES LIKE 'bill%'; SHOW TABLES LIKE 'billing%'; SHOW TABLES LIKE 'pod_info%'; SHOW TABLES LIKE 'all_node%';"

# 扣费配置默认值
docker exec docker-mysql-1 mysql -uroot -padmin kubeflow -e "SELECT cfg_key, cfg_value FROM billing_config;"

# 演示数据
docker exec docker-mysql-1 mysql -uroot -padmin kubeflow -e "SELECT username, org FROM ab_user WHERE username IN ('zhoujunchi','chenjinwen1'); SELECT node_name, gpu_type FROM all_node_memory; SELECT pod_name, duration FROM pod_info_history_v2;"
# 期望：2 个用户（AI中心）、5 个节点（含 1 个 NULL=CPU 节点）、3 条样例快照
```

## 3. 端口转发验证（Codespace 访问）

```bash
gh codespace ports -c "$CODESPACE_NAME"
# 80 端口必须为 public；若为 private：
gh codespace ports visibility 80:public -c "$CODESPACE_NAME"
```

访问地址：`https://<codespace名>-80.app.github.dev/frontend/`（admin / admin）

## 4. 扣费功能验证（API 全链路冒烟）

用 Flask test client 走完整流程（复用下列脚本，失败即修复后再继续）：

```python
# 容器内执行：docker exec -it docker-myapp-1 bash -c 'cd /home/myapp && python -c "..."'
# 1) admin 登录 + 执行扣费（应生成 2-3 张 draft 单，金额与规格匹配）
# 2) 一键推送 → 状态变 pushed
# 3) zhoujunchi 登录：我的扣费单看到 pushed 单 → 同意 → settled，钱包余额减少、流水出现
# 4) chenjinwen1 登录：对另一张单质疑（附理由）→ 管理员在扣费单管理看到 disputed → 驳回 → settled
# 5) 重复执行扣费 → 全部增量=0 跳过（不重复收费）
```

验证要点：
- 扣费金额 = 快照时长 × 单价（L20 = 2000 元/卡/月 ÷ 720h；GPU 卡数 = gpu_usage/100）
- 扣费单带 `pod_uid` + 计费区间（deduct_from_hours → deduct_to_hours）
- 我的Pod记录能看到已扣时长/扣费次数

## 5. 页面功能演示（给用户看效果）

1. **管理员**（admin/admin）→ 左侧导航 **计费中心 → 扣费管理**：
   - ① 规则配置：可设置"开始收费时间"（只收该时间之后的时长）、超时自动扣费天数
   - ② 执行扣费：点"执行一轮扣费"→ 生成扣费单 → 批次记录显示生成/跳过统计
   - ③ 扣费单管理：推送（单选/一键全推）、明细展开、处理质疑（改价/驳回/作废）
   - ④ 白名单：添加用户/部门/集群白名单
   - ⑤ 任务快照查询：按用户/显卡/集群筛选，看到已扣时长/扣费次数
2. **用户**（zhoujunchi / 123456）→ **我的账单**：
   - 我的扣费单：同意（立即扣款）/ 质疑（附理由）
   - 我的Pod记录：任务列表 + 按天快照明细

## 6. 常见问题速查

| 症状 | 处理 |
|---|---|
| nginx `[emerg] host not found in upstream "myapp"` | 已修复（depends_on），若出现：`docker compose up -d --force-recreate frontend` |
| Codespace 转发 URL 打不开 / 跳登录页 | 端口可见性变 private：`gh codespace ports visibility 80:public -c $CODESPACE_NAME` |
| 扣费执行生成 0 张单 | 正常情况：演示数据如果已结算过则增量=0。可重置：删掉 bill/bill_item/account_log/wallet 后重新执行 |
| 演示数据乱码（AIä¸­å¿ƒ） | 用 utf8 连接重写 org：`mysql --default-character-set=utf8` |
| mysql 端口冲突 | 旧的独立 mysql 容器占用 3306 时：`docker stop mysql && docker rm mysql` 后 compose up |

## 7. 汇报格式（全部完成后向用户汇报）

```
✅ 服务状态：6 容器正常，页面 200
✅ 数据层：全部迁移通过，演示数据就位（2 用户 / 5 节点 / 3 快照）
✅ 功能验证：执行扣费 → 推送 → 同意/质疑 → 结算 全链路通过
✅ 访问地址：https://<codespace名>-80.app.github.dev/frontend/
   管理员 admin/admin ｜ 演示用户 zhoujunchi / 123456
```
