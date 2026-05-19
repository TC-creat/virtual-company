# 第1轮：AI新闻模块上线完善

## 第一层：用户需求

用户（吴潘翔）在5月18日确认了虚拟公司AI新闻模块的架构。Claude Code已经生成了28个文件的核心代码，并成功跑了一期日报（8条精选）。但项目尚未完全上线，有以下遗留问题需要一次性解决：

1. 代码已存在但未推送到GitHub
2. 日报未通过微信实际推送给用户（hermes_pusher.py的HTTP POST是占位实现）
3. DeepSeek摘要增强（给每条新闻生成一句话中文摘要）客户端已写好但未接入评分管线
4. GitHub Trending和HuggingFace两个数据源因代理SSL问题无法采集
5. 没有自动定时运行（每天出日报）
6. README.md和CHANGELOG.md不完整

## 第二层：产品方案

### 核心交付
用户每天早上在微信收到一份AI日报，内容精炼、可直接阅读。

### 日报构成
- **精简版（微信）**：标题+一句话AI摘要（DeepSeek生成）+来源，8-10条
- **详细版（本地归档）**：完整内容，含技术要点

### 数据源
| 源 | 优先级 | 当前状态 |
|----|--------|---------|
| Hacker News | P0 | ✅ 可用 |
| arXiv | P0 | ✅ 可用 |
| GitHub Trending | P1 | ❌ SSL代理问题 |
| HuggingFace Papers | P1 | ❌ SSL代理问题 |

### 推送方式
通过Hermes cron的deliver机制，将日报文本直接通过微信网关推送给用户。

## 第三层：技术方案

### Task 1: 接入DeepSeek一句话摘要
- `processors/scoring.py` 未调用 `llm/deepseek_client.py` 
- 需要在 `processors/scoring.py` 的 `score_items()` 或独立步骤中调用 `DeepSeekClient.summarize_item()`
- 将生成的 `one_line_summary` 存入 `NewsItem.quality` 或新增字段
- `formatters/daily_summary.py` 需要读取该摘要替换原始标题
- 效果：日报从"标题+原始标题"变成"标题+一句话AI中文摘要+来源"

### Task 2: 修复GitHub Trending和HuggingFace的SSL问题
- 根因：通过Clash代理访问GitHub和HuggingFace时SSL握手失败
- 方案：在 `utils/http.py` 的 `create_session()` 中添加自定义SSL Adapter，跳过代理SSL验证，或改用SOCKS代理直连
- 或者：在collector层捕获SSLError并降级（跳过该源，不影响其他源）

### Task 3: 实现微信推送
- `hermes_pusher.py` 的 `send_daily()` 目前是占位实现（POST到本地8000端口）
- 实际方案：日报推文通过Hermes cron的deliver机制送达微信
- 具体做法：
  1. `daily_agent.py` 在执行结束时，格式化日报文本
  2. 通过 `terminal` 或Hermes的send_message机制发送给用户
  3. 或者：将日报文本写入文件，cron deliver时自动发送

### Task 4: 设置Hermes cron定时任务
- 已有 `.hermes/news-agent-daily.yaml` 但未注册
- 需要用 `hermes cron` 注册，每天7:30执行
- 确保deliver目标为用户的微信

### Task 5: 推送到GitHub并更新文档
- 在 `~/projects/virtual-company/` 初始化git仓库
- 添加 `.gitignore`（排除 `data/`, `__pycache__`, `.hermes/` 下的敏感文件）
- 提交并推送
- 更新 `README.md` 反映当前状态（Phase 1完成，Phase 2推送已实现）
- 创建 `CHANGELOG.md`

## 第四层：验收标准

1. ✅ `daily_agent.py` 完整运行一次，日报包含DeepSeek一句话摘要（中文）
2. ✅ 日报文本能通过微信发送到用户手机
3. ✅ GitHub Trending和HuggingFace至少有一个能成功采集（或明确降级说明）
4. ✅ cron定时任务已注册并确认配置正确
5. ✅ 代码已推送到GitHub
6. ✅ README和CHANGELOG已更新

## 调度顺序

先走Codex评估当前代码 → Codex输出补充方案 → Claude Code执行所有代码修改 → Codex验收 → 推GitHub
