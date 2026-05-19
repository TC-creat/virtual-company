"""
Hacker News 采集器

数据源：Firebase 官方 API（无需认证）
API 文档：https://github.com/HackerNews/API

采集策略：
  1. 获取 /v0/topstories.json 得到热门文章 ID 列表
  2. 取前 150 条，逐个 /v0/item/{id}.json 拉取详情
  3. 根据 AI_KEYWORDS / DOMAIN_WHITELIST 过滤
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SOURCE_TIMEOUT, SOURCE_RETRY, RAW_DIR, GITHUB_TOKEN, AI_KEYWORDS, DOMAIN_WHITELIST
from models import NewsItem
from utils.http import create_session, fetch_with_timeout

# ── 常量 ───────────────────────────────────────────────────
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
TOP_N = 150  # 取 topstories 的前 N 条


def _is_ai_related(item: dict) -> bool:
    """判断 HN 条目是否与 AI 相关。

    满足以下任一条件即判定为 AI 相关：
      1. title 包含 AI_KEYWORDS 中任一关键词（不区分大小写）
      2. url 的域名在 DOMAIN_WHITELIST 中

    Args:
        item: HN API 返回的 item JSON 字典。

    Returns:
        True 表示该条目值得收录。
    """
    title = (item.get("title") or item.get("text") or "")
    title_lower = title.lower()

    # 检查标题是否含 AI 关键词
    for kw in AI_KEYWORDS:
        if kw.lower() in title_lower:
            return True

    # 检查 URL 域名是否在白名单内
    url = item.get("url") or ""
    if url:
        try:
            domain = urlparse(url).netloc.lower()
            for whitelist_domain in DOMAIN_WHITELIST:
                if domain == whitelist_domain or domain.endswith("." + whitelist_domain):
                    return True
        except Exception:
            pass

    return False


def collect_hacker_news() -> list[NewsItem]:
    """采集 Hacker News 热门文章，返回 AI 相关的新闻列表。

    Returns:
        AI 相关的 NewsItem 列表；发生异常时返回空列表。
    """
    timeout = SOURCE_TIMEOUT.get("hacker_news", 15)
    session = create_session()
    items: list[NewsItem] = []
    raw_data: list[dict] = []

    try:
        # ── 1. 获取 topstories ID 列表 ─────────────────
        print("[hacker_news] 正在获取 topstories 列表 ...")
        resp = fetch_with_timeout(
            session,
            f"{HN_API_BASE}/topstories.json",
            timeout=timeout,
        )
        all_ids = resp.json()
        target_ids = all_ids[:TOP_N]
        print(f"[hacker_news] 获取到 {len(all_ids)} 条，取前 {len(target_ids)} 条")

        # ── 2. 逐个拉取详情 ────────────────────────────
        for idx, story_id in enumerate(target_ids):
            try:
                story_resp = fetch_with_timeout(
                    session,
                    f"{HN_API_BASE}/item/{story_id}.json",
                    timeout=timeout,
                )
                story = story_resp.json()
                if not story or story.get("type") != "story":
                    continue

                raw_data.append(story)

                # AI 相关性过滤
                if not _is_ai_related(story):
                    continue

                # 构建新闻条目
                title = (story.get("title") or "").strip()
                url = story.get("url") or ""
                if not url:
                    # Ask HN / Show HN 无外部链接，指向 HN 讨论页
                    url = f"https://news.ycombinator.com/item?id={story_id}"
                author = story.get("by") or ""
                score = story.get("score") or 0
                comments = story.get("descendants") or 0
                unix_time = story.get("time")
                published_at = ""
                if unix_time:
                    published_at = datetime.fromtimestamp(
                        int(unix_time), tz=timezone.utc
                    ).isoformat()

                # 取 content_snippet（HN 没有正文，用 text 字段或空）
                snippet = (story.get("text") or "")[:300]

                item = NewsItem(
                    source="hacker_news",
                    source_type="community",
                    title=title,
                    url=url,
                    canonical_url=url,
                    author=author,
                    published_at=published_at,
                    content_snippet=snippet,
                    summary_raw=title,
                    tags=[],
                    metrics={
                        "score": score,
                        "comments": comments,
                        "stars_today": 0,
                        "github_stars": 0,
                    },
                    evidence={
                        "hn": True,
                        "hf_papers": False,
                        "github": False,
                        "reddit": False,
                    },
                )
                items.append(item)

            except Exception as e:
                print(f"[hacker_news] 获取 story {story_id} 失败: {e}")
                continue

        # ── 3. 保存原始数据用于调试 ─────────────────────
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            raw_path = RAW_DIR / f"hacker_news_{date_str}.json"
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)
            print(f"[hacker_news] 原始数据已保存: {raw_path}")
        except Exception as e:
            print(f"[hacker_news] 保存原始数据失败: {e}")

        print(f"[hacker_news] 采集完成: {len(items)} 条")
        return items

    except Exception as e:
        print(f"[hacker_news] 采集异常: {e}")
        return []
