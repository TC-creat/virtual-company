"""
去重与聚类模块 —— URL标准化、标题相似度去重、跨源证据合并、指纹聚类

处理顺序：
    1. dedupe_by_url               — 对 canonicalize_url 后的 URL 去重
    2. dedupe_by_title_similarity  — 标题模糊匹配去重（rapidfuzz 或 Jaccard 回退）
    3. merge_evidence              — 同 cluster_key 的证据合并
    4. cluster_items               — 基于标题 hash 生成 cluster_key
    5. run_dedup                   — 串联上述流程并打印统计
"""
import hashlib
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from models import NewsItem

logger = logging.getLogger(__name__)

# 需要剥离的 tracking 参数名
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
}


# ── 工具函数 ──────────────────────────────────────────────────────────────

def canonicalize_url(url: str) -> str:
    """URL 标准化：去除 tracking 参数、统一 GitHub/ArXiv 格式、小写域名、去尾斜杠。

    处理规则：
        - 域名转为小写
        - 剥离 TRACKING_PARAMS 中的查询参数
        - 去除尾部斜杠（保留根路径 '/' 不变）
        - GitHub 统一为 /tree/main 格式
        - ArXiv 统一为 abs/XXXX.XXXXX 格式
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url.lower().strip())
    except Exception:
        return url.strip().lower()

    # 剥离 tracking 参数
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned_params = {
        k: v for k, v in query_params.items()
        if k not in TRACKING_PARAMS
    }
    new_query = urlencode(cleaned_params, doseq=True) if cleaned_params else ""

    # 标准化路径
    path = parsed.path.rstrip("/") or "/"

    # GitHub: 统一短链接 /tree/main
    if parsed.netloc == "github.com":
        # /user/repo 保持; /user/repo.git → /user/repo
        if path.endswith(".git"):
            path = path[:-4]

    # ArXiv: 统一为 abs/XXXX.XXXXX
    if parsed.netloc == "arxiv.org":
        # /abs/2101.12345 保持不变
        # /pdf/2101.12345 → /abs/2101.12345
        # /pdf/2101.12345.pdf → /abs/2101.12345 (去掉 .pdf)
        # /2101.12345 → /abs/2101.12345
        path = path.removesuffix(".pdf")
        if "/pdf/" in path:
            path = path.replace("/pdf/", "/abs/")
        elif path.count("/") == 1 and path[1:].split("/")[0].replace(".", "").isdigit():
            path = f"/abs/{path.lstrip('/')}"

    new_netloc = parsed.netloc
    return urlunparse((parsed.scheme, new_netloc, path, parsed.params, new_query, parsed.fragment or ""))


def _jaccard_similarity(tokens_a: set, tokens_b: set) -> float:
    """Jaccard 相似度 — 作为 rapidfuzz 不可用时的回退方案。"""
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _higher_quality(a: NewsItem, b: NewsItem) -> NewsItem:
    """比较两个条目，返回 quality.rule_score 更高的那个。"""
    return a if (a.quality.get("rule_score", 0) or 0) >= (b.quality.get("rule_score", 0) or 0) else b


# ── 核心逻辑 ──────────────────────────────────────────────────────────────

def dedupe_by_url(items: List[NewsItem]) -> List[NewsItem]:
    """URL 去重：canonicalize 后相同 URL 只保留 rule_score 最高的那一条。

    canonical_url 字段会被更新为标准化后的 URL。
    """
    seen: Dict[str, NewsItem] = {}
    order: List[str] = []  # 保持首次出现的顺序

    for item in items:
        canon = canonicalize_url(item.url)
        item.canonical_url = canon
        if not canon:
            continue
        if canon in seen:
            # 保留评分更高的结果
            seen[canon] = _higher_quality(seen[canon], item)
        else:
            seen[canon] = item
            order.append(canon)

    return [seen[url] for url in order]


def dedupe_by_title_similarity(items: List[NewsItem], threshold: float = 0.85) -> List[NewsItem]:
    """标题相似度去重：快速模糊比对，超过阈值的视为重复，保留 rule_score 较高的。

    优先使用 rapidfuzz（pip install rapidfuzz），不可用时回退到 Jaccard 相似度。
    """
    try:
        from rapidfuzz import fuzz
        def _ratio(a: str, b: str) -> float:
            return fuzz.ratio(a, b) / 100.0
        logger.debug("使用 rapidfuzz 进行标题相似度计算")
    except ImportError:
        def _ratio(a: str, b: str) -> float:
            words_a = set(a.lower().split())
            words_b = set(b.lower().split())
            return _jaccard_similarity(words_a, words_b)
        logger.debug("rapidfuzz 不可用，回退到 Jaccard 相似度")

    kept: List[NewsItem] = []
    for item in items:
        title = (item.title or "").strip()
        if not title:
            continue
        is_dup = False
        for existing in kept:
            existing_title = (existing.title or "").strip()
            if not existing_title:
                continue
            sim = _ratio(title, existing_title)
            if sim >= threshold:
                # 保留评分更高的那条
                better = _higher_quality(item, existing)
                if better is item:
                    # 当前项更好，替换已有项
                    kept.remove(existing)
                    kept.append(item)
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
    return kept


def merge_evidence(items: List[NewsItem]) -> List[NewsItem]:
    """跨源证据合并：相同 cluster_key 的条目合并 evidence 字段。

    规则：
        - 按 cluster_key 分组（非空）
        - 组内所有 evidence 布尔值做 OR 合并
        - 保留组内 quality.rule_score 最高的条目作为代表
        - 无 cluster_key 的条目原样保留
    """
    groups: Dict[str, List[NewsItem]] = {}
    standalone: List[NewsItem] = []

    for item in items:
        key = (item.cluster_key or "").strip()
        if key:
            groups.setdefault(key, []).append(item)
        else:
            standalone.append(item)

    merged: List[NewsItem] = []
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # OR 合并所有 evidence
        combined_evidence = dict(group[0].evidence)
        for other in group[1:]:
            for field in combined_evidence:
                if other.evidence.get(field):
                    combined_evidence[field] = True

        # 保留评分最高的作为代表
        best = max(group, key=lambda x: x.quality.get("rule_score", 0) or 0)
        best.evidence = combined_evidence
        merged.append(best)

        logger.info("证据合并: cluster_key=%s, 合并了 %d 条, 来源域: %s",
                     key, len(group),
                     [it.source for it in group])

    return merged + standalone


def cluster_items(items: List[NewsItem]) -> List[NewsItem]:
    """指纹聚类：基于标题关键词 + URL 域名生成 cluster_key。

    算法：
        1. 对标题做分词（按空白符 / 标点分割）
        2. 取最长的前 5 个词（过滤长度 ≤ 2 的停用词）
        3. 加上 URL 的域名（canonicalize 后）
        4. MD5 取前 12 位作为 cluster_key
    """
    # 常见英文停用词（长度 ≤ 2 且无信息含量）
    short_stopwords = {"a", "an", "the", "of", "in", "on", "at", "to", "for",
                       "by", "is", "it", "as", "be", "or", "and", "not", "no",
                       "we", "if", "do", "up", "my", "he", "she"}

    import re
    for item in items:
        if item.cluster_key:
            # 已有聚类键的不覆盖
            continue

        title = (item.title or "").strip()
        if not title:
            continue

        # 分词：按空白符和常见标点分割
        tokens = re.findall(r"[a-zA-Z0-9一-鿿\-]+", title.lower())
        # 过滤长度 ≤ 2 的停用词和纯数字
        meaningful = [t for t in tokens if len(t) > 2 and t not in short_stopwords and not t.isdigit()]
        # 去重且按长度降序取前 5
        unique = list(dict.fromkeys(meaningful))
        unique.sort(key=lambda w: (len(w), w), reverse=True)
        top_words = unique[:5]

        # 加入标准化后的域名
        canon = item.canonical_url or canonicalize_url(item.url)
        domain = urlparse(canon).netloc if canon else ""

        fingerprint_str = "|".join(top_words + ([domain] if domain else []))
        if fingerprint_str:
            item.cluster_key = hashlib.md5(fingerprint_str.encode()).hexdigest()[:12]

    return items


def run_dedup(items: List[NewsItem]) -> List[NewsItem]:
    """串联去重流程，每步打印处理数量。

    Args:
        items: 经过过滤的条目列表

    Returns:
        去重后的条目列表
    """
    total = len(items)
    logger.info("开始去重 — 输入: %d", total)

    step1 = dedupe_by_url(items)
    logger.info("URL去重: %d → %d (消除 %d)", total, len(step1), total - len(step1))

    # 先做聚类再合并证据
    step1 = cluster_items(step1)
    logger.info("聚类完成: %d 个条目获得 cluster_key", sum(1 for it in step1 if it.cluster_key))

    step3 = merge_evidence(step1)
    logger.info("证据合并: %d → %d (合并 %d)", len(step1), len(step3), len(step1) - len(step3))

    step4 = dedupe_by_title_similarity(step3)
    logger.info("标题去重: %d → %d (消除 %d)", len(step3), len(step4), len(step3) - len(step4))

    logger.info("去重完成: %d → %d (总消除 %d)", total, len(step4), total - len(step4))
    return step4
