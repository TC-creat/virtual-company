"""
URL 规范化工具
统一清洗来自不同源的 URL，去除埋点参数、GitHub/arXiv 等
知名站点上的语义冗余片段，确保同一篇文章在不同采集器中的
URL 能够被正确去重。
"""
import re
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs, ParseResult


# ── 需要剥离的跟踪参数 ──────────────────────────────────
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "source_url", "si", "mc_cid", "mc_eid",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid",
    "twclid", "scm", "campaign", "feature", "gi",
}


def _strip_tracking_params(query: str) -> str:
    """从 query string 中移除跟踪参数。"""
    params = parse_qs(query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}
    if not cleaned:
        return ""
    return urlencode(cleaned, doseq=True)


def _normalize_github(parsed: ParseResult) -> ParseResult:
    """规范化 GitHub URL：移除 /tree/main/、/blob/main/ 等分支前缀。

    输入: https://github.com/user/repo/tree/main/path/to/file
    输出: https://github.com/user/repo/path/to/file
    """
    if parsed.netloc.lower() != "github.com":
        return parsed

    parts = parsed.path.split("/")
    # path 格式: /user/repo/...
    if len(parts) < 4:
        return parsed

    # parts[1]=user, parts[2]=repo, parts[3] 之后是目录结构
    # 支持常见的分支引用前缀
    branch_prefixes = {"tree", "blob"}
    if parts[3] in branch_prefixes and len(parts) >= 5:
        # 移除 /tree/main 或 /blob/main 两段
        new_path = "/".join(parts[:3] + parts[5:])
        return ParseResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=new_path,
            params=parsed.params,
            query=parsed.query,
            fragment=parsed.fragment,
        )

    # 处理带 # 锚点的 hash URL（如 GitHub 文件锚点）
    # 目前保持 fragment 不变，仅在必要时剥离
    return parsed


def _normalize_arxiv(parsed: ParseResult) -> ParseResult:
    """规范化 arXiv URL：移除版本号后缀。

    输入: https://arxiv.org/abs/2401.12345v2
    输出: https://arxiv.org/abs/2401.12345
    输入: https://arxiv.org/pdf/2401.12345v3
    输出: https://arxiv.org/pdf/2401.12345
    """
    if parsed.netloc.lower() not in ("arxiv.org", "www.arxiv.org"):
        return parsed

    # 匹配 /abs/XXXX.XXXXXvN 或 /pdf/XXXX.XXXXXvN
    new_path = re.sub(
        r"^(/(?:abs|pdf)/\d{4}\.\d{4,5})v\d+$",
        r"\1",
        parsed.path,
    )
    return ParseResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path=new_path,
        params=parsed.params,
        query=parsed.query,
        fragment=parsed.fragment,
    )


def canonicalize_url(url: str) -> str:
    """规范化 URL 以便去重和存储。

    处理项：
      1. 剥离跟踪参数（utm_*, ref, fbclid, gclid 等）
      2. 规范化 GitHub 链接（移除 /tree/main/、/blob/main/）
      3. 规范化 arXiv 链接（移除版本号 v1, v2 等）
      4. hostname 转小写
      5. 移除尾部斜杠（保留根路径 "/"）

    Args:
        url: 原始 URL 字符串。

    Returns:
        清洗后的 URL。如果输入不合法则原样返回。
    """
    if not url or not isinstance(url, str):
        return url

    url = url.strip()

    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    # 如果没有 scheme，视为 relative URL 直接返回
    if not parsed.scheme:
        return url

    # ── 规范化 ────────────────────────────────────────
    parsed = parsed._replace(netloc=parsed.netloc.lower())
    parsed = parsed._replace(query=_strip_tracking_params(parsed.query))
    parsed = _normalize_github(parsed)
    parsed = _normalize_arxiv(parsed)

    # 移除尾部斜杠（但保留根路径 "/"）
    path = parsed.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    parsed = parsed._replace(path=path)

    return urlunparse(parsed)
