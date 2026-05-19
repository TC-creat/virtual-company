"""
Hugging Face Papers 采集器

数据源：https://huggingface.co/papers（网页抓取）

采集策略：
  1. 抓取 Hugging Face Papers 页面
  2. 解析论文卡片：标题、摘要、标签、链接
  3. 所有 HF Papers 均为 AI 相关，默认全部收录
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SOURCE_TIMEOUT, SOURCE_RETRY, RAW_DIR, GITHUB_TOKEN, AI_KEYWORDS, DOMAIN_WHITELIST
from models import NewsItem
from utils.http import create_session, fetch_with_timeout

# ── 常量 ───────────────────────────────────────────────────
HF_PAPERS_URL = "https://huggingface.co/papers"


def _extract_text(el, default: str = "") -> str:
    """安全提取元素的纯文本内容，去除多余空白。

    Args:
        el: BeautifulSoup 元素或 None。
        default: 提取失败时的默认值。

    Returns:
        清洗后的文本。
    """
    if el is None:
        return default
    try:
        return " ".join(el.get_text(strip=True).split())
    except Exception:
        return default


def _is_ai_related(title: str, summary: str, tags: list[str]) -> bool:
    """检查论文是否与 AI 相关。

    HF Papers 理论上全是 AI 论文，此处为双重保险。

    Args:
        title: 论文标题。
        summary: 论文摘要。
        tags: 标签列表。

    Returns:
        True 表示值得收录。
    """
    text_to_check = f"{title} {summary}".lower()
    # 宽匹配：只要标题/摘要含任一 AI 关键词即通过
    for kw in AI_KEYWORDS:
        if kw.lower() in text_to_check:
            return True
    for tag in tags:
        for kw in AI_KEYWORDS:
            if kw.lower() in tag.lower():
                return True
    # 即使没有关键词命中，HF 论文也大概率是 AI 相关，宽松处理
    # 若无任何关键词命中但标题非空，仍然收录（HF 本身是 AI 平台）
    return bool(title.strip())


def _parse_papers_page(session) -> list[dict]:
    """抓取并解析 HF Papers 页面，返回原始论文数据。

    Args:
        session: requests.Session 实例。

    Returns:
        论文原始数据列表。
    """
    timeout = SOURCE_TIMEOUT.get("huggingface", 20)
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    resp = fetch_with_timeout(session, HF_PAPERS_URL, timeout=timeout, headers=headers)

    # 延迟导入 BeautifulSoup
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[huggingface] BeautifulSoup 未安装，跳过")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    papers_data: list[dict] = []

    # ── 策略：尝试多种选择器以适应页面结构变化 ────────
    # HF 页面可能使用 article、div[class*="paper"]、li 等容器
    candidates = []

    # 1. 尝试 article 元素
    candidates.extend(soup.select("article"))
    # 2. 尝试包含 paper 关键词的 div
    candidates.extend(soup.select('div[class*="paper"]'))
    candidates.extend(soup.select('div[class*="Paper"]'))
    # 3. 尝试常见的卡片容器
    candidates.extend(soup.select('div[class*="card"]'))
    candidates.extend(soup.select('li[class*="paper"]'))

    # 如果没有特定容器，尝试在 main 区域查找标题元素附近的卡片
    if not candidates:
        # 回退策略：在 body 中找 h2/h3 作为段落标题，其父容器作为卡片
        for heading in soup.select("h2, h3"):
            parent = heading.parent
            if parent and parent not in candidates:
                # 检查父容器是否包含链接和段落（论文卡片特征）
                if parent.find("a") and (parent.find("p") or parent.find("div", class_=True)):
                    candidates.append(parent)

    # 去重（保留顺序）
    seen = set()
    unique_candidates = []
    for el in candidates:
        el_id = id(el)
        if el_id not in seen:
            seen.add(el_id)
            unique_candidates.append(el)

    print(f"[huggingface] 页面解析到 {len(unique_candidates)} 个候选容器")

    for card in unique_candidates:
        try:
            # ── 标题与链接 ────────────────────────────
            title_el = card.select_one("h3 a") or card.select_one("h2 a") or card.select_one("a")
            if not title_el:
                continue
            title = _extract_text(title_el)
            if not title or len(title) < 3:
                continue

            # 构建完整 URL
            href = title_el.get("href", "")
            if href.startswith("/"):
                url = urljoin("https://huggingface.co", href)
            elif href.startswith("http"):
                url = href
            else:
                url = f"https://huggingface.co/{href}"

            # ── 摘要 ──────────────────────────────────
            # 尝试多种元素定位摘要
            summary = ""
            for selector in ["p", "div[class*='abstract']", "div[class*='description']",
                             "div[class*='summary']", "div[class*='subtitle']"]:
                summary_el = card.select_one(selector)
                if summary_el:
                    summary = _extract_text(summary_el)
                    if summary:
                        break

            # ── 标签 ──────────────────────────────────
            tags = []
            for tag_el in card.select('[class*="tag"], [class*="badge"], [class*="label"], '
                                       '[class*="topic"], [class*="category"]'):
                tag_text = _extract_text(tag_el)
                if tag_text and len(tag_text) < 50:
                    tags.append(tag_text)

            # 也尝试从 URL 路径中提取标签
            if "arxiv" in url.lower():
                tags.append("arxiv")

            papers_data.append({
                "title": title,
                "url": url,
                "summary": summary,
                "tags": tags,
            })
        except Exception as e:
            print(f"[huggingface] 解析单篇论文卡片失败: {e}")
            continue

    return papers_data


def collect_huggingface() -> list[NewsItem]:
    """采集 Hugging Face Papers，返回 AI 论文列表。

    Returns:
        论文的 NewsItem 列表；发生异常时返回空列表。
    """
    items: list[NewsItem] = []

    # 先走代理，失败则直连重试
    for attempt in range(2):
        session = create_session() if attempt == 0 else create_session(bypass_proxy=True)
        if attempt > 0:
            print("[huggingface] 代理连接失败，尝试直连…")
        try:
            print("[huggingface] 正在抓取 HF Papers 页面 ...")
            papers_data = _parse_papers_page(session)
            break
        except Exception as e:
            if attempt == 1:
                print(f"[huggingface] 直连也失败: {e}")
                return []
            print(f"[huggingface] 代理失败: {e}")

    for paper in papers_data:
        try:
            title = paper.get("title", "")
            url = paper.get("url", "")
            summary = paper.get("summary", "")
            tags = paper.get("tags", [])

            if not _is_ai_related(title, summary, tags):
                continue

            item = NewsItem(
                source="huggingface",
                source_type="paper",
                title=title,
                url=url,
                canonical_url=url,
                author="",
                published_at="",
                summary_raw=summary,
                tags=tags,
                metrics={"score": 0, "comments": 0, "stars_today": 0, "github_stars": 0},
                evidence={"hn": False, "hf_papers": True, "github": False, "reddit": False},
            )
            items.append(item)
        except Exception as e:
            print(f"[huggingface] 构建 NewsItem 失败: {e}")
            continue

    # 保存原始数据
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        raw_path = RAW_DIR / f"huggingface_{date_str}.json"
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(papers_data, f, ensure_ascii=False, indent=2)
        print(f"[huggingface] 原始数据已保存: {raw_path}")
    except Exception as e:
        print(f"[huggingface] 保存原始数据失败: {e}")

    print(f"[huggingface] 采集完成: {len(items)} 条")
    return items
