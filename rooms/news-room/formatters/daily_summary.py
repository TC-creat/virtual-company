"""
微信日报精简版 —— 适合推送到微信/企业微信/飞书的短文本日报

特点：
    - 纯文本 + emoji 标记，不支持 Markdown
    - 每项最多 4 行（标题行 + 摘要行 + 来源行 + 空行分隔）
    - 自动从 top_items 截取 TOP_K_SUMMARY 条
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List

from models import NewsItem
from config import TOP_K_SUMMARY

logger = logging.getLogger(__name__)

# 来源类型 → Emoji 映射
SOURCE_EMOJI: dict[str, str] = {
    "paper": "\U0001F4C4",       # 📄
    "repo": "\U0001F4E6",        # 📦
    "community": "\U0001F4AC",   # 💬
    "media": "\U0001F4E1",       # 📡
}
FALLBACK_EMOJI = "\U0001F4F0"    # 📰


def _build_stats_line(stats: dict) -> str:
    """构建统计概要行。"""
    total = stats.get("total_raw", 0)
    filtered = stats.get("total_filtered", 0)
    src_count = stats.get("source_count", 0)
    date_str = stats.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return f"采集：{src_count}源 | {total}条原始 → {filtered}条入选"


def _shorten_url(url: str, max_len: int = 45) -> str:
    """截断 URL 为可读长度。"""
    if not url or len(url) <= max_len:
        return url or ""
    return url[: max_len - 3] + "..."


def _get_one_line_summary(item: NewsItem) -> str:
    """获取一行摘要：优先取 deepseek.one_line_summary，回退到 summary_raw 截断。"""
    ds = item.deepseek or {}
    summary = ds.get("one_line_summary", "") or ""
    if not summary:
        summary = (item.summary_raw or "")[:80]
    # 去除换行
    return summary.replace("\n", " ").replace("\r", " ").strip()


def render_wechat_text(items: List[NewsItem], stats: Dict) -> str:
    """生成微信日报精简版文本。

    Args:
        items: 已评分排序的条目（将被截取前 TOP_K_SUMMARY 条）
        stats: 统计字典，至少包含 total_raw / total_filtered / source_count / date

    Returns:
        格式化后的纯文本日报
    """
    top_k = items[:TOP_K_SUMMARY]
    date_str = stats.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    lines: List[str] = []
    # ── 标题行 ──
    lines.append(f"\U0001F4F0 AI日报 | {date_str}")
    lines.append("")
    lines.append(_build_stats_line(stats))
    lines.append("---")
    lines.append("")

    # ── 每条内容 ──
    for i, item in enumerate(top_k, start=1):
        st = item.source_type or ""
        emoji = SOURCE_EMOJI.get(st.lower(), FALLBACK_EMOJI)

        # 第1行：序号 + emoji + 标题
        title = (item.title or "").strip().replace("\n", " ").replace("\r", " ")
        lines.append(f"{i}. [{emoji}] {title}")

        # 第2行：一行摘要
        summary = _get_one_line_summary(item)
        if summary:
            lines.append(f"   {summary}")

        # 第3行：来源 + 短链接
        source = (item.source or "").strip()
        url_short = _shorten_url(item.url or "")
        lines.append(f"   来源：{source} | {url_short}")

        # 空行分隔
        lines.append("")

    # ── 尾部 ──
    lines.append("---")
    lines.append("由 AI 新闻采集系统自动生成")

    return "\n".join(lines)
