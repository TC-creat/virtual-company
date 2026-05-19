"""
arXiv 论文采集器

数据源：arXiv Atom XML API（无需认证）
API 文档：https://info.arxiv.org/help/api/index.html

采集策略：
  1. 按 AI/CL/LG/CV 分类查询最新论文（最多 100 条）
  2. 解析 Atom XML，提取标题、摘要、作者、标签等
  3. 用 LLM/Agent 相关关键词做二次过滤
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
import re

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SOURCE_TIMEOUT, SOURCE_RETRY, RAW_DIR, GITHUB_TOKEN, AI_KEYWORDS, DOMAIN_WHITELIST
from models import NewsItem
from utils.http import create_session, fetch_with_timeout

# ── 常量 ───────────────────────────────────────────────────
ARXIV_API_URL = "http://export.arxiv.org/api/query"
ARXIV_ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

# LLM / Agent 相关关键词（比通用 AI_KEYWORDS 更聚焦）
LLM_KEYWORDS = [
    "llm", "large language model", "agent", "gpt", "claude", "gemini",
    "language model", "transformer", "prompt", "rag", "fine-tun",
    "alignment", "instruction", "chat", "conversational", "generative",
    "embedding", "tokenizer", "attention mechanism", "self-attention",
    "reinforcement learning from human", "rlhf", "chain-of-thought",
    "few-shot", "zero-shot", "multimodal", "vision language",
    "diffusion", "autoregressive", "pre-train", "pretrain",
    "parameter-efficient", "lora", "qlora", "adapter",
    "mistral", "llama", "deepseek", "qwen", "mixtral",
    "openai", "anthropic", "copilot", "code generation",
    "tool use", "function calling", "reasoning", "world model",
    "retrieval augmented", "knowledge graph", "semantic search",
]


def _parse_arxiv_datetime(text: str) -> str:
    """将 arXiv 的 Atom 日期转为 ISO8601 格式。

    arXiv 返回的时间格式示例：2024-01-15T18:59:59Z
    """
    if not text:
        return ""
    try:
        # 尝试标准 ISO 格式解析
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, TypeError):
        return text


def _is_llm_related(title: str, summary: str) -> bool:
    """判断论文标题/摘要是否与 LLM / Agent 相关。

    Args:
        title: 论文标题。
        summary: 论文摘要。

    Returns:
        True 表示该论文值得收录。
    """
    text = (title + " " + summary).lower()
    for kw in LLM_KEYWORDS:
        if kw.lower() in text:
            return True
    # 也检查全局 AI_KEYWORDS（覆盖更广）
    for kw in AI_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def collect_arxiv() -> list[NewsItem]:
    """采集 arXiv 最新 AI/CL/LG/CV 分类论文，返回 LLM/Agent 相关列表。

    Returns:
        AI 相关论文的 NewsItem 列表；发生异常时返回空列表。
    """
    timeout = SOURCE_TIMEOUT.get("arxiv", 30)
    session = create_session()
    items: list[NewsItem] = []

    # 查询字符串：多个分类用 OR 连接
    query_params = (
        "search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV"
        "&sortBy=submittedDate&sortOrder=descending&max_results=100"
    )
    url = f"{ARXIV_API_URL}?{query_params}"

    try:
        print("[arxiv] 正在请求 arXiv API ...")
        resp = fetch_with_timeout(session, url, timeout=timeout)

        # ── 解析 Atom XML ─────────────────────────────
        root = ElementTree.fromstring(resp.content)

        # 注册命名空间以便查找
        ns = {"atom": ARXIV_ATOM_NS}

        entries = root.findall("atom:entry", ns)
        print(f"[arxiv] API 返回 {len(entries)} 条论文")

        raw_entries: list[dict] = []

        for entry in entries:
            try:
                # 标题（去除首尾空格和换行）
                title_el = entry.find("atom:title", ns)
                title = ""
                if title_el is not None and title_el.text:
                    title = " ".join(title_el.text.split()).strip()

                # 摘要
                summary_el = entry.find("atom:summary", ns)
                summary = ""
                if summary_el is not None and summary_el.text:
                    summary = " ".join(summary_el.text.split()).strip()

                raw_entries.append({"title": title, "summary": summary[:200]})

                # LLM / Agent 相关性过滤
                if not _is_llm_related(title, summary):
                    continue

                # 发表时间
                published_el = entry.find("atom:published", ns)
                published_at = _parse_arxiv_datetime(
                    published_el.text if published_el is not None else ""
                )

                # 更新日期
                updated_el = entry.find("atom:updated", ns)
                updated_at = _parse_arxiv_datetime(
                    updated_el.text if updated_el is not None else ""
                )

                # 论文链接：取 <link> 中 rel="alternate" 的 href
                url = ""
                for link_el in entry.findall("atom:link", ns):
                    rel = link_el.get("rel", "")
                    if rel == "alternate":
                        href = link_el.get("href", "")
                        if href:
                            # 去除版本号后缀（v1, v2 等）
                            url = re.sub(r"v\d+$", "", href)
                            break
                if not url:
                    # 兜底：用 <id> 元素
                    id_el = entry.find("atom:id", ns)
                    if id_el is not None and id_el.text:
                        url = re.sub(r"v\d+$", "", id_el.text.strip())

                # 作者（仅取第一位）
                author_el = entry.find("atom:author", ns)
                author = ""
                if author_el is not None:
                    name_el = author_el.find("atom:name", ns)
                    if name_el is not None and name_el.text:
                        author = name_el.text.strip()

                # 分类标签（<category term="cs.AI"/>）
                tags = []
                for cat_el in entry.findall("atom:category", ns):
                    term = cat_el.get("term", "")
                    if term:
                        tags.append(term)

                # 构建新闻条目
                item = NewsItem(
                    source="arxiv",
                    source_type="paper",
                    title=title,
                    url=url,
                    canonical_url=url,
                    author=author,
                    published_at=published_at,
                    summary_raw=summary,
                    tags=tags,
                    metrics={
                        "score": 0,
                        "comments": 0,
                        "stars_today": 0,
                        "github_stars": 0,
                    },
                    evidence={
                        "hn": False,
                        "hf_papers": True,  # arXiv 是 HF Papers 的上游
                        "github": False,
                        "reddit": False,
                    },
                )
                items.append(item)

            except Exception as e:
                print(f"[arxiv] 解析单条论文失败: {e}")
                continue

        # ── 保存原始数据用于调试 ───────────────────────
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            raw_path = RAW_DIR / f"arxiv_{date_str}.json"
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw_entries, f, ensure_ascii=False, indent=2)
            print(f"[arxiv] 原始数据已保存: {raw_path}")
        except Exception as e:
            print(f"[arxiv] 保存原始数据失败: {e}")

        # 礼貌性休眠（后续若分页扩量，保持间隔）
        time.sleep(3)

        print(f"[arxiv] 采集完成: {len(items)} 条")
        return items

    except Exception as e:
        print(f"[arxiv] 采集异常: {e}")
        # 确保异常路径也触发休眠
        try:
            time.sleep(3)
        except Exception:
            pass
        return []
