"""HTTP 层：请求头、Cookie、直连（默认绕过代理）、重试。

实测结论（2026-10，本机）：
  - 直连小红书（绕过本机代理）可用，走代理反而多一层变量
  - 伪造 web_session 会被 500 拒掉 —— Cookie 只原样透传用户提供的，绝不自己造
  - 未登录访问 /explore 首页返回 200 且带 __INITIAL_STATE__（feeds 为空），
    说明匿名会话能拿到 SSR 数据，笔记页是否有数据取决于笔记本身与风控
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import requests

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)

RETRYABLE = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


class FetchError(RuntimeError):
    """请求失败，message 里带用户可读的原因。"""


@dataclass
class ClientConfig:
    cookie: str = ""                   # 用户浏览器里复制的整串 Cookie（至少含 web_session / a1）
    proxy: str = ""                    # 空 = 直连（默认）；"http://127.0.0.1:7890" 走代理
    timeout: int = 30
    retries: int = 3
    mobile_ua: bool = False
    extra_headers: dict = field(default_factory=dict)

    def headers(self) -> dict:
        h = {
            "User-Agent": UA_MOBILE if self.mobile_ua else UA_DESKTOP,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.extra_headers:
            h.update(self.extra_headers)
        return h


def build_session(cfg: ClientConfig) -> requests.Session:
    s = requests.Session()
    s.headers.update(cfg.headers())
    if cfg.proxy:
        s.proxies = {"http": cfg.proxy, "https": cfg.proxy}
    else:
        s.trust_env = False            # 关键：忽略系统代理，直连国内站
    return s


def get(session: requests.Session, url: str, cfg: ClientConfig, *,
        allow_redirects: bool = True, label: str = "") -> requests.Response:
    """带退避重试的 GET。风控页 / 登录墙 / 已删除会转成可读错误。"""
    last_exc: Exception | None = None
    for attempt in range(1, cfg.retries + 1):
        try:
            resp = session.get(
                url, timeout=cfg.timeout, allow_redirects=allow_redirects,
                headers={"Referer": "https://www.xiaohongshu.com/"},
            )
            break
        except RETRYABLE as exc:
            last_exc = exc
            if attempt == cfg.retries:
                raise FetchError(f"网络错误（重试 {cfg.retries} 次后仍失败）：{exc}") from exc
            sleep_s = min(2 ** attempt + random.random(), 10)
            time.sleep(sleep_s)

    if resp.status_code == 461:
        raise FetchError("被小红书风控拦截（HTTP 461）。建议：换网络/稍后再试，或在 Cookie 里提供有效的 web_session")
    if resp.status_code == 403:
        raise FetchError("拒绝访问（HTTP 403）。笔记可能仅自己可见，或 Cookie 已失效")
    if resp.status_code >= 500:
        raise FetchError(f"小红书服务端错误（HTTP {resp.status_code}），稍后重试")
    if resp.status_code == 404:
        raise FetchError("笔记不存在（HTTP 404）：已删除、ID 写错，或链接里的 xsec_token 失效")
    if resp.status_code != 200:
        raise FetchError(f"意外的 HTTP {resp.status_code}（{label or url}）")
    if "login" in str(resp.url) and "/login" in urlsplit_path(resp.url):
        raise FetchError("被重定向到登录页：该内容需要登录态。请用 --cookie 提供浏览器里的 Cookie")
    return resp


def urlsplit_path(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).path


def resolve_short_link(session: requests.Session, short_url: str, cfg: ClientConfig) -> str:
    """xhslink.com 短链 → 真实笔记地址（跟随 302，不下载正文）。"""
    resp = get(session, short_url, cfg, allow_redirects=True, label="短链解析")
    return str(resp.url)


def head_ok(session: requests.Session, url: str, cfg: ClientConfig) -> tuple[bool, int]:
    """HEAD 探测媒体直链是否可用，返回 (ok, content_length)。"""
    try:
        r = session.head(url, timeout=cfg.timeout, allow_redirects=True,
                         headers={"Referer": "https://www.xiaohongshu.com/"})
        return r.status_code == 200, int(r.headers.get("Content-Length") or 0)
    except requests.RequestException:
        return False, 0
