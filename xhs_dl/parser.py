"""页面解析：window.__INITIAL_STATE__ 主路径 + og:meta 兜底。

__INITIAL_STATE__ 里的关键路径（2026 实测结构）：
  state.note.noteDetailMap[<note_id>].note
    ├─ type                "video" | "normal"
    ├─ title / desc        标题与正文（长文类笔记正文在 desc）
    ├─ user               {nickname, userId, avatar}
    ├─ interactInfo       {likedCount, collectedCount, commentCount, shareCount}
    ├─ imageList          [{urlDefault, url, width, height, livePhoto}]
    ├─ tagList            [{id, name, type}]
    ├─ video.consumer.originVideoKey          ← 无水印直链的关键
    └─ video.media.stream {h264:[{masterUrl,...}], h265:[...], av1:[...]}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urlsplit

INITIAL_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL
)


class ParseError(RuntimeError):
    """页面拿到了但解析不出笔记数据。"""


@dataclass
class MediaItem:
    url: str
    kind: str = "image"           # image | video
    ext: str = ""
    width: int = 0
    height: int = 0
    note: str = ""                # 备注（如"无水印直链"/"降级：带水印流"）


@dataclass
class Note:
    note_id: str = ""
    type: str = "normal"          # video | normal
    title: str = ""
    desc: str = ""
    nickname: str = ""
    user_id: str = ""
    likes: str = ""
    collects: str = ""
    comments: str = ""
    shares: str = ""
    ip_location: str = ""
    time_ms: int = 0
    tags: list[str] = field(default_factory=list)
    media: list[MediaItem] = field(default_factory=list)
    source: str = ""              # initial_state | og_meta
    raw: dict = field(default_factory=dict)

    @property
    def safe_title(self) -> str:
        t = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", self.title or self.desc or self.note_id).strip()
        return (t[:60] or self.note_id)

    @property
    def is_video(self) -> bool:
        return self.type == "video"

    def article_markdown(self) -> str:
        parts = [f"# {self.title}\n"]
        if self.nickname:
            meta = [f"作者：{self.nickname}"]
            if self.ip_location:
                meta.append(f"IP：{self.ip_location}")
            parts.append("> " + " ｜ ".join(meta) + "\n")
        parts.append(self.desc.strip())
        if self.tags:
            parts.append("\n" + " ".join(f"#{t}" for t in self.tags))
        return "\n".join(p for p in parts if p.strip()) + "\n"


# ---------------------------------------------------------------------------
# __INITIAL_STATE__ 提取
# ---------------------------------------------------------------------------

def extract_initial_state(html: str) -> dict:
    """从页面里挖出 __INITIAL_STATE__ 并还原成 dict。

    小红书的序列化产物里混着 JS 字面量 ``undefined``，直接 json.loads 会炸，
    统一替换成 null。
    """
    m = INITIAL_STATE_RE.search(html)
    if not m:
        raise ParseError("页面里没有找到 window.__INITIAL_STATE__（可能被风控页替换，或需要登录态）")
    blob = m.group(1)
    blob = re.sub(r"\bundefined\b", "null", blob)
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise ParseError(f"__INITIAL_STATE__ 不是合法 JSON：{exc}") from exc


def _first_note_detail(state: dict, note_id: str) -> dict:
    note_root = (state.get("note") or {})
    detail_map = note_root.get("noteDetailMap") or {}
    if not detail_map:
        raise ParseError("__INITIAL_STATE__ 里没有 noteDetailMap（页面可能被风控替换）")
    entry = detail_map.get(note_id) or detail_map.get(note_id.upper())
    if not entry and len(detail_map) == 1:
        entry = next(iter(detail_map.values()))
    if not entry:
        raise ParseError(f"noteDetailMap 里没有 {note_id}：笔记可能已删除、仅自己可见，或 token 失效")
    note = entry.get("note") or {}
    if not note:
        # 删除/仅自己可见的笔记会有一个只有 noteCard 占位的 entry
        raise ParseError("笔记数据为空：可能已删除、仅自己可见，或 xsec_token 失效")
    return note


def _norm_url(url: str) -> str:
    """协议相对地址（//cdn.x.com/a.png）补 https:。"""
    u = (url or "").strip()
    return "https:" + u if u.startswith("//") else u


def _video_media(note: dict) -> list[MediaItem]:
    media: list[MediaItem] = []
    video = note.get("video") or {}
    consumer = video.get("consumer") or {}
    origin_key = consumer.get("originVideoKey") or ""
    if origin_key:
        media.append(MediaItem(
            url=f"https://sns-video-bd.xhscdn.com/{origin_key}",
            kind="video", ext="mp4", note="无水印直链(originVideoKey)",
        ))
    stream = (video.get("media") or {}).get("stream") or {}
    for codec in ("h264", "h265", "av1"):
        for item in stream.get(codec) or []:
            url = item.get("masterUrl") or ""
            if not url:
                continue
            ext = "mp4" if codec == "h264" else ("hevc" if codec == "h265" else "av1")
            note_txt = f"降级：{codec} 站点转码流" if origin_key else f"降级：{codec} 流"
            media.append(MediaItem(
                url=_norm_url(url), kind="video", ext=ext,
                width=int(item.get("height") or 0) or int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                note=note_txt,
            ))
    return media


def _image_media(note: dict) -> list[MediaItem]:
    out: list[MediaItem] = []
    for i, img in enumerate(note.get("imageList") or [], start=1):
        url = img.get("urlDefault") or img.get("url") or ""
        if not url:
            continue
        out.append(MediaItem(
            url=_norm_url(_original_image_url(url)), kind="image",
            ext=_guess_img_ext(url),
            width=int(img.get("width") or 0), height=int(img.get("height") or 0),
            note=f"第 {i} 张",
        ))
    return out


def _guess_img_ext(url: str) -> str:
    path = urlsplit(url).path.lower()
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        if path.endswith(ext):
            return ext.lstrip(".")
    return "webp"        # 小红书默认 webp


def _original_image_url(url: str) -> str:
    """去掉 !nd_xxx 缩放后缀拿原图；失败时返回原 URL。

    小红书图片 URL 形如 .../1040g0xxx!nd_dft_weblte_2，! 后是裁剪规格。
    """
    bang = url.find("!")
    return url[:bang] if bang > 0 else url


def parse_initial_state(html: str, note_id: str) -> Note:
    state = extract_initial_state(html)
    note = _first_note_detail(state, note_id)
    interact = note.get("interactInfo") or {}
    user = note.get("user") or {}
    n = Note(
        note_id=note_id,
        type=str(note.get("type") or "normal"),
        title=unescape(str(note.get("title") or "")).strip(),
        desc=unescape(str(note.get("desc") or "")).strip(),
        nickname=str(user.get("nickname") or ""),
        user_id=str(user.get("userId") or ""),
        likes=str(interact.get("likedCount") or ""),
        collects=str(interact.get("collectedCount") or ""),
        comments=str(interact.get("commentCount") or ""),
        shares=str(interact.get("shareCount") or ""),
        ip_location=str(note.get("ipLocation") or ""),
        time_ms=int(note.get("time") or 0),
        tags=[str(t.get("name")) for t in (note.get("tagList") or []) if t.get("name")],
        source="initial_state",
        raw=note,
    )
    n.media = _video_media(note) if n.is_video else _image_media(note)
    if n.is_video and not any(m.kind == "video" for m in n.media):
        # 视频笔记但没取到流：把封面图也带上，避免空手而归
        n.media = _image_media(note)
    return n


# ---------------------------------------------------------------------------
# og:meta 兜底（__INITIAL_STATE__ 被风控替换时仍能拿到标题/封面/视频）
# ---------------------------------------------------------------------------

def _meta(html: str, name: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']',
        html, re.IGNORECASE,
    ) or re.search(
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
        html, re.IGNORECASE,
    )
    return unescape(m.group(1)).strip() if m else ""


def parse_og_meta(html: str, note_id: str) -> Note:
    title = _meta(html, "og:title").replace(" - 小红书", "").strip()
    desc = _meta(html, "description").strip()
    images = re.findall(
        r'<meta[^>]+(?:name|property)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ) + re.findall(
        r'<meta[^>]+content=["\'](https?://[^"\']*sns-webpic[^"\']+)["\']',
        html, re.IGNORECASE,
    )
    videos = [_meta(html, "og:video")] if _meta(html, "og:video") else []
    n = Note(
        note_id=note_id,
        type="video" if videos else "normal",
        title=title, desc=desc,
        source="og_meta",
    )
    if videos:
        n.media = [MediaItem(url=_norm_url(v), kind="video", ext="mp4", note="og:video 兜底") for v in videos if v]
    n.media += [
        MediaItem(url=_norm_url(_original_image_url(u)), kind="image", ext=_guess_img_ext(u), note=f"og 兜底 第 {i} 张")
        for i, u in enumerate(dict.fromkeys(images), start=1) if u
    ]
    if not (n.title or n.desc or n.media):
        raise ParseError("og:meta 兜底也拿不到数据：页面大概率是验证码/登录墙")
    return n


def parse_note_page(html: str, note_id: str) -> Note:
    """主路径 __INITIAL_STATE__，失败降级 og:meta。"""
    try:
        return parse_initial_state(html, note_id)
    except ParseError:
        return parse_og_meta(html, note_id)
