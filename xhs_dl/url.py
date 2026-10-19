"""链接解析：短链跟随、笔记 ID 提取、URL 归一化。

支持的输入形态（可直接粘贴 App 分享出来的整段文案，工具会自己抽出链接）：
  - https://www.xiaohongshu.com/explore/<24hex>?xsec_token=...&xsec_source=...
  - https://www.xiaohongshu.com/discovery/item/<24hex>?...
  - https://www.xiaohongshu.com/note/<24hex>?...
  - http://xhslink.com/<code>            （App 分享短链，302 到真实地址）
  - 上述任意一种混在一段文字里
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

# 24 位十六进制是小红书笔记 ID 的固定形态
NOTE_ID_RE = re.compile(r"(?:explore|discovery/item|note)/([0-9a-f]{24})", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>）)]+", re.IGNORECASE)
XHS_HOST_RE = re.compile(r"(?:^|\.)xiaohongshu\.com$|xhslink\.com$", re.IGNORECASE)
NOTE_ID_BARE_RE = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)


class LinkError(ValueError):
    """输入不是一个可识别的小红书链接。"""


@dataclass
class NoteRef:
    """一次下载任务的链接归一化结果。"""

    note_id: str
    url: str = ""                      # 用于请求的完整 URL（含 xsec_token 等参数）
    original_url: str = ""             # 用户给的原始链接
    xsec_token: str = ""
    params: dict = field(default_factory=dict)
    was_short_link: bool = False

    def __str__(self) -> str:  # pragma: no cover
        return f"note_id={self.note_id} url={self.url or '(未请求)'}"


def extract_url(text: str) -> str:
    """从一段文案里抽出第一个 URL；本身就是 URL 时原样返回。"""
    text = (text or "").strip()
    m = URL_RE.search(text)
    if not m:
        raise LinkError("输入里没有找到 http(s) 链接")
    return m.group(0).rstrip(".,;，。；")


def is_xhs_url(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return bool(XHS_HOST_RE.search(host))


def parse_note_id(url: str) -> str:
    m = NOTE_ID_RE.search(url or "")
    if m:
        return m.group(1).lower()
    # 允许直接给 24 位纯 ID
    bare = (url or "").strip()
    if NOTE_ID_BARE_RE.match(bare):
        return bare.lower()
    raise LinkError(f"无法从链接中提取笔记 ID：{url!r}")


def split_params(url: str) -> tuple[str, dict]:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), parse_qs(parts.query)


def build_page_url(note_id: str, params: dict | None = None) -> str:
    """组装笔记页 URL。xsec_token 等参数原样带上。

    token 是 URL-safe base64，结尾常带 ``=``。urlencode 默认会把它转成 %3D，
    功能上等价但和真实链接长得不一样；用 safe 保留原样，diff 起来直观。
    """
    query = urlencode(
        {k: v for k, v in (params or {}).items() if v},
        doseq=True, safe="=-._~",
    )
    path = f"/explore/{note_id}"
    return urlunsplit(("https", "www.xiaohongshu.com", path, query, ""))


def parse_link(text: str) -> NoteRef:
    """把用户输入变成 NoteRef。短链在这里不做网络解析（那需要联网，见 fetch.resolve_short_link）。"""
    text = (text or "").strip()
    # 直接给 24 位纯 ID 的捷径
    if NOTE_ID_BARE_RE.match(text):
        nid = text.lower()
        return NoteRef(note_id=nid, url=build_page_url(nid), original_url=text)

    url = extract_url(text)
    if not is_xhs_url(url):
        raise LinkError(f"不是小红书链接（域名不认识）：{url}")

    is_short = "xhslink.com" in urlsplit(url).netloc.lower()
    if is_short:
        # 短链里没有笔记 ID，要等 302 之后才知道 —— 网络解析由调用方做
        return NoteRef(note_id="", url="", original_url=url, was_short_link=True)

    ref = NoteRef(note_id=parse_note_id(url), original_url=url)
    clean, params = split_params(url)
    flat = {k: v[-1] for k, v in params.items()}  # 重复参数取最后一个
    ref.params = flat
    ref.xsec_token = flat.get("xsec_token", "")
    ref.url = build_page_url(ref.note_id, flat)
    return ref


def merge_token(ref: NoteRef, resolved_url: str) -> NoteRef:
    """短链解析出真实地址后，把参数并回 NoteRef。"""
    clean, params = split_params(resolved_url)
    flat = {k: v[-1] for k, v in params.items()}
    if not ref.note_id or ref.note_id != parse_note_id(resolved_url):
        ref.note_id = parse_note_id(resolved_url)
    ref.params = {**flat, **ref.params}      # 用户原始链接里的参数优先
    ref.xsec_token = ref.params.get("xsec_token", ref.xsec_token)
    ref.url = build_page_url(ref.note_id, ref.params)
    return ref
