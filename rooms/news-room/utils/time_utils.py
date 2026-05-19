"""
时间日期工具函数
集中管理项目的 ISO8601 序列化 / 反序列化、
中文日期格式化以及时效判断逻辑。
"""
from datetime import datetime, timezone, timedelta


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO8601 字符串。

    Returns:
        形如 "2026-05-19T12:34:56+00:00" 的字符串。
    """
    return datetime.now(timezone.utc).isoformat()


def parse_iso(s: str) -> datetime:
    """解析 ISO8601 字符串为 timezone-aware datetime。

    支持常见格式：
      - "2026-05-19T12:34:56Z"
      - "2026-05-19T12:34:56+00:00"
      - "2026-05-19T12:34:56.123456+00:00"

    Args:
        s: ISO8601 字符串。

    Returns:
        带 UTC 时区的 datetime 对象。

    Raises:
        ValueError: 字符串格式无法解析。
    """
    # Python 3.11+ 的 fromisoformat 支持 Z 后缀，
    # 此处做兼容处理
    normalized = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hours_ago(dt: datetime, hours: int) -> bool:
    """判断给定时间是否在最近 N 小时内。

    Args:
        dt: 待判断的时间（应带时区，否则视为 UTC）。
        hours: 时间窗口（小时数）。

    Returns:
        若 dt 在 now-{hours} ~ now 之间返回 True，否则 False。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return cutoff <= dt <= now


def format_cn(dt: datetime) -> str:
    """将 datetime 格式化为中文日期字符串。

    Args:
        dt: 待格式化的时间。

    Returns:
        形如 "2026年5月19日" 的中文日期。
    """
    return f"{dt.year}年{dt.month}月{dt.day}日"
