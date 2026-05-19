"""
统一 HTTP 会话与重试工具
提供全局可复用的 requests.Session 工厂、重试装饰器、超时封装，
降低各采集器之间的重复代码。
"""
import functools
import logging
import ssl
import time
from typing import Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout
from urllib3.poolmanager import PoolManager
from urllib3.util.ssl_ import create_urllib3_context

logger = logging.getLogger(__name__)

# ── 默认请求头 ──────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": "AI-News-Room/1.0",
    "Accept-Language": "zh-CN,en-US;q=0.9",
    "Accept": "text/html,application/json,*/*;q=0.8",
}


class _PermissiveSSLAdapter(HTTPAdapter):
    """自定义 HTTPS Adapter：使用宽松 SSL 上下文以穿透不稳定代理。

    部分站点（GitHub、HuggingFace）通过 Clash/V2Ray 代理时，
    CONNECT 隧道内的 TLS 握手可能触发 SSLEOFError。
    此 Adapter 使用 CERT_NONE + 关闭 hostname 检查，
    让 TLS 层只加密不验证书，绕过代理干扰。
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def create_session(
    headers: Optional[dict] = None,
    bypass_proxy: bool = False,
) -> requests.Session:
    """创建统一的 requests.Session，注入默认请求头 + 宽松 SSL Adapter。

    Args:
        headers: 可选，与默认头合并的额外头字段。
        bypass_proxy: True 时绕过系统代理直连。

    Returns:
        配置好的 requests.Session 实例。
    """
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    merged = DEFAULT_HEADERS.copy()
    if headers:
        merged.update(headers)
    session.headers.update(merged)

    # SSL 兼容：挂载宽松 Adapter，绕过代理 TLS 干扰
    adapter = _PermissiveSSLAdapter()
    session.mount("https://", adapter)

    # 关闭证书验证（与 Adapter 的 CERT_NONE 配合）
    session.verify = False

    if bypass_proxy:
        session.trust_env = False

    return session


def retry_request(
    func: Optional[Callable] = None,
    *,
    retries: int = 2,
    backoff: float = 1.5,
) -> Callable:
    """重试装饰器：捕获 RequestException/Timeout，按指数退避重试。

    可作无参数装饰器使用：@retry_request
    也可带参数：          @retry_request(retries=3, backoff=2.0)

    Args:
        func: 被装饰的函数。
        retries: 最大重试次数（不含首次调用）。
        backoff: 退避系数，第 n 次重试前等待 backoff**n 秒。

    Returns:
        包装后的函数。
    """
    if func is None:
        return functools.partial(retry_request, retries=retries, backoff=backoff)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(retries + 1):
            try:
                return func(*args, **kwargs)
            except (RequestException, Timeout) as exc:
                last_exc = exc
                if attempt < retries:
                    wait = backoff ** (attempt + 1)
                    logger.warning(
                        "请求失败 (尝试 %d/%d): %s，%.1f 秒后重试",
                        attempt + 1, retries + 1, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "请求最终失败 (已重试 %d 次): %s", retries, exc,
                    )
        raise last_exc  # type: ignore[misc]

    return wrapper


def fetch_with_timeout(
    session: requests.Session,
    url: str,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """带超时的 GET 请求封装。

    与直接调用 session.get() 的区别：
      - 强制要求 timeout 参数（防止请求挂死）
      - 遇到网络错误时统一记录日志

    Args:
        session: requests.Session 实例。
        url: 目标 URL。
        timeout: 超时秒数。
        **kwargs: 透传给 session.get() 的额外参数。

    Returns:
        requests.Response 对象。

    Raises:
        RequestException: 网络层 / HTTP 错误。
        Timeout: 请求超时。
    """
    logger.debug("Fetching: %s (timeout=%d)", url, timeout)
    try:
        resp = session.get(url, timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp
    except Timeout:
        logger.warning("请求超时: %s (timeout=%d)", url, timeout)
        raise
    except RequestException as exc:
        logger.warning("请求异常: %s -> %s", url, exc)
        raise
