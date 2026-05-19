#!/bin/bash
# AI新闻采集系统 - 定时任务安装脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3 || which python)"

echo "========================================"
echo " AI新闻采集系统 - 环境初始化"
echo "========================================"
echo ""

# 检查Python
echo "[1/5] 检查 Python..."
$PYTHON --version || { echo "Python3 未安装"; exit 1; }

# 安装依赖
echo "[2/5] 安装依赖..."
cd "$SCRIPT_DIR"
pip install -r requirements.txt -q

# 创建目录
echo "[3/5] 创建数据目录..."
mkdir -p data/{raw,artifacts,logs}

# 检查环境变量
echo "[4/5] 检查环境变量..."
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "  ⚠ DEEPSEEK_API_KEY 未设置 (LLM增强功能不可用，不影响基础采集)"
fi
if [ -z "$GITHUB_TOKEN" ]; then
    echo "  ⚠ GITHUB_TOKEN 未设置 (GitHub Search API增强不可用)"
fi

# 设置定时任务
echo "[5/5] 设置定时任务..."
CRON_JOB="30 7 * * * cd $SCRIPT_DIR && $PYTHON agents/daily_agent.py >> data/logs/cron.log 2>&1"

# 检查是否已存在
if crontab -l 2>/dev/null | grep -q "daily_agent.py"; then
    echo "  定时任务已存在，跳过"
else
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "  定时任务已添加: 每天 7:30 执行"
fi

echo ""
echo "========================================"
echo " 安装完成"
echo " 手动运行: $PYTHON agents/daily_agent.py"
echo " 试运行:   $PYTHON agents/daily_agent.py --dry-run"
echo "========================================"
