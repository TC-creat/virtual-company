"""
Hermes 消息推送模块
负责将每日精选的内容推送到 Hermes 网关，并在本地留存归档。

Hermes cron 的 --no-agent 模式会捕获脚本 stdout 并投递到
deliver 目标（微信/Telegram/...），因此此模块的核心职责是
将日报文本输出到 stdout，同时本地存档。
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from models import NewsItem
from config import ARTIFACTS_DIR

logger = logging.getLogger(__name__)


def send_text(text: str) -> None:
    """将文本落盘归档并打印到 stdout。

    Hermes cron --no-agent 模式会将 stdout 内容作为消息体
    投递到 deliver 目标。
    """
    if not text or not text.strip():
        logger.warning("推送文本为空，跳过")
        return

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # 本地归档
    archive_path = ARTIFACTS_DIR / "daily_push.txt"
    timestamp = datetime.now(timezone.utc).isoformat()
    header = f"\n{'=' * 60}\n# {timestamp}\n{'=' * 60}\n"
    try:
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write(header)
            f.write(text)
            f.write("\n")
    except OSError as exc:
        logger.warning("写入归档文件失败 %s: %s", archive_path, exc)

    # stdout 输出 → Hermes cron deliver 捕获
    print(text)


def send_daily(items: list[NewsItem], stats: dict, summary_text: str = "") -> None:
    """推送日报：落盘 + stdout。

    Args:
        items: 日报条目列表 (NewsItem 实例)。
        stats: 统计信息 dict。
        summary_text: 已格式化的精简版文本。为空则用 items 简单拼接。
    """
    if summary_text:
        body = summary_text
    else:
        # 降级：简单拼接
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [f"AI 日报 {today_str}", "", f"共 {len(items)} 条", ""]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.title}")
            ds = (item.deepseek or {}).get("one_line_summary", "")
            if ds:
                lines.append(f"   {ds}")
            lines.append(f"   {item.source} | {item.url}")
            lines.append("")
        body = "\n".join(lines)

    send_text(body)
