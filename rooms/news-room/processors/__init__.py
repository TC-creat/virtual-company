"""
processors —— 新闻采集后处理流水线

包含三大模块，按处理顺序串联使用：

    1. filtering  — 粗过滤（时间窗口、AI相关性、黑名单、低质量丢弃）
    2. dedup      — 去重与聚类（URL标准化、标题相似度、跨源证据合并）
    3. scoring    — 评分与排序（时效性、热度、权威度、跨源热度、综合加权）

典型用法：

    from processors.filtering import run_filters
    from processors.dedup import run_dedup
    from processors.scoring import score_items, select_top

    items = load_from_collectors()
    items = run_filters(items)
    items = run_dedup(items)
    items = score_items(items)
    top = select_top(items, k=8)
"""
