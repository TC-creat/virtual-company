# AI新闻采集系统

每日自动采集 Hacker News、arXiv、GitHub Trending、HuggingFace Papers 的 AI 相关内容，规则过滤 + 评分排序 + DeepSeek 中文摘要增强，生成日报通过 Hermes 推送到微信。

## 架构

```
news-room/
├── agents/          # 主编排器
├── collectors/      # 数据源采集器 (HN / arXiv / GitHub / HF)
├── processors/      # 过滤 / 去重 / 评分
├── formatters/      # 日报格式化（精简版 + 详细版）
├── llm/             # DeepSeek 摘要增强
├── push/            # 推送模块（Hermes cron deliver）
├── utils/           # HTTP 工具 + 宽松 SSL Adapter
├── data/            # 原始数据 & 产物 (gitignored)
├── .hermes/         # Hermes cron 配置
└── config.py        # 全局配置
```

## 数据流

```
HN / arXiv / GitHub / HF
       ↓
  [collectors] → 原始 NewsItem (并发采集, 单源失败不影响)
       ↓
  [filtering] → 时间窗口 + AI相关性 + 黑名单
       ↓
  [dedup]     → URL去重 + 标题相似度 + 跨源合并
       ↓
  [scoring]   → 规则打分（权威 + 热度 + 时效 + 跨源）
       ↓
  [DeepSeek]  → 一句话中文摘要生成
       ↓
  [format]    → 精简版(微信) + 详细版(Markdown)
       ↓
  [push]      → stdout → Hermes cron → 微信投递
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export DEEPSEEK_API_KEY="sk-xxx"
export GITHUB_TOKEN="ghp_xxx"  # 可选

# 试运行（只采集不保存）
python agents/daily_agent.py --dry-run

# 正式运行
python agents/daily_agent.py
```

## 定时运行

通过 Hermes cron 每天 7:30 AM 自动执行，结果推送到微信：

```bash
hermes cron list          # 查看已注册任务
hermes cron run <job-id>  # 手动触发一次
```

## 数据源状态

| 源 | 状态 | 说明 |
|----|------|------|
| Hacker News | ✅ | 正常采集 |
| arXiv | ✅ | 正常采集 |
| GitHub Trending | ⚠️ | 代理 SSL 不稳定，已添加宽松 Adapter + 直连回退 |
| HuggingFace Papers | ⚠️ | 同 GitHub，已添加直连回退 |

## 开发阶段

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 0 | 骨架搭建 | ✅ |
| Phase 1 | 规则采集与过滤 | ✅ |
| Phase 2 | 推送与稳定性 | ✅ |
| Phase 3 | DeepSeek 中文摘要增强 | ✅ |
