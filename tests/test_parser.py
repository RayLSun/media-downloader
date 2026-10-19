"""单元测试：解析器与链接处理。跑法：python -m pytest tests/ 或 python -m unittest discover tests"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from xhs_dl.parser import (
    ParseError, extract_initial_state, parse_note_page, _original_image_url, _video_media,
)
from xhs_dl.url import LinkError, build_page_url, merge_token, parse_link, parse_note_id


# ---------------------------------------------------------------------------
# 链接解析
# ---------------------------------------------------------------------------

def test_parse_link_explore_with_token():
    ref = parse_link("https://www.xiaohongshu.com/explore/656700d1000000002a01b3e9?xsec_token=ABTb4LzOxWwxUhJLBvQtbVxNQXcEEUtGjJ2hS-BIxVC-c=&xsec_source=pc_search")
    assert ref.note_id == "656700d1000000002a01b3e9"
    assert ref.xsec_token == "ABTb4LzOxWwxUhJLBvQtbVxNQXcEEUtGjJ2hS-BIxVC-c="
    assert ref.was_short_link is False
    assert "xsec_token=ABTb4LzOxWwxUhJLBvQtbVxNQXcEEUtGjJ2hS-BIxVC-c=" in ref.url


def test_parse_link_from_share_text():
    text = '67 惊喜生日礼物 https://www.xiaohongshu.com/explore/65f3c16b000000001203ab65?xsec_token=ABC123= 快来看'
    ref = parse_link(text)
    assert ref.note_id == "65f3c16b000000001203ab65"
    assert ref.xsec_token == "ABC123="


def test_parse_link_discovery_item():
    ref = parse_link("https://www.xiaohongshu.com/discovery/item/65f3c16b000000001203ab65?source=xcx")
    assert ref.note_id == "65f3c16b000000001203ab65"


def test_parse_link_short_link_flag():
    ref = parse_link("http://xhslink.com/a1B2cD")
    assert ref.was_short_link is True
    assert ref.url == ""


def test_parse_link_bare_note_id():
    ref = parse_link("65f3c16b000000001203ab65")
    assert ref.note_id == "65f3c16b000000001203ab65"


def test_parse_link_rejects_non_xhs():
    with pytest.raises(LinkError):
        parse_link("https://example.com/explore/65f3c16b000000001203ab65")
    with pytest.raises(LinkError):
        parse_link("随便一段话没有链接")


def test_merge_token_short_link_resolution():
    ref = parse_link("http://xhslink.com/a1B2cD")
    resolved = merge_token(
        ref,
        "https://www.xiaohongshu.com/explore/65f3c16b000000001203ab65?xsec_token=XYZ=&xsec_source=pc_user",
    )
    assert resolved.note_id == "65f3c16b000000001203ab65"
    assert resolved.xsec_token == "XYZ="
    assert "xsec_token=XYZ=" in resolved.url


def test_build_page_url_stable():
    url = build_page_url("65f3c16b000000001203ab65", {"xsec_token": "t", "xsec_source": "pc_user"})
    assert url == ("https://www.xiaohongshu.com/explore/65f3c16b000000001203ab65"
                   "?xsec_token=t&xsec_source=pc_user")


# ---------------------------------------------------------------------------
# __INITIAL_STATE__ 解析
# ---------------------------------------------------------------------------

def make_note(note_id="65f3c16b000000001203ab65", **overrides):
    note = {
        "type": "video",
        "title": "测试视频笔记",
        "desc": "这是描述 #测试 #下载",
        "user": {"nickname": "小张", "userId": "u123"},
        "interactInfo": {"likedCount": "1.2万", "collectedCount": "3000",
                         "commentCount": "45", "shareCount": "10"},
        "ipLocation": "广东",
        "time": 1718000000000,
        "tagList": [{"id": "1", "name": "测试"}, {"id": "2", "name": "下载"}],
        "imageList": [
            {"urlDefault": "https://sns-webpic-qc.xhscdn.com/2026/abc!nd_dft_weblte_2",
             "url": "https://sns-webpic-qc.xhscdn.com/2026/abc!nd_dft_weblte_2",
             "width": 1080, "height": 1440},
        ],
        "video": {
            "consumer": {"originVideoKey": "1000g00831abc/def-mp4"},
            "media": {"stream": {
                "h264": [{"masterUrl": "https://sns-video-hw.xhscdn.com/stream/110/259/x_259.mp4",
                          "width": 1080, "height": 1920}],
                "h265": [{"masterUrl": "https://sns-video-hw.xhscdn.com/stream/110/260/x_260.mp4"}],
                "av1": [],
            }},
        },
    }
    note.update(overrides)
    state = {"note": {"noteDetailMap": {note_id: {"note": note}}}}
    html = f"<html><script>window.__INITIAL_STATE__={json.dumps(state)}</script></html>"
    return html, note


def test_extract_initial_state_replaces_undefined():
    html = '<script>window.__INITIAL_STATE__={"a":undefined,"b":{"c":undefined}};</script>'
    state = extract_initial_state(html)
    assert state == {"a": None, "b": {"c": None}}


def test_extract_initial_state_missing():
    with pytest.raises(ParseError):
        extract_initial_state("<html>验证码页</html>")


def test_parse_video_note_full():
    html, note = make_note()
    n = parse_note_page(html, "65f3c16b000000001203ab65")
    assert n.is_video and n.type == "video"
    assert n.title == "测试视频笔记"
    assert n.nickname == "小张"
    assert n.likes == "1.2万"
    assert n.ip_location == "广东"
    assert n.tags == ["测试", "下载"]
    assert n.source == "initial_state"
    # 视频候选：无水印直链优先，其次 h264/h265
    videos = [m for m in n.media if m.kind == "video"]
    assert videos[0].url == "https://sns-video-bd.xhscdn.com/1000g00831abc/def-mp4"
    assert videos[0].note.startswith("无水印")
    assert any("h264" in m.note for m in videos)
    assert any("h265" in m.note for m in videos)


def test_parse_image_note():
    html, _ = make_note(type="normal", video=None)
    n = parse_note_page(html, "65f3c16b000000001203ab65")
    assert not n.is_video
    assert len(n.media) == 1
    img = n.media[0]
    assert img.kind == "image"
    # 原图：!nd_ 后缀被去掉
    assert "!nd_" not in img.url
    assert img.url == "https://sns-webpic-qc.xhscdn.com/2026/abc"


def test_original_image_url_no_bang_untouched():
    url = "https://sns-webpic-qc.xhscdn.com/2026/plain.jpg"
    assert _original_image_url(url) == url


def test_article_markdown_contains_all():
    html, _ = make_note()
    n = parse_note_page(html, "65f3c16b000000001203ab65")
    md = n.article_markdown()
    assert "# 测试视频笔记" in md
    assert "作者：小张" in md
    assert "IP：广东" in md
    assert "这是描述" in md
    assert "#测试 #下载" in md


def test_parse_falls_back_to_og_meta():
    # 无 __INITIAL_STATE__，但有 og 标签
    html = """
    <html><head>
    <meta name="og:title" content="OG 兜底笔记 - 小红书">
    <meta name="description" content="OG 描述文本">
    <meta name="og:image" content="https://sns-webpic-qc.xhscdn.com/2026/og1!nd_dft_1">
    <meta name="og:video" content="https://sns-video-hw.xhscdn.com/stream/110/259/x.mp4">
    </head><body></body></html>
    """
    n = parse_note_page(html, "65f3c16b000000001203ab65")
    assert n.source == "og_meta"
    assert n.title == "OG 兜底笔记"
    assert n.is_video
    assert n.media[0].kind == "video"
    assert any(m.kind == "image" for m in n.media)


def test_parse_note_deleted_raises_then_og_fails():
    state = {"note": {"noteDetailMap": {"65f3c16b000000001203ab65": {"note": {}}}}}
    html = f"<html><script>window.__INITIAL_STATE__={json.dumps(state)}</script></html>"
    with pytest.raises(ParseError):
        parse_note_page(html, "65f3c16b000000001203ab65")


def test_video_media_empty_stream_still_has_origin_key():
    note = {"video": {"consumer": {"originVideoKey": "key1"}, "media": {"stream": {}}}}
    media = _video_media(note)
    assert [m.url for m in media] == ["https://sns-video-bd.xhscdn.com/key1"]


def test_norm_url_protocol_relative():
    from xhs_dl.parser import _norm_url
    assert _norm_url("//cdn.x.com/a.png") == "https://cdn.x.com/a.png"
    assert _norm_url("https://cdn.x.com/a.png") == "https://cdn.x.com/a.png"
