"""
完整日报 —— 支持 Markdown 格式和纯文本格式两种输出

Markdown 日报包含：
    - H1 标题 & 采集概况统计表
    - 每条新闻的详细卡片（链接、摘要、热度指标、分项评分、标签）
    - 失败源列表
    - 生成时间戳

典型用法：
    from formatters.daily_detail import render_markdown, render_plain_text
    md_report = render_markdown(top_items, stats, failures)
    txt_report = render_plain_text(top_items, stats)
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import NewsItem

logger = logging.getLogger(__name__)

# 来源类型 → 可读标签
SOURCE_TYPE_LABEL: dict[str, str] = {
    "paper": "论文",
    "repo": "仓库",
    "community": "社区",
    "media": "媒体",
}


def _fmt_stat_table(stats: dict) -> str:
    """渲染采集概况统计表（Markdown 格式）。"""
    lines = [
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 数据源数量 | {stats.get('source_count', 0)} |",
        f"| 原始采集 | {stats.get('total_raw', 0)} |",
        f"| 过滤后 | {stats.get('total_filtered', 0)} |",
        f"| 入选日报 | {stats.get('total_selected', 0)} |",
    ]
    # 可选：各源明细
    per_source = stats.get("per_source", {})
    if per_source and isinstance(per_source, dict):
        lines.append("")
        lines.append("| 来源 | 采集 | 入选 |")
        lines.append("|------|------|------|")
        for src, counts in per_source.items():
            lines.append(f"| {src} | {counts.get('raw', 0)} | {counts.get('selected', 0)} |")
    return "\n".join(lines)


def _fmt_failures(failures: Optional[dict]) -> str:
    """渲染失败源列表。"""
    if not failures:
        return ""
    lines = ["", "---", "## 采集异常"]
    for src, err in failures.items():
        lines.append(f"- **{src}**: {err or '未知错误'}")
    return "\n".join(lines)


def _fmt_tags(tags: List[str]) -> str:
    """格式化标签列表为逗号分隔字符串。"""
    if not tags:
        return "—"
    return ", ".join(f"`{t}`" for t in tags)


def _fmt_metric(key: str, metrics: dict) -> str:
    """安全读取 metrics 中的数值。"""
    return str(metrics.get(key, 0))


def render_markdown(items: List[NewsItem], stats: Dict, failures: Optional[Dict] = None) -> str:
    """生成完整 Markdown 日报。

    Args:
        items: 已评分排序的条目列表
        stats: 统计字典（source_count / total_raw / total_filtered / total_selected / date / per_source）
        failures: 可选，失败源字典 {源名称: 错误信息}

    Returns:
        完整的 Markdown 字符串
    """
    date_str = stats.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    sections: List[str] = []

    # ── H1 标题 ──
    sections.append(f"# AI 日报 | {date_str}")
    sections.append("")
    sections.append(_fmt_stat_table(stats))
    sections.append("")
    sections.append("---")
    sections.append("")

    # ── 每条详细卡片 ──
    for i, item in enumerate(items, start=1):
        st = item.source_type or ""
        label = SOURCE_TYPE_LABEL.get(st.lower(), st)

        title = (item.title or "").strip().replace("\n", " ").replace("\r", " ")
        sections.append(f"## {i}. [{label}] {title}")
        sections.append("")

        # 来源与链接
        url = item.url or ""
        sections.append(f"- **来源**: {item.source or '—'} | **链接**: [{url}]({url})")
        if item.canonical_url and item.canonical_url != url:
            sections.append(f"  - 规范化URL: `{item.canonical_url}`")
        if item.author:
            sections.append(f"  - **作者**: {item.author}")

        # 摘要
        summary = (item.summary_raw or "").strip()
        if summary:
            # 限制摘要显示长度，太长截断
            if len(summary) > 200:
                summary = summary[:200] + "..."
            sections.append(f"- **摘要**: {summary}")

        # DeepSeek 摘要（如有）
        ds = item.deepseek or {}
        one_line = (ds.get("one_line_summary", "") or "").strip()
        if one_line:
            sections.append(f"- **AI摘要**: {one_line}")

        # 热度指标
        metrics = item.metrics or {}
        sections.append(
            f"- **热度**: score={_fmt_metric('score', metrics)}, "
            f"comments={_fmt_metric('comments', metrics)}, "
            f"stars_today={_fmt_metric('stars_today', metrics)}"
        )

        # 分项评分
        quality = item.quality or {}
        sections.append(
            f"- **评分**: 权威={quality.get('source_authority', 0):.2f}, "
            f"时效={quality.get('recency', 0):.2f}, "
            f"热度={quality.get('heat', 0):.2f}, "
            f"规则总分={quality.get('rule_score', 0):.2f}"
        )
        llm_score = quality.get("llm_score", 0)
        if llm_score:
            sections.append(f"  - LLM评分: {llm_score:.2f}, 最终分={quality.get('final_score', 0):.2f}")

        # 标签
        sections.append(f"- **标签**: {_fmt_tags(item.tags or [])}")

        # DeepSeek 技术要点（如有）
        tech_points = ds.get("technical_points", [])
        if tech_points:
            formatted_pts = " | ".join(tech_points[:5])
            sections.append(f"- **技术要点**: {formatted_pts}")

        # 跨源证据
        evidence = item.evidence or {}
        ev_sources = [k for k, v in evidence.items() if v]
        if ev_sources:
            sections.append(f"- **跨源覆盖**: {', '.join(ev_sources)}")

        sections.append("")

    # ── 失败源列表 ──
    if failures:
        sections.append(_fmt_failures(failures))
        sections.append("")

    # ── 页脚 ──
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sections.append("---")
    sections.append(f"*由 AI 新闻采集系统自动生成 | {now_str}*")
    sections.append("")

    return "\n".join(sections)


def render_plain_text(items: List[NewsItem], stats: Dict) -> str:
    """纯文本格式日报 —— 作为 Markdown 渲染不可用时的 fallback 方案。

    格式与 daily_summary.render_wechat_text 类似但更详细：
        - 包含评分和标签
        - 保留完整 URL
        - 无 emoji
    """
    date_str = stats.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    lines: List[str] = []

    lines.append(f"AI日报 | {date_str}")
    lines.append("=" * 50)
    lines.append(f"采集源: {stats.get('source_count', 0)} | "
                 f"原始: {stats.get('total_raw', 0)} | "
                 f"过滤后: {stats.get('total_filtered', 0)}")
    lines.append("")

    for i, item in enumerate(items, start=1):
        title = (item.title or "").strip().replace("\n", " ")
        lines.append(f"{i}. {title}")
        lines.append(f"   来源: {item.source or '—'} | {item.url or '—'}")
        summary = (item.summary_raw or "").strip()[:120]
        if summary:
            lines.append(f"   摘要: {summary}")
        quality = item.quality or {}
        metrics = item.metrics or {}
        lines.append(
            f"   评分: 权威={quality.get('source_authority', 0):.2f} | "
            f"热度={quality.get('heat', 0):.2f} | "
            f"总分={quality.get('final_score', 0):.2f}"
        )
        lines.append("")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append("-" * 50)
    lines.append(f"由 AI 新闻采集系统自动生成 | {now_str}")
    return "\n".join(lines)
