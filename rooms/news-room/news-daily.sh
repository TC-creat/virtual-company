#!/usr/bin/env bash
# Hermes cron 包装脚本 - AI新闻日报
# 由 Hermes cron --no-agent 模式调用，stdout 会被捕获并投递到微信
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 加载 DeepSeek API Key 等环境变量
if [ -f "$HOME/.hermes/.env" ]; then
    set -a
    source "$HOME/.hermes/.env"
    set +a
fi

# Claude 环境（claude_env.sh 定义 DEEPSEEK 兼容端点）
if [ -f "$HOME/ubuntu_package/claude_config/claude_env.sh" ]; then
    source "$HOME/ubuntu_package/claude_config/claude_env.sh"
fi

exec python3 agents/daily_agent.py --skip-push
