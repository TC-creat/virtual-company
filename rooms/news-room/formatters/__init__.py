"""
formatters —— 日报格式化输出模块

包含两个格式化器：

    1. daily_summary — 微信推送精简版日报（短文本、emoji 标记、每项最多4行）
    2. daily_detail  — 完整 Markdown 日报（表格统计、详细评分、标签、失败源列表）

典型用法：

    from processors.scoring import score_items, select_top
    from formatters.daily_summary import render_wechat_text
    from formatters.daily_detail import render_markdown

    top_items = select_top(ranked, k=8)
    wechat = render_wechat_text(top_items, stats)
    md = render_markdown(top_items, stats, failures)
"""
