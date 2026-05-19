"""
过滤模块 —— 对原始采集结果执行多级粗过滤

过滤顺序：
    1. filter_by_time_window   — 超出时间窗口的丢弃
    2. filter_by_ai_relevance  — 不含AI关键词的丢弃
    3. filter_blacklisted      — 命中域名/标题黑名单的丢弃
    4. filter_low_quality      — 无标题或无URL的丢弃
    5. run_filters             — 串联上述四步并打印统计
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from models import NewsItem
from config import TIME_WINDOW_HOURS, AI_KEYWORDS, TITLE_BLACKLIST, DOMAIN_BLACKLIST

logger = logging.getLogger(__name__)


def filter_by_time_window(items: List[NewsItem], hours: int = TIME_WINDOW_HOURS) -> List[NewsItem]:
    """过滤时间窗口：只保留最近 N 小时内的条目。

    若 published_at 为空或解析失败则保留该条目 —— 宁可放过也不误杀不确定的数据。
    """
    if not hours or hours <= 0:
        return items

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    kept: List[NewsItem] = []

    for item in items:
        pub_str = item.published_at
        # 论文使用采集时间（arXiv API 返回的是原始提交日期，可能已过数天）
        if item.source_type == "paper" and item.collected_at:
            pub_str = item.collected_at

        if not pub_str:
            # 发布时间缺失 —— 无法判断时效，保留
            kept.append(item)
            continue

        try:
            # 尝试解析 ISO8601 格式；兼容末尾带 Z / 已有 +00:00 等情况
            pub_str = pub_str.strip()
            # 替换末尾 Z → +00:00（只在尾部替换一次）
            if pub_str.endswith("Z"):
                pub_str = pub_str[:-1] + "+00:00"
            # 防止重复时区：如 "2026-05-18T17:37:54+00:00+00:00"
            # 检查是否已含时区（'+'在末尾偏移中出现）
            if pub_str.count("+") > 1:
                # 取第一个 + 作为时区分割
                idx = pub_str.find("+")
                pub_str = pub_str[:idx] + "+00:00"
            # 如果没有时区信息，视为 UTC
            if "+" not in pub_str:
                pub_str += "+00:00"
            pub_dt = datetime.fromisoformat(pub_str)
        except (ValueError, TypeError) as e:
            logger.warning("无法解析 published_at [%s]: %s — 保留该条目", pub_str, e)
            kept.append(item)
            continue

        if pub_dt >= cutoff:
            kept.append(item)

    return kept


def filter_by_ai_relevance(items: List[NewsItem]) -> List[NewsItem]:
    """过滤AI相关性：标题/摘要/tags 中至少一个包含 AI 关键词。

    匹配规则：全部转为小写后，检查是否包含 AI_KEYWORDS 中的任一关键词。
    """
    if not AI_KEYWORDS:
        return items

    # 预处理关键词为小写，方便后续加速
    keywords_lower = [kw.lower() for kw in AI_KEYWORDS]

    def _is_relevant(item: NewsItem) -> bool:
        """判断单条新闻是否与 AI 相关"""
        # 拼接所有可检查的文本字段，逐个匹配
        title_lower = (item.title or "").lower()
        summary_lower = (item.summary_raw or "").lower()
        # tags 列表转小写集合
        tags_lower = {t.lower() for t in (item.tags or [])}

        for kw in keywords_lower:
            if kw in title_lower or kw in summary_lower or kw in tags_lower:
                return True
        return False

    return [item for item in items if _is_relevant(item)]


def filter_blacklisted(items: List[NewsItem]) -> List[NewsItem]:
    """过滤黑名单：域名或标题命中黑名单的条目丢弃。

    规则：
        - 标题中任意 TITLE_BLACKLIST 子串出现 → 丢弃
        - URL 中任意 DOMAIN_BLACKLIST 子串出现  → 丢弃
    """
    title_bk = [b.lower() for b in TITLE_BLACKLIST]
    domain_bk = [d.lower() for d in DOMAIN_BLACKLIST]

    def _is_blacklisted(item: NewsItem) -> bool:
        title_lower = (item.title or "").lower()
        url_lower = (item.url or "").lower()

        for word in title_bk:
            if word in title_lower:
                return True
        for domain in domain_bk:
            if domain in url_lower:
                return True
        return False

    return [item for item in items if not _is_blacklisted(item)]


def filter_low_quality(items: List[NewsItem]) -> List[NewsItem]:
    """过滤低质量：无标题或无URL的条目直接丢弃。"""
    return [
        item for item in items
        if item.title and item.title.strip() and item.url and item.url.strip()
    ]


def run_filters(items: List[NewsItem]) -> List[NewsItem]:
    """串联所有过滤器，返回干净条目，每步打印过滤数量。

    Args:
        items: 原始采集条目列表

    Returns:
        经过全部过滤后的条目列表
    """
    total = len(items)
    logger.info("开始过滤 — 原始条目: %d", total)

    step1 = filter_by_time_window(items)
    logger.info("时间窗口过滤: %d → %d (丢弃 %d)", total, len(step1), total - len(step1))

    step2 = filter_by_ai_relevance(step1)
    logger.info("AI相关性过滤: %d → %d (丢弃 %d)", len(step1), len(step2), len(step1) - len(step2))

    step3 = filter_blacklisted(step2)
    logger.info("黑名单过滤: %d → %d (丢弃 %d)", len(step2), len(step3), len(step2) - len(step3))

    step4 = filter_low_quality(step3)
    logger.info("低质量过滤: %d → %d (丢弃 %d)", len(step3), len(step4), len(step3) - len(step4))

    logger.info("过滤完成: %d → %d (总丢弃 %d)", total, len(step4), total - len(step4))
    return step4
