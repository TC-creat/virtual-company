"""
NewsItem 数据模型
"""
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """新闻条目统一数据模型"""
    # ── 标识 ──────────────────────────────────────
    id: str = ""
    source: str = ""            # hacker_news | arxiv | github_trending | huggingface
    source_type: str = ""       # community | paper | repo | media

    # ── 内容 ──────────────────────────────────────
    title: str = ""
    url: str = ""
    canonical_url: str = ""
    author: str = ""
    published_at: str = ""       # ISO8601
    collected_at: str = ""       # ISO8601
    summary_raw: str = ""        # 原始摘要
    content_snippet: str = ""    # 截断内容
    tags: list[str] = field(default_factory=list)

    # ── 指标 ──────────────────────────────────────
    metrics: dict = field(default_factory=lambda: {
        "score": 0,
        "comments": 0,
        "stars_today": 0,
        "github_stars": 0,
    })

    # ── 证据（跨源追踪）────────────────────────────
    evidence: dict = field(default_factory=lambda: {
        "hn": False,
        "hf_papers": False,
        "github": False,
        "reddit": False,
    })

    # ── 质量评分 ──────────────────────────────────
    quality: dict = field(default_factory=lambda: {
        "rule_score": 0.0,
        "llm_score": 0.0,
        "final_score": 0.0,
    })

    # ── 聚类 ──────────────────────────────────────
    cluster_key: str = ""

    # ── DeepSeek 增强 ─────────────────────────────
    deepseek: dict = field(default_factory=lambda: {
        "one_line_summary": "",
        "technical_points": [],
        "impact": "",
        "reason": "",
    })

    def __post_init__(self):
        """自动生成ID和采集时间"""
        if not self.id:
            raw = self.url or self.title
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.collected_at:
            self.collected_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return asdict(self)

    def to_json(self) -> str:
        """转为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "NewsItem":
        """从字典还原"""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
