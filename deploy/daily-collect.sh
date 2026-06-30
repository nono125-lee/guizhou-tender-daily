#!/bin/bash
# 每日标讯自动采集脚本
# 本地时间 15:03 执行（夏令时约北京时间 6:03，冬令时约 7:03）
set -euo pipefail

PROJECT_DIR="$HOME/Documents/标讯"
LOG_DIR="$PROJECT_DIR/deploy/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/collect-$(date +%Y%m%d).log"
exec 2>&1 | tee -a "$LOG_FILE"

echo "=== 每日标讯采集开始 $(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S' ) ==="
echo "本地时间: $(date)"

cd "$PROJECT_DIR"

# 1. 采集图文广告
echo ""
echo "--- 图文广告采集 ---"
PYTHONPATH=src python3 -m tender_agent.site update || echo "⚠️ 图文广告采集失败"

# 2. 统一采集施工、超长期计划、关联、测试并发布
echo ""
echo "--- 统一施工机会雷达 ---"
PYTHONPATH=src python3 -m tender_agent.unified_site update --publish

echo ""
echo "=== 采集部署完成 $(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S') ==="
