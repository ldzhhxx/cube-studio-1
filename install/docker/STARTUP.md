# cube-studio 启动指南（新环境开箱即用）

> 本文档用于在新初始化的 Codespace（或本地 docker 环境）中快速拉起全套服务。
> **给 AI 助手的提示**：按"启动步骤 → 验证 → 常见问题"顺序执行即可，不要重复排查已修复过的问题。

## 服务组成

一条 `docker compose` 拉起 4 个服务（依赖顺序已由 compose 保证，见 `docker-compose.yml`）：

```
mysql(健康检查通过) → myapp(后端 Flask，自动建库建表/初始化数据) → frontend(nginx，80 端口)
redis 独立启动
```

- `myapp`：Flask 后端，端口 80（容器内），`STAGE: dev` 开发模式自动热更新
- `frontend`：nginx 反向代理，宿主机端口 **80**，静态前端来自 `../../myapp/static/appbuilder/frontend`
- `mysql`：数据持久化在 `./data/mysql`（已 gitignore），root 密码 `admin`，数据库 `kubeflow`

## 启动步骤

### 1. 确认 docker 可用

```bash
docker info >/dev/null 2>&1 && echo OK || echo "等待 docker daemon 就绪..."
```

### 2. 拉起全套服务（一条命令）

```bash
cd /workspaces/cube-studio-1/install/docker   # 仓库实际挂载路径
docker compose up -d
```

首次启动自动完成（无需手工建库/授权）：
- MySQL 初始化 + 数据目录挂载
- `myapp` 等 MySQL 健康后启动，自动执行建库建表、创建 **admin/admin** 账号、初始化演示数据
- frontend 等 myapp 起来后再启动 nginx（不会出现 nginx 找不到 upstream 的报错）

### 3. Codespace 端口转发（已由 .devcontainer 配置，自动执行）

- 80 端口已配置 `public` 可见性（GitHub 转发层对 private 端口强制登录，会导致页面打不开）
- `.devcontainer/poststart.sh` 在容器启动时自动执行上面第 2 步

## 访问地址

| 环境 | 地址 | 账号 |
|---|---|---|
| 本机 | http://localhost/frontend/ | admin / admin |
| Codespace | https://`<codespace名>`.github.dev 的 PORTS 面板 → 80 端口 URL（形如 `https://xxx-80.app.github.dev/frontend/`） | admin / admin |

注意：根路径 `/` 会 301 跳转到 `/frontend/`，属正常行为。

## 启动后验证（正常状态长这样）

```bash
docker ps -a
# 期望：docker-mysql-1 / docker-myapp-1 / docker-redis-1 / docker-frontend-1 全部 Up

docker logs docker-frontend-1
# 期望：空日志（没有 "[emerg] host not found in upstream"）

docker logs docker-myapp-1 2>&1 | tail -5
# 期望：最后出现 "Running on http://0.0.0.0:80/"

curl -s -o /dev/null -w '%{http_code}' http://localhost/frontend/
# 期望：200
```

## 常见问题

### 1. nginx 报 `[emerg] host not found in upstream "myapp"`
启动竞争问题，已通过 `depends_on` 修复。若再次出现：确认 docker-compose.yml 中 `frontend` 有 `depends_on: [myapp]`，然后 `docker compose up -d --force-recreate frontend`。

### 2. Codespace 转发 URL 打不开 / 401 / 跳登录页
端口可见性变成了 `private`。修复：
```bash
gh codespace ports visibility 80:public -c $CODESPACE_NAME
```
或 VS Code PORTS 面板右键 80 → Port Visibility → Public。

### 3. 后端数据库连不上
```bash
docker logs docker-myapp-1 | grep -i -A2 "mysql\|connect"
```
等 `docker-mysql-1` 健康检查通过后 myapp 才会启动（healthcheck 已配置）。也可手动验证：
```bash
docker exec docker-mysql-1 mysqladmin ping -h127.0.0.1 -uroot -padmin
```

### 4. 想重置全部数据（回到初始状态）
```bash
docker compose down && rm -rf data/mysql && docker compose up -d
```

## 常用命令

```bash
docker compose ps                    # 查看服务状态
docker logs -f docker-myapp-1        # 跟踪后端日志
docker logs -f docker-frontend-1     # 跟踪 nginx 日志
docker compose restart myapp         # 重启单个服务
docker compose up -d --force-recreate  # 强制重建
docker compose down                  # 停止全部（保留数据卷）
```

## 代码修改如何生效

- 后端代码：`../../myapp/` 挂载进容器，`STAGE: dev` 下 Flask debug 模式自动热更新，改完直接刷新页面
- 前端代码：修改 `myapp/frontend` 源码 → `yarn build` 编译（或容器内 `STAGE: build`）→ 静态产物挂载到 nginx
- 配置文件：`./config.py`、`./entrypoint.sh`、`./kubeconfig` 均从宿主机挂载，改完 `docker compose restart myapp`
