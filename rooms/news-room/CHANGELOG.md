# CHANGELOG

## [0.2.0] - 2026-05-19

### Added
- DeepSeek 中文一句话摘要：评分后对 Top 8 条目调用 DeepSeek 生成中文摘要
- 宽松 SSL Adapter：自定义 HTTPAdapter 解决 GitHub/HuggingFace 通过代理时的 TLS 握手问题
- 直连回退：GitHub 和 HuggingFace 采集器在代理失败后自动尝试直连
- Hermes cron 定时推送：每天 7:30 自动运行，结果推送到微信

### Changed
- 推送模块重构：改为 stdout 输出 + Hermes cron --no-agent 捕获投递
- `send_daily()` 接受 NewsItem 对象而非 dict，修复序列化 bug
- `create_session()` 增加 `bypass_proxy` 参数

### Fixed
- `hermes_pusher.py` 中 `'NewsItem' object has no attribute 'get'` 错误

## [0.1.0] - 2026-05-18

### Added
- 项目骨架：models, config, 采集器/处理器/格式化器/推送模块
- 4 个数据源采集器：Hacker News, arXiv, GitHub Trending, HuggingFace
- 处理管线：过滤 → 去重 → 评分 → 格式化
- 双格式输出：微信精简版 + Markdown 详细版
- DeepSeek API 客户端（prompts + client，未接入管线）
