"""
全局配置 - AI新闻采集系统
"""
import os
from pathlib import Path

# ── 项目路径 ───────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
LOG_DIR = DATA_DIR / "logs"

# 确保目录存在
for d in [DATA_DIR, RAW_DIR, ARTIFACTS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── 数据源开关 ─────────────────────────────────────────
SOURCES = {
    "hacker_news": True,
    "arxiv": True,
    "github_trending": True,
    "huggingface": True,
}

# ── 各源超时与重试 ────────────────────────────────────
SOURCE_TIMEOUT = {
    "hacker_news": 15,
    "arxiv": 30,
    "github_trending": 20,
    "huggingface": 20,
}

SOURCE_RETRY = {
    "hacker_news": 2,
    "arxiv": 2,
    "github_trending": 2,
    "huggingface": 2,
}

# ── 日报与LLM候选 ─────────────────────────────────────
TOP_K_SUMMARY = 8       # 日报精选条数
LLM_CANDIDATE_SIZE = 24  # 送入LLM打分的候选数

# ── 评分权重 ──────────────────────────────────────────
SCORE_WEIGHTS = {
    "source_authority": 0.35,
    "recency": 0.20,
    "heat": 0.20,
    "cross_source": 0.10,
    "llm": 0.15,  # Phase 3启用
}

# ── 时间窗口（小时）───────────────────────────────────
TIME_WINDOW_HOURS = 24

# ── DeepSeek 配置 ─────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 60

# ── GitHub Token（可选）────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# ── Hermes 推送配置 ───────────────────────────────────
HERMES_ENABLED = os.getenv("HERMES_ENABLED", "false").lower() == "true"
HERMES_API_URL = os.getenv("HERMES_API_URL", "http://localhost:8000")

# ── AI 关键词白名单 ───────────────────────────────────
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "agent", "gpt", "claude", "gemini",
    "llama", "mistral", "openai", "anthropic", "diffusion", "transformer",
    "rag", "mcp", "model context protocol", "fine-tun", "prompt",
    "neural network", "nlp", "natural language", "computer vision",
    "reinforcement learning", "rlhf", "embedding", "vector database",
    "langchain", "autogpt", "chatgpt", "copilot", "cursor",
    "deepseek", "qwen", "mixtral", "falcon", "stable diffusion",
    "sora", "dall-e", "midjourney", "whisper", "tts",
    "tokenizer", "attention mechanism", "self-attention",
    "zero-shot", "few-shot", "chain-of-thought", "tree-of-thoughts",
    "multimodal", "vision language", "vlm", "text-to-",
    "huggingface", "hugging face", "gradio", "streamlit",
]

# ── 域名白名单（即使标题不匹配也收录）─────────────────
DOMAIN_WHITELIST = [
    "openai.com", "anthropic.com", "huggingface.co",
    "arxiv.org", "github.com", "deepmind.google",
    "meta.ai", "mistral.ai", "cohere.com",
]

# ── 标题/域名黑名单 ───────────────────────────────────
TITLE_BLACKLIST = [
    "sponsor", "advertisement", "sponsored", "webinar",
    "hiring", "job", "survey", "buy", "discount",
]
DOMAIN_BLACKLIST = [
    "youtube.com", "youtu.be", "tiktok.com",
    "instagram.com", "facebook.com",
]
