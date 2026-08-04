#!/bin/bash
# cube-studio Codespace 启动钩子：
# 等待 docker daemon 就绪后，一键拉起 redis + mysql + myapp + frontend 全套服务。
# 服务首次启动会自动初始化数据库（建库、建表、admin 账号、演示数据），无需手工操作。
# 启动完成后访问：https://<codespace名>-80.app.github.dev/frontend/  （admin / admin）
set -x

# 1. 等待 docker daemon（codespace 容器启动后 daemon 可能还要几秒）
for i in $(seq 1 30); do
  if docker info >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# 2. 定位仓库里的 compose 目录（codespace 默认挂载在 /workspaces/<仓库名>）
COMPOSE_DIR="$(ls -d /workspaces/*/install/docker 2>/dev/null | head -1)"
if [ -z "$COMPOSE_DIR" ]; then
  echo "ERROR: 未找到 install/docker 目录，请确认仓库已挂载" >&2
  exit 1
fi

# 3. 拉起全套服务（幂等：已运行的服务会跳过）
cd "$COMPOSE_DIR"
docker compose up -d

# 4. 确认 80 端口转发为 public（GitHub 转发层对 private 端口强制登录，会打不开页面）
if command -v gh >/dev/null 2>&1; then
  CODESPACE="${CODESPACE_NAME:-$(gh codespace list --json name -q '.[0].name' 2>/dev/null)}"
  [ -n "$CODESPACE" ] && gh codespace ports visibility 80:public -c "$CODESPACE" >/dev/null 2>&1 || true
fi

echo "cube-studio 服务已启动：访问 https://$(hostname)-80.app.github.dev/frontend/ （admin / admin）"
