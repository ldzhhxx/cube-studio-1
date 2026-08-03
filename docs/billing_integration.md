# 计费系统（Billing）内网集成指南

> 适用：把计费模块集成到你目前的内网平台部署。
> 打包文件：`billing_module.zip`（本目录），内含全部新增/修改文件。
> 详细设计见 `docs/billing.md`。

---

## 一、模块简介

**外部算费，平台记账**：费用由外部费用清单系统计算，通过 HTTP 接口推送到平台；平台负责记账、扣余额、充值、转账、对账展示。

- 三张数据表：`bill`（费用明细，pod_name 幂等）/ `wallet`（用户钱包，单位分）/ `account_log`（资金流水，支持冲正）
- 两个前端页面：计费控制台（管理员）/ 我的账单（普通用户），**零外部依赖**（无 CDN），内网可正常渲染
- 余额拦截：任务发起前检查余额，低于 `BILLING_MIN_BALANCE` 禁止运行

---

## 二、文件清单（zip 内容）

| 文件 | 类型 | 说明 |
|---|---|---|
| `myapp/models/model_billing.py` | **新增** | 数据模型 Bill / Wallet / AccountLog |
| `myapp/views/view_billing.py` | **新增** | 全部接口 + 两个页面路由（约 800 行） |
| `myapp/static/billing/console.html` | **新增** | 计费控制台页面（管理员） |
| `myapp/static/billing/my.html` | **新增** | 我的账单页面（普通用户） |
| `myapp/migrations/versions/1ee3bd719439_add_billing_tables.py` | **新增** | 迁移①：建三张表 |
| `myapp/migrations/versions/2a9c4f8e1b5d_add_billing_indexes.py` | **新增** | 迁移②：索引 |
| `myapp/migrations/versions/8d3e2f1a6c9b_add_account_log_reverse.py` | **新增** | 迁移③：冲正字段（reversed/ref_log_id） |
| `myapp/views/__init__.py` | **修改** | 追加 `from . import view_billing` |
| `myapp/__init__.py` | **修改** | 登录白名单加 `/billing/api` |
| `myapp/views/home.py` | **修改** | 顶级菜单"计费中心"（按角色显示子项） |
| `myapp/views/view_pipeline.py` | **修改** | run_pipeline 余额拦截 |
| `install/docker/config.py` | **修改** | 新增 `BILLING_TOKEN` / `BILLING_MIN_BALANCE` 配置 |
| `install/docker/docker-compose.yml` | **修改** | redis 镜像调整 + host.docker.internal（仅 docker-compose 部署需要） |
| `docs/billing.md` | **新增** | 接口/行为文档 |
| `docs/billing_seed.sql` | **新增** | 种子数据（测试用户/钱包/流水，可选导入） |

---

## 三、集成步骤

### Step 1：合并代码

**新增文件**直接放入对应目录：

```
myapp/models/model_billing.py
myapp/views/view_billing.py
myapp/static/billing/console.html
myapp/static/billing/my.html
myapp/migrations/versions/1ee3bd719439_add_billing_tables.py
myapp/migrations/versions/2a9c4f8e1b5d_add_billing_indexes.py
myapp/migrations/versions/8d3e2f1a6c9b_add_account_log_reverse.py
```

**修改文件**需要与你的版本合并（共 5 处，都很小）：

1. `myapp/views/__init__.py` —— 末尾加一行：
   ```python
   from . import view_billing
   ```
2. `myapp/__init__.py` —— `check_login` 的白名单数组加一项：
   ```python
   static_urls=['/static','/logout','/login','/health','/wechat','/billing/api']
   ```
3. `myapp/views/home.py` —— **只需加 2 行**，不依赖你 home.py 里的任何现有变量（setting/links 等一律不用管，你的改动原样保留）：
   ```python
   # 在 @expose('/menu') 函数的 return jsonify(menu) 之前插入：
   # 计费中心：所有登录用户可见；普通用户只有"我的账单"，管理员另有"计费控制台"
   from myapp.views.view_billing import billing_menu_items
   menu.insert(0, billing_menu_items())
   ```
   > 计费菜单已封装为自包含函数 `billing_menu_items()`（在 view_billing.py 内），按登录用户角色自动返回子项（管理员：计费控制台+我的账单；普通用户：我的账单）。
4. `myapp/views/view_pipeline.py` —— `run_pipeline` 函数开头加余额拦截（约 10 行）：
   ```python
   # 计费余额拦截
   try:
       from myapp.models.model_billing import Wallet
       if pipeline.created_by and pipeline.created_by.id:
           wallet = db.session.query(Wallet).filter_by(user_id=pipeline.created_by.id).first()
           if wallet and wallet.balance_fen < conf.get('BILLING_MIN_BALANCE', -10000):
               flash('余额不足...', 'warning')
               return redirect('/pipeline_modelview/web/%s' % pipeline.id)
   except Exception as e:
       print('check balance error: %s' % e)
   ```
5. `install/docker/config.py` —— 追加配置（见 Step 3）。若你的部署不用 `install/docker/config.py`，把配置加到你实际的 config 文件即可。

### Step 2：数据库建表（二选一）

**方式 A（推荐）：用 Alembic 迁移**
把 3 个迁移文件放入你的 `myapp/migrations/versions/` 目录，重启应用（或执行 `myapp db upgrade`）。会自动创建三张表 + 索引 + 冲正字段。
> ⚠️ 迁移文件按版本链执行（1ee3bd719439 → 2a9c4f8e1b5d → 8d3e2f1a6c9b），三个文件必须一起放入，不能只放部分。

**方式 B：手动建表**
执行 `docs/billing_seed.sql` 的开头部分（`DROP TABLE ...; CREATE TABLE ...;` 到流水表结束），然后手动把 alembic 版本标记到最新，避免重启时 `db upgrade` 报错：
```sql
INSERT INTO alembic_version (version_num) VALUES ('8d3e2f1a6c9b')
ON DUPLICATE KEY UPDATE version_num = '8d3e2f1a6c9b';
```

> 表名：`bill` / `wallet` / `account_log`，全部 utf8mb4。三张表与 `ab_user`（平台用户表）有外键关联。

### Step 3：配置项

在你平台的 config 中追加：

```python
# 外部费用清单推送接口的鉴权 token（必改！）
BILLING_TOKEN = '换成你自己的随机长字符串'
# 余额下限（分），低于该值禁止发起新的任务运行
BILLING_MIN_BALANCE = -10000   # -100 元
```

同时确认 `ADMIN_USER` 配置包含管理员用户名（决定谁能看到"计费控制台"）。

### Step 4：前端静态文件

`myapp/static/billing/` 目录（console.html / my.html）随应用静态目录提供即可。两种部署都满足：
- docker-compose 部署：`myapp/` 已挂载，无需额外操作
- k8s/其他部署：确认 `myapp/static/` 目录被包含在镜像或挂载中

页面由后端路由 `/billing/console`（管理员）和 `/billing/my`（登录用户）返回，iframe 嵌入前端菜单，**无需改动 React 前端代码、无需重新构建前端**。

### Step 5：重启验证

重启应用后按"四、验证清单"逐项检查。

---

## 四、验证清单

```bash
TOKEN='你的BILLING_TOKEN'

# 1. 页面（管理员会话打开）
curl -b <cookie> http://你的平台/billing/console        # 200 计费控制台
curl -b <cookie> http://你的平台/billing/my             # 200 我的账单

# 2. 推送接口（外部系统调用方式）
# 无 token → 401
curl -X POST http://你的平台/billing/api/push -H "Content-Type: application/json" \
  -d '[{"pod_name":"test-pod-1","username":"admin","amount_fen":100}]'
# 带 token → 200, result: [{"pod_name":"test-pod-1","result":"settled"}]
curl -X POST http://你的平台/billing/api/push -H "X-Billing-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"pod_name":"test-pod-1","username":"admin","amount_fen":100}]'

# 3. 余额被扣（admin 钱包 -100 分）
curl -b <cookie> http://你的平台/billing/api/my_balance

# 4. 对账查询
curl -H "X-Billing-Token: $TOKEN" "http://你的平台/billing/api/list?pod_name=test-pod-1"

# 5. 菜单（登录后）
curl -b <cookie> http://你的平台/myapp/menu   # 顶级菜单第一个是"计费中心"
```

---

## 五、与外部计费系统的对接

外部系统在任务结束后推送明细（按 pod 幂等，重复推送只修正不重复扣费）：

```bash
curl -X POST http://你的平台/billing/api/push \
  -H "X-Billing-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{
    "username": "zhangsan",          # ab_user 中的用户名
    "task_name": "train-resnet50",
    "pod_name": "resnet50-x7f2k",    # 幂等键，重复推送只修正数据
    "cpu": 4, "memory": 16, "gpu_num": 1, "gpu_memory": 16,
    "duration_seconds": 3600,
    "amount_fen": 1234,              # 费用（分）
    "start_time": "2026-08-03 10:00:00",
    "end_time": "2026-08-03 11:00:00"
  }]'
```

返回 `result`：`settled` 已入账扣费 / `updated` 重复推送已修正（金额变化自动差额补扣/退回）/ `settled_no_user` 用户名对不上未扣费 / `skip` 缺 pod_name / `reject` 金额非法。

---

## 六、内网环境注意事项

1. **BILLING_TOKEN 必须修改**为强随机串（默认值是占位符，存在被冒用风险）。
2. **前端页面零外部依赖**：console.html / my.html 不使用任何 CDN，内网无外网也能正常渲染。
3. **组织数据**：组织树按 `ab_user.org` 的"中心-部门"格式（如 `软件与数字化中心-AI技术应用部`）自动分层展示；单段 org 的用户不显示在组织树中（仍参与计费）。几百个中心/部门也支持（面板可收起 + 搜索）。
4. **账号密码**：`docs/billing_seed.sql` 导入的测试用户密码为 `test123`，admin 为 `admin`——**生产环境导入种子数据前请评估**；不导入种子数据则全部功能正常，只是没有演示用户。
5. **余额拦截**：只有"有钱包记录且低于下限"的用户才会被拦截；新用户（无钱包）先跑后扣，跑完才进入欠费管控。
6. **docker-compose 部署**：`install/docker/docker-compose.yml` 的改动（redis 镜像、extra_hosts）仅为本地开发调试用；生产部署请按你现有方式，只需保证 `myapp` 代码更新 + `db upgrade` 执行。
7. **撤销/冲正**：管理员可撤销手动账单、冲正充值/转账流水（审计留痕，不物理删除）；外部推送的账单不可手动撤销（由推送系统修正，保证对账一致）。

---

## 七、常见问题

| 问题 | 处理 |
|---|---|
| 重启后 `db upgrade` 报错找不到迁移 | 三个迁移文件必须一起放入 `myapp/migrations/versions/`；或按方式 B 手动标记 alembic_version |
| 菜单里没有"计费中心" | home.py 合并遗漏；确认 `menu.insert(0, billing)` 已加且 Python 无语法错误 |
| 页面 404 | `myapp/static/billing/` 目录未随应用发布；检查静态目录挂载/镜像 |
| push 接口 401 | BILLING_TOKEN 未配置或请求头名不对（`X-Billing-Token`） |
| 推送返回 `settled_no_user` | 账单里的 username 在 ab_user 中不存在（注意大小写/空格） |
| 余额没有变化 | 推送金额为 0 或用户匹配失败；查 `account_log` 流水确认 |
| 控制台只显示"我的账单" | 当前登录用户不在 `ADMIN_USER` 配置中 |
