# 计费系统（Billing）

## 整体方案

- **外部算费，平台记账**：费用由外部维护的费用清单系统计算，通过接口推送给平台；平台只负责记账、扣余额、充值、转账、对账展示。
- **计费维度**：按任务的 cpu 核数、内存 GB、显存 GB 计费（外部系统计算），平台记录资源数与运行时长做展示/统计。
- **后处理方式**：任务运行结束后，外部系统将明细推送到平台，平台按 `pod_name` 幂等入账。
- **欠费策略**：先跑后扣，余额允许为负；低于 `BILLING_MIN_BALANCE`（默认 -10000 分 = -100 元）时禁止发起新的任务运行。
- `ab_user.org` 为用户的部门，账单明细冗余 `org`，支持按部门汇总统计。

## 数据表

| 表 | 说明 |
|---|---|
| `bill` | 费用明细，一个 pod 一条，`pod_name` 唯一（幂等键） |
| `wallet` | 用户钱包余额，单位**分**（整数，避免浮点误差） |
| `account_log` | 资金流水：充值/消费/转账双向审计（transfer_out + transfer_in） |

## 对外接口（供外部费用清单系统调用）

鉴权：请求头 `X-Billing-Token`，值在平台 config 的 `BILLING_TOKEN` 中配置。

### 1. 推送费用明细

```
POST /billing/api/push
X-Billing-Token: <token>
Content-Type: application/json
```

请求体为明细数组，支持一次推送多条：

```json
[
  {
    "username": "zhangsan",
    "task_name": "train-resnet50",
    "pod_name": "resnet50-x7f2k",
    "run_id": "argo-xxx",
    "cpu": 4,
    "memory": 16,
    "gpu_num": 1,
    "gpu_memory": 16,
    "duration_seconds": 3600,
    "amount_fen": 1234,
    "start_time": "2026-08-03 10:00:00",
    "end_time": "2026-08-03 11:00:00"
  }
]
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `pod_name` | 是 | pod 名，**幂等去重键**，重复推送只修正数据不重复扣费 |
| `username` | 是 | 归属用户名（平台 ab_user 中的 username） |
| `amount_fen` | 是 | 费用金额（分） |
| `cpu` `memory` `gpu_num` `gpu_memory` | 否 | 资源数：cpu核数、内存GB、GPU卡数、显存GB |
| `duration_seconds` | 否 | 运行时长（秒） |
| `start_time` `end_time` | 否 | 运行起止时间 |

返回：

```json
{"message": "ok", "status": 200, "result": [
  {"pod_name": "resnet50-x7f2k", "result": "settled"},
  {"pod_name": "xxx", "result": "settled_no_user"}
]}
```

`result` 取值：`settled` 已入账扣费 / `updated` 重复推送已修正 / `settled_no_user` 入账但用户名对不上（未扣费）/ `skip` 缺 pod_name / `reject` 金额非法（负数或超上限 100 万元）/ `error` 单条数据异常（已逐笔容错，不影响同批其他数据）。

**商用行为约定**：
- 请求必须带 `Content-Type: application/json`，否则 415。
- `username` 自动去首尾空格；`amount_fen` 必须为非负整数（0~1亿分），负数直接 `reject` 不入账。
- **重复推送金额变化会结算差额**：金额变大补扣（`consume` 流水，备注"费用修正补扣"），金额变小退回（新增 `refund` 流水类型，备注"费用修正退回"），不会重复扣全额。
- 扣费/充值时对钱包行加锁（`SELECT ... FOR UPDATE`），并发推送同用户不会竞态漏扣；同 pod 并发推送按幂等处理。

### 2. 对账查询（外部核对平台入账状态）

```
GET /billing/api/list?username=xxx&pod_name=yyy&start_time=2026-08-01&end_time=2026-08-03&limit=200
```

或 POST 传同名字段 JSON。鉴权：`X-Billing-Token`（或平台管理员会话）。

返回：`{"message":"ok","status":200,"result":{"count":N,"bills":[{...}]}}`，每条含入账状态 `status`。

## 平台内部接口

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /billing/api/recharge` | 管理员会话或 token | `{"username":"zhangsan","amount_fen":10000,"remark":"..."}` 充值 |
| `POST /billing/api/transfer` | 管理员会话或 token | `{"from_username":"a","to_username":"b","amount_fen":100,"remark":"..."}` 转账（双向流水） |
| `GET /billing/api/my_balance` | 登录用户 | 我的余额（含 `status`：normal/overdue/blocked，及 SQL 聚合的累计消费/充值/退款） |
| `GET /billing/api/my_bills` | 登录用户 | 我的费用明细（支持 `page`/`page_size` 分页） |
| `GET /billing/api/my_logs` | 登录用户 | 我的资金流水（支持 `page`/`page_size` 分页） |
| `GET /billing/api/admin/stats` | 管理员或 token | 平台汇总：用户/部门数、总余额、累计充值消费、今日消费、部门消费排行 `org_consume`、组织树 `centers` |
| `GET /billing/api/admin/wallets` | 管理员或 token | 全部用户余额（SQL 分页+排序：`page/page_size/sort_by/order`，`sort_by` 支持 balance/username/org/updated；`username` 模糊搜索；`center` 按中心筛选） |
| `GET /billing/api/admin/bills` | 管理员或 token | 全部费用明细（筛选+分页+排序，`sort_by` 支持 amount/created_on，`center` 按中心筛选） |
| `GET /billing/api/admin/logs` | 管理员或 token | 全部资金流水（筛选+分页+排序，`sort_by` 支持 amount/type/created_on） |
| `GET /billing/api/users` | 管理员或 token | 搜索 ab_user 用户（`?keyword=xxx`，充值/转账选择用户用） |
| `POST /billing/api/deduct` | 管理员或 token | 手动扣费，**支持单个对象或数组批量**：`{"username":"a","amount_fen":100,"remark":"...","task_name":"...","pod_name":"选填"}`；逐笔容错，返回 `{count, ok, failed, results[]}`；自动生成 `manual-用户名-时间戳` 的 pod_name（重复会拒绝）；写 bill 账本（source=manual）+ consume 流水 |
| `GET /billing/api/admin/export` | 管理员会话 | CSV 导出（`?kind=bills|logs` + 同列表筛选参数，`limit` 默认 10 万可调，带 BOM 供 Excel 识别中文） |
| `POST /billing/api/admin/bill/<id>/reverse` | 管理员会话 | 撤销手动账单（回退余额+refund 流水，状态置 reversed；外部账单不可撤，由推送修正） |
| `POST /billing/api/admin/log/<id>/reverse` | 管理员会话 | 冲正流水：recharge 扣回 / transfer_out 双向撤销（转入扣回+转出退回，关联 transfer_in 一并标记） |

**写操作要求**：`recharge`/`transfer`/`push` 必须带 `Content-Type: application/json`（CSRF 防护，浏览器跨站表单无法伪造）；单笔金额上限 100 万元（`MAX_TRANSFER_FEN`）。

## 页面

**计费中心**为顶级菜单（所有登录用户可见），子项按角色区分：

- 管理员：**计费控制台**（`/billing/console`）——统计卡片、**组织架构树**（org 按 `-` 拆分为"中心-部门"两级，点中心展开部门、点部门行下内联展开成员/明细/流水）、余额列表/费用明细/资金流水（按中心筛选 + **分页（10/20/50/100 每页）** + **表头点击排序** + CSV 导出）、充值/扣费（单笔/批量）/转账（模态框，可搜索 ab_user 用户）、**账单撤销/流水冲正**（操作列按钮+确认框，审计留痕）
- 所有用户：**我的账单**（`/billing/my`）——余额大卡片、欠费状态提示（normal/overdue/blocked）、累计消费/充值/退款统计、我的明细与流水（分页）

## 数据表

`bill`/`account_log` 高频查询字段已加索引（`username`/`org`/`created_on`/外键），迁移文件 `2a9c4f8e1b5d`。

## 配置项

在 `install/docker/config.py` 中：

```python
BILLING_TOKEN = os.getenv('BILLING_TOKEN', 'change-me-to-your-own-token')  # 外部推送鉴权token，上线前务必修改
BILLING_MIN_BALANCE = -10000   # 余额下限（分），低于该值禁止发起新任务
```

## 余额拦截

发起任务运行（`/pipeline_modelview/run_pipeline/<id>`）时校验运行者钱包余额：低于 `BILLING_MIN_BALANCE` 则拦截并提示充值。
