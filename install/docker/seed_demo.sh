#!/bin/bash
# cube-studio 扣费模块演示数据播种（幂等，可重复执行）：
#   测试账号 zhoujunchi / chenjinwen1（密码 123456，AI中心，Gamma 角色）
#   all_node_memory 节点示例（L20/A100/V100/H800/CPU）
#   pod_info_history_v2 样例任务快照
# 由 .devcontainer/poststart.sh 在服务拉起后自动调用；也可手动执行：
#   bash install/docker/seed_demo.sh
set -e
cd "$(dirname "$0")"

MYSQL() {
  docker exec -i docker-mysql-1 mysql --default-character-set=utf8 -uroot -padmin "$@"
}

# 等待 MySQL 就绪 + myapp 初始化完成（ab_user 表由 myapp 的 db upgrade 创建）
for i in $(seq 1 60); do
  if docker exec docker-mysql-1 mysqladmin ping -h127.0.0.1 -uroot -padmin >/dev/null 2>&1 \
     && docker exec docker-mysql-1 mysql -uroot -padmin -N -e "SELECT COUNT(*) FROM kubeflow.ab_user" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

MYSQL kubeflow < seed_demo.sql
echo "演示数据播种完成（幂等，已存在则跳过）"
