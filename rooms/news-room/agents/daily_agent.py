#!/usr/bin/env python3
"""
AI新闻日报采集 - 主编排器
用法: python agents/daily_agent.py [--date YYYY-MM-DD] [--skip-push] [--dry-run]
"""
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    SOURCES, PROJECT_ROOT, DATA_DIR, RAW_DIR, ARTIFACTS_DIR, LOG_DIR,
    TOP_K_SUMMARY, TIME_WINDOW_HOURS,
)
from models import NewsItem
from utils.time_utils import now_iso, format_cn

# ── 日志配置 ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"daily_{datetime.now():%Y%m%d}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("daily_agent")


def collect_all(date_str: str) -> list[NewsItem]:
    """并发采集所有启用的数据源，单源失败不影响其他源"""
    all_items = []
    failures = {}

    # 动态导入采集器
    collectors = {}
    if SOURCES.get("hacker_news"):
        from collectors.hacker_news import collect_hacker_news
        collectors["hacker_news"] = collect_hacker_news
    if SOURCES.get("arxiv"):
        from collectors.arxiv import collect_arxiv
        collectors["arxiv"] = collect_arxiv
    if SOURCES.get("github_trending"):
        from collectors.github_trending import collect_github_trending
        collectors["github_trending"] = collect_github_trending
    if SOURCES.get("huggingface"):
        from collectors.huggingface import collect_huggingface
        collectors["huggingface"] = collect_huggingface

    logger.info(f"开始采集: {len(collectors)} 个数据源")

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): name for name, fn in collectors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                items = future.result()
                all_items.extend(items)
                logger.info(f"[{name}] 采集完成: {len(items)} 条")
            except Exception as e:
                logger.error(f"[{name}] 采集失败: {e}")
                failures[name] = str(e)

    # 保存原始数据
    raw_path = RAW_DIR / f"all_raw_{date_str}.json"
    with open(raw_path, "w") as f:
        json.dump([it.to_dict() for it in all_items], f, ensure_ascii=False, indent=2)
    logger.info(f"原始数据已保存: {raw_path} ({len(all_items)} 条)")

    return all_items


def process_pipeline(items: list[NewsItem]) -> tuple[list[NewsItem], dict]:
    """过滤 → 去重 → 评分 → DeepSeek摘要增强"""
    from processors.filtering import run_filters
    from processors.dedup import run_dedup
    from processors.scoring import score_items, select_top
    from llm.deepseek_client import get_deepseek_client

    stats = {
        "raw_count": len(items),
        "filtered_count": 0,
        "deduped_count": 0,
        "final_count": 0,
    }

    # 过滤
    items = run_filters(items)
    stats["filtered_count"] = len(items)

    # 去重
    items = run_dedup(items)
    stats["deduped_count"] = len(items)

    # 评分
    items = score_items(items)
    items = select_top(items, k=TOP_K_SUMMARY)
    stats["final_count"] = len(items)

    # DeepSeek 中文摘要增强
    ds_client = get_deepseek_client()
    if ds_client.available:
        logger.info("开始 DeepSeek 摘要增强…")
        for item in items:
            try:
                result = ds_client.summarize_item(item)
                if result:
                    item.deepseek.update(result)
            except Exception as e:
                logger.warning(f"DeepSeek 摘要生成失败 [{item.id}]: {e}")
    else:
        logger.info("DeepSeek API Key 未配置，跳过摘要增强")

    return items, stats


def format_output(items: list[NewsItem], stats: dict, failures: dict, date_str: str) -> dict:
    """格式化输出：精简版 + 详细版"""
    from formatters.daily_summary import render_wechat_text
    from formatters.daily_detail import render_markdown

    summary_text = render_wechat_text(items, stats)
    detail_md = render_markdown(items, stats, failures)

    # 保存
    summary_path = ARTIFACTS_DIR / f"daily_summary_{date_str}.txt"
    detail_path = ARTIFACTS_DIR / f"daily_detail_{date_str}.md"

    with open(summary_path, "w") as f:
        f.write(summary_text)
    with open(detail_path, "w") as f:
        f.write(detail_md)

    logger.info(f"产物已保存: {summary_path}, {detail_path}")

    return {"summary": summary_text, "detail": detail_md, "summary_path": summary_path, "detail_path": detail_path}


def push_output(items: list[NewsItem], stats: dict, formatted: dict):
    """推送日报"""
    try:
        from push.hermes_pusher import send_daily
        send_daily(items, stats, summary_text=formatted.get("summary", ""))
        logger.info("推送完成")
    except Exception as e:
        logger.warning(f"推送失败（不影响本地产物）: {e}")


def run(date_str: str = None, skip_push: bool = False, dry_run: bool = False):
    """主编排入口"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"======== AI新闻日报采集启动 ========")
    logger.info(f"日期: {date_str} | dry_run={dry_run} | skip_push={skip_push}")
    t0 = datetime.now()

    failures = {}

    # 1. 采集
    items = collect_all(date_str)
    if dry_run:
        logger.info(f"[DRY-RUN] 采集到 {len(items)} 条，不保存不推送，退出")
        return

    # 2. 处理
    items, stats = process_pipeline(items)

    # 3. 格式化
    formatted = format_output(items, stats, failures, date_str)

    # 4. 推送
    if not skip_push:
        push_output(items, stats, formatted)

    # 5. 运行报告
    elapsed = (datetime.now() - t0).total_seconds()
    report = f"""
======== 运行报告 ========
日期: {date_str}
耗时: {elapsed:.1f} 秒
原始: {stats['raw_count']} 条 → 过滤: {stats['filtered_count']} 条 → 去重: {stats['deduped_count']} 条 → 入选: {stats['final_count']} 条
失败源: {', '.join(failures.keys()) if failures else '无'}
产物: {formatted.get('summary_path', 'N/A')}
=========================="""
    logger.info(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI新闻日报采集器")
    parser.add_argument("--date", type=str, default=None, help="采集日期 YYYY-MM-DD")
    parser.add_argument("--skip-push", action="store_true", help="跳过推送")
    parser.add_argument("--dry-run", action="store_true", help="只采集不保存不推送")
    args = parser.parse_args()

    run(date_str=args.date, skip_push=args.skip_push, dry_run=args.dry_run)
