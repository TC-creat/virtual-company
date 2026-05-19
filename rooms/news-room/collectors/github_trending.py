"""
GitHub Trending 采集器

数据源：
  1. GitHub Trending 页（https://github.com/trending）
  2. GitHub Search API（可选，需 GITHUB_TOKEN）

采集策略：
  1. 抓取 Trending 每日热门仓库
  2. 若配置了 GITHUB_TOKEN，额外通过 Search API 补充 AI 相关仓库
  3. 合并结果、按仓库名去重
  4. 用 AI 关键词 / 语言 + 描述相关性过滤
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SOURCE_TIMEOUT, SOURCE_RETRY, RAW_DIR, GITHUB_TOKEN, AI_KEYWORDS, DOMAIN_WHITELIST
from models import NewsItem
from utils.http import create_session, fetch_with_timeout

# ── 常量 ───────────────────────────────────────────────────
TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"

# 仓库层面 AI 关键词（比通用 AI_KEYWORDS 更聚焦 ML/AI 工程）
REPO_AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "agent", "gpt", "claude", "gemini",
    "llama", "mistral", "openai", "anthropic", "diffusion", "transformer",
    "rag", "mcp", "fine-tun", "neural network", "nlp",
    "reinforcement learning", "rlhf", "embedding", "vector database",
    "langchain", "autogpt", "chatgpt", "copilot",
    "deepseek", "qwen", "mixtral", "stable diffusion",
    "sora", "whisper", "tokenizer", "attention",
    "zero-shot", "few-shot", "multimodal", "vision language",
    "huggingface", "gradio", "streamlit", "pytorch", "tensorflow",
    "generative", "chatbot", "rag", "knowledge graph",
]

# ML 工程领域（语言 + 描述匹配用）
ML_ENGINEERING_LANGUAGES = {"python", "javascript", "typescript"}
ML_RELATED_KEYWORDS = [
    "machine learning", "deep learning", "ai", "artificial intelligence",
    "neural", "nlp", "computer vision", "data science",
    "automl", "mlops", "data pipeline", "data mining",
    "predictive", "classification", "regression", "clustering",
    "recommendation", "ranking", "optimization",
]


def _parse_stars_today(text: str) -> int:
    """从 "1,234 stars today" 格式中解析星标数字。

    Args:
        text: GitHub 显示的每日星标文本。

    Returns:
        解析出的整数；解析失败返回 0。
    """
    if not text:
        return 0
    cleaned = re.sub(r"[^\d]", "", text.strip())
    try:
        return int(cleaned) if cleaned else 0
    except ValueError:
        return 0


def _is_repo_ai_related(name: str, description: str, language: str, topics: list[str]) -> bool:
    """判断仓库是否与 AI 相关。

    满足以下任一条件即判定相关：
      1. 仓库名/描述/topics 包含 AI 关键词
      2. 语言是 Python/JavaScript/TypeScript 且描述包含 ML 关键词

    Args:
        name: 仓库名（含 owner）。
        description: 仓库描述。
        language: 主要编程语言。
        topics: 仓库话题标签。

    Returns:
        True 表示该仓库值得收录。
    """
    text_to_check = f"{name} {description}".lower()
    topics_lower = [t.lower() for t in topics]

    # 条件 1：名称/描述/topics 含 AI 关键词
    for kw in REPO_AI_KEYWORDS:
        if kw.lower() in text_to_check:
            return True
        for t in topics_lower:
            if kw.lower() in t:
                return True

    # 条件 2：Python/JS/TS + ML 相关描述
    if language and language.lower() in ML_ENGINEERING_LANGUAGES:
        for kw in ML_RELATED_KEYWORDS:
            if kw.lower() in text_to_check:
                return True

    return False


def _scrape_trending(session) -> list[dict]:
    """抓取 GitHub Trending 页面并解析仓库列表。

    Args:
        session: requests.Session 实例。

    Returns:
        解析出的仓库原始数据列表（每个元素为 dict）。
    """
    timeout = SOURCE_TIMEOUT.get("github_trending", 20)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    resp = fetch_with_timeout(session, TRENDING_URL, timeout=timeout, headers=headers)

    # 延迟导入 BeautifulSoup（避免缺少依赖时整个模块崩溃）
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[github_trending] BeautifulSoup 未安装，跳过 Trending 抓取")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    rows = soup.select("article.Box-row")
    print(f"[github_trending] Trending 页面解析到 {len(rows)} 个仓库")

    repos = []
    for row in rows:
        try:
            # ── 仓库名 ────────────────────────────────
            h2 = row.select_one("h2 a")
            if not h2:
                continue
            raw_name = h2.get_text(strip=True)
            # GitHub 上显示为 "owner / repo"，需去除斜杠空格
            repo_name = re.sub(r"\s+", "", raw_name)  # "owner/repo"

            # ── 描述 ──────────────────────────────────
            desc_el = row.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # ── 语言 ──────────────────────────────────
            lang_el = row.select_one('span[itemprop="programmingLanguage"]')
            language = lang_el.get_text(strip=True) if lang_el else ""

            # ── 今日星标 ──────────────────────────────
            stars_el = row.select_one("span.d-inline-block.float-sm-right")
            stars_today = _parse_stars_today(
                stars_el.get_text(strip=True) if stars_el else ""
            )

            repos.append({
                "name": repo_name,
                "description": description,
                "language": language,
                "stars_today": stars_today,
                "source": "trending",
            })
        except Exception as e:
            print(f"[github_trending] 解析单个仓库失败: {e}")
            continue

    return repos


def _search_github_api(session) -> list[dict]:
    """通过 GitHub Search API 搜索 AI 相关仓库。

    仅在 GITHUB_TOKEN 配置时调用。

    Args:
        session: requests.Session 实例。

    Returns:
        搜索结果的仓库原始数据列表。
    """
    if not GITHUB_TOKEN:
        return []

    timeout = SOURCE_TIMEOUT.get("github_trending", 20)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-News-Room/1.0",
    }

    query = "agent+LLM+RAG+AI+topic:artificial-intelligence"
    params = {
        "q": query.replace("+", " "),
        "sort": "stars",
        "order": "desc",
        "per_page": 20,
    }

    try:
        print("[github_trending] 正在调用 GitHub Search API ...")
        resp = fetch_with_timeout(
            session, GITHUB_SEARCH_API, timeout=timeout, headers=headers, params=params,
        )
        data = resp.json()
        items = data.get("items", [])
        print(f"[github_trending] Search API 返回 {len(items)} 条结果")

        repos = []
        for item in items:
            repos.append({
                "name": item.get("full_name", ""),
                "description": item.get("description") or "",
                "language": item.get("language") or "",
                "stars_today": 0,  # Search API 无每日星标数据
                "stargazers_count": item.get("stargazers_count", 0),
                "topics": item.get("topics", []),
                "html_url": item.get("html_url", ""),
                "source": "search_api",
            })
        return repos
    except Exception as e:
        print(f"[github_trending] Search API 调用失败: {e}")
        return []


def collect_github_trending() -> list[NewsItem]:
    """采集 GitHub 趋势仓库（含 Search API 补充），返回 AI 相关列表。

    Returns:
        AI 相关仓库的 NewsItem 列表；发生异常时返回空列表。
    """
    items: list[NewsItem] = []
    seen_repos: set[str] = set()
    all_raw: list[dict] = []
    trending_repos: list[dict] = []
    search_repos: list[dict] = []

    # 先走代理，失败则直连重试
    for attempt in range(2):
        session = create_session() if attempt == 0 else create_session(bypass_proxy=True)
        if attempt > 0:
            print("[github_trending] 代理连接失败，尝试直连…")
        try:
            trending_repos = _scrape_trending(session)
            all_raw.extend(trending_repos)
            search_repos = _search_github_api(session)
            all_raw.extend(search_repos)
            break
        except Exception as e:
            if attempt == 1:
                print(f"[github_trending] 直连也失败: {e}")
                return []
            print(f"[github_trending] 代理失败: {e}")

    # 合并 & 去重
    for repo in trending_repos + search_repos:
        repo_name = repo.get("name", "")
        if not repo_name or repo_name in seen_repos:
            continue
        seen_repos.add(repo_name)

        description = repo.get("description", "")
        language = repo.get("language", "")
        topics = repo.get("topics", [])

        if not _is_repo_ai_related(repo_name, description, language, topics):
            continue

        url = repo.get("html_url") if repo.get("source") == "search_api" else f"https://github.com/{repo_name}"
        url = url or f"https://github.com/{repo_name}"

        item = NewsItem(
            source="github_trending",
            source_type="repo",
            title=repo_name,
            url=url,
            canonical_url=url,
            author="",
            published_at="",
            summary_raw=description,
            tags=topics if isinstance(topics, list) else ([language] if language else []),
            metrics={
                "score": 0,
                "comments": 0,
                "stars_today": repo.get("stars_today", 0),
                "github_stars": repo.get("stargazers_count", 0),
            },
            evidence={"hn": False, "hf_papers": False, "github": True, "reddit": False},
        )
        items.append(item)

    # 保存原始数据
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        raw_path = RAW_DIR / f"github_trending_{date_str}.json"
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(all_raw, f, ensure_ascii=False, indent=2)
        print(f"[github_trending] 原始数据已保存: {raw_path}")
    except Exception as e:
        print(f"[github_trending] 保存原始数据失败: {e}")

    print(f"[github_trending] 采集完成: {len(items)} 条")
    return items
