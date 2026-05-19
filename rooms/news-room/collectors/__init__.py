"""
AI 新闻采集器包

每个子模块对应一个独立数据源，采集函数签名统一为：
    def collect_<source>() -> list[NewsItem]:

当前支持的采集器：
  - hacker_news    : Hacker News 社区热门 (Firebase API)
  - arxiv          : arXiv 论文预印本 (Atom XML API)
  - github_trending: GitHub 趋势仓库 (网页 + Search API)
  - huggingface    : Hugging Face Papers (网页抓取)
"""
