"""
DeepSeek API 客户端 - Phase 3 启用
用于对候选新闻进行LLM打分和摘要增强
"""
import json
import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT,
    LLM_CANDIDATE_SIZE,
)
from models import NewsItem

logger = logging.getLogger("deepseek")


class DeepSeekClient:
    """DeepSeek API 封装"""

    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL.rstrip("/")
        self.model = DEEPSEEK_MODEL
        self.timeout = DEEPSEEK_TIMEOUT

    @property
    def available(self) -> bool:
        """检查API Key是否可用"""
        return bool(self.api_key)

    def _call(self, messages: list[dict], temperature: float = 0.3) -> Optional[str]:
        """调用DeepSeek Chat API"""
        if not self.available:
            logger.warning("DeepSeek API Key 未配置，跳过LLM调用")
            return None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            return None

    def summarize_item(self, item: NewsItem) -> dict:
        """对单条新闻进行LLM摘要（中文一句话 + 技术要点 + 影响判断 + 入选理由）"""
        from llm.prompts import SUMMARIZE_PROMPT

        prompt = SUMMARIZE_PROMPT.format(
            title=item.title,
            source=item.source,
            summary=item.summary_raw[:500],
            tags=", ".join(item.tags) if item.tags else "无",
        )

        result = self._call([{"role": "user", "content": prompt}])
        if not result:
            return item.deepseek

        # 解析JSON响应
        try:
            parsed = json.loads(result)
            return {
                "one_line_summary": parsed.get("one_line_summary", ""),
                "technical_points": parsed.get("technical_points", []),
                "impact": parsed.get("impact", ""),
                "reason": parsed.get("reason", ""),
            }
        except json.JSONDecodeError:
            # 降级：直接用原文
            return {
                "one_line_summary": result[:120],
                "technical_points": [],
                "impact": "",
                "reason": "",
            }

    def score_candidates(self, items: list[NewsItem]) -> list[NewsItem]:
        """对候选列表进行LLM打分（批量评分）"""
        if not self.available:
            return items

        from llm.prompts import SCORING_PROMPT

        # 只取前LLM_CANDIDATE_SIZE条
        candidates = items[:LLM_CANDIDATE_SIZE]

        # 构建候选列表文本
        candidate_text = ""
        for i, item in enumerate(candidates, 1):
            candidate_text += f"{i}. [{item.source_type}] {item.title}\n"
            candidate_text += f"   摘要: {item.summary_raw[:150]}\n"
            candidate_text += f"   热度: score={item.metrics.get('score', 0)}, stars={item.metrics.get('stars_today', 0)}\n\n"

        prompt = SCORING_PROMPT.format(candidates=candidate_text)
        result = self._call([{"role": "user", "content": prompt}])

        if not result:
            return items

        # 解析打分结果（预期格式: "1:8.5, 3:9.0, 5:7.2"）
        try:
            scores = {}
            for part in result.split(","):
                part = part.strip()
                if ":" in part:
                    idx, score = part.split(":")
                    scores[int(idx.strip())] = float(score.strip())

            for i, item in enumerate(candidates, 1):
                if i in scores:
                    item.quality["llm_score"] = min(1.0, scores[i] / 10.0)
                    item.quality["final_score"] = (
                        item.quality["rule_score"] * 0.7 + item.quality["llm_score"] * 0.3
                    )
        except (ValueError, IndexError):
            logger.warning("LLM打分结果解析失败，使用规则分数")

        # 按final_score重排
        items[:LLM_CANDIDATE_SIZE] = sorted(
            candidates, key=lambda x: x.quality["final_score"], reverse=True
        )
        return items


# 全局单例
_client: Optional[DeepSeekClient] = None


def get_deepseek_client() -> DeepSeekClient:
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
