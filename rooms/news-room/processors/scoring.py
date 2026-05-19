"""
评分排序模块 —— 多维度评分 + 综合加权排序

评分维度：
    1. source_authority  — 来源权威度（paper > repo > community > media）
    2. recency           — 时效性（越新越高，48小时内线性衰减）
    3. heat              — 热度（log1p 归一化后的互动/星标指标）
    4. cross_source      — 跨源热度证据加分
    5. llm_score         — LLM 打分（外部写入，此处不做计算）

典型用法：
    from processors.scoring import score_items, select_top
    ranked = score_items(items)
    top = select_top(ranked, k=8)
"""
import logging
import math
from datetime import datetime, timezone
from typing import List, Optional

from models import NewsItem
from config import SCORE_WEIGHTS

logger = logging.getLogger(__name__)

# 来源类型 → 权威度映射
AUTHORITY_MAP: dict[str, float] = {
    "paper": 0.9,
    "repo": 0.7,
    "community": 0.5,
    "media": 0.4,
}


def _parse_published_at(item: NewsItem) -> Optional[datetime]:
    """尝试解析 published_at 为 datetime 对象；失败返回 None。"""
    raw = item.published_at
    if not raw:
        return None
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if s.count("+") > 1:
            idx = s.find("+")
            s = s[:idx] + "+00:00"
        if "+" not in s:
            s += "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ── 各维度评分函数 ─────────────────────────────────────────────────────────

def compute_source_authority(item: NewsItem) -> float:
    """来源权威度评分：基于 source_type 映射。

    paper=0.9, repo=0.7, community=0.5, media=0.4, 未知=0.3
    """
    return AUTHORITY_MAP.get((item.source_type or "").strip().lower(), 0.3)


def compute_recency(item: NewsItem, now: Optional[datetime] = None) -> float:
    """时效性评分：越新越高，48 小时内线性衰减到零。

    公式：score = max(0, 1 - hours_ago / 48)
    无法解析发布时间时返回 0.5（中性分）。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    pub_dt = _parse_published_at(item)
    if pub_dt is None:
        return 0.5

    hours_ago = max(0, (now - pub_dt).total_seconds() / 3600)
    return max(0.0, 1.0 - hours_ago / 48.0)


def compute_heat(item: NewsItem) -> float:
    """热度评分：基于 metrics 中的互动与星标指标，log1p 归一化到 [0, 1]。

    组合指标：score + comments*2 + stars_today*5 + github_stars*0.1
    归一化参考点：原始分值达到 1000 时归一化为 1.0。
    """
    metrics = item.metrics or {}
    raw = (
        float(metrics.get("score", 0))
        + float(metrics.get("comments", 0)) * 2.0
        + float(metrics.get("stars_today", 0)) * 5.0
        + float(metrics.get("github_stars", 0)) * 0.1
    )
    normalized = math.log1p(raw) / math.log1p(1000)
    return min(1.0, normalized)


def compute_cross_source(item: NewsItem) -> float:
    """跨源热度加分：被多个不同来源同时提到则加分。

    evidence 字典中每个 True 字段计 0.25 分，最高 1.0。
    """
    evidence = item.evidence or {}
    count = sum(1 for v in evidence.values() if v)
    return min(1.0, count * 0.25)


# ── 综合评分 ───────────────────────────────────────────────────────────────

def score_items(items: List[NewsItem]) -> List[NewsItem]:
    """综合评分：遍历所有条目，更新 quality 字段并降序排序。

    每一条目会更新：
        - quality["source_authority"] — 来源权威度（单独存储方便查）
        - quality["rule_score"]       — 各规则维度的加权总分
        - quality["final_score"]      — = rule_score * (1 + llm_score) 混合最终分

    排序规则：按 final_score 降序。
    """
    weights = SCORE_WEIGHTS
    now = datetime.now(timezone.utc)

    for item in items:
        authority = compute_source_authority(item)
        recency = compute_recency(item, now)
        heat = compute_heat(item)
        cross = compute_cross_source(item)

        # 加权汇总
        rule_score = (
            weights.get("source_authority", 0.35) * authority
            + weights.get("recency", 0.20) * recency
            + weights.get("heat", 0.20) * heat
            + weights.get("cross_source", 0.10) * cross
            + weights.get("llm", 0.15) * (item.quality.get("llm_score", 0.0) or 0.0)
        )

        # 更新 quality 字段
        item.quality["source_authority"] = authority
        item.quality["recency"] = recency
        item.quality["heat"] = heat
        item.quality["cross_source"] = cross
        item.quality["rule_score"] = round(rule_score, 4)

        # final_score: rule_score 与 llm_score 混合
        llm = item.quality.get("llm_score", 0.0) or 0.0
        item.quality["final_score"] = round(rule_score * (1.0 + llm * 0.3), 4)

    # 按 final_score 降序排列
    items.sort(key=lambda x: x.quality.get("final_score", 0) or 0, reverse=True)
    return items


def select_top(items: List[NewsItem], k: Optional[int] = None) -> List[NewsItem]:
    """筛选 Top-K 条目。

    Args:
        items: 已评分排序的条目列表
        k: 保留条数。为 None 时不截断（返回全部）

    Returns:
        评分最高的 k 条；若 items 未排序则不会重新排序。
    """
    if k is None or k < 1:
        return items
    return items[:k]
