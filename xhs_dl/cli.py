"""CLI 入口。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import __version__
from .download import check_ffmpeg, download_note_media, human_size
from .fetch import ClientConfig, FetchError, build_session, get, resolve_short_link
from .parser import ParseError, parse_note_page
from .url import LinkError, parse_link, merge_token


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xhs_dl",
        description="小红书笔记下载器：视频 / 图文 / 文章。独立实现，不依赖任何第三方解析站。",
        epilog=(
            "Cookie 获取：浏览器登录 xiaohongshu.com → F12 → Application/网络 → 任一请求的 "
            "Cookie 头整串复制（至少含 web_session 和 a1）。只下载你有权访问的公开内容，"
            "尊重创作者版权，勿用于商业或批量抓取。"
        ),
    )
    p.add_argument("link", nargs="?", help="笔记链接 / 短链 / 含链接的分享文案 / 24位笔记ID")
    p.add_argument("-o", "--outdir", default="downloads", help="输出根目录（默认 ./downloads）")
    p.add_argument("--cookie", default=os.environ.get("XHS_COOKIE", ""),
                   help="浏览器 Cookie 整串；也可用环境变量 XHS_COOKIE")
    p.add_argument("--cookie-file", help="从文件读 Cookie（首行）")
    p.add_argument("--proxy", default="", help="HTTP 代理，如 http://127.0.0.1:7890（默认直连不走系统代理）")
    p.add_argument("--no-video", action="store_true", help="不下载视频")
    p.add_argument("--no-images", action="store_true", help="不下载图片")
    p.add_argument("--info-only", action="store_true", help="只输出元数据 JSON，不下载媒体")
    p.add_argument("--no-article", action="store_true", help="不生成文章 markdown")
    p.add_argument("--quiet", "-q", action="store_true", help="少打印进度")
    p.add_argument("--mobile", action="store_true", help="使用移动端 UA")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def resolve_cookie(args) -> str:
    if args.cookie_file:
        first = Path(args.cookie_file).read_text(encoding="utf-8").strip().splitlines()
        return first[0].strip() if first else ""
    return (args.cookie or "").strip()


def run(args) -> int:
    if not args.link:
        print("缺少链接。例：python xhs_dl.py \"3.14 复制打开抖音... https://v.douyin... \" ｜ "
              "详见 --help", file=sys.stderr)
        return 2

    cfg = ClientConfig(cookie=resolve_cookie(args), proxy=args.proxy, mobile_ua=args.mobile)
    session = build_session(cfg)

    # 1. 链接归一化（短链在这里联网解析）
    try:
        ref = parse_link(args.link)
        if ref.was_short_link or not ref.url:
            print(f"  解析短链 {ref.original_url} ...")
            real = resolve_short_link(session, ref.original_url, cfg)
            ref = merge_token(ref, real)
        print(f"  笔记 ID：{ref.note_id}")
        if not ref.xsec_token:
            print("  ⚠ 链接里没有 xsec_token —— 2026 年起多数笔记页需要它；"
                  "建议用 App「复制链接」拿到的完整分享文案")
    except LinkError as exc:
        print(f"链接不合法：{exc}", file=sys.stderr)
        return 2

    # 2. 抓笔记页
    page_url = ref.url or f"https://www.xiaohongshu.com/explore/{ref.note_id}"
    print(f"  请求 {page_url[:90]}{'...' if len(page_url) > 90 else ''}")
    try:
        resp = get(session, page_url, cfg, label="笔记页")
    except FetchError as exc:
        print(f"抓取失败：{exc}", file=sys.stderr)
        return 1
    html = resp.text
    if len(html) < 2000 and "验证" in html:
        print("返回的是验证码页。建议：浏览器打开链接完成验证后再试，或提供有效 Cookie", file=sys.stderr)
        return 1

    # 3. 解析
    try:
        note = parse_note_page(html, ref.note_id)
    except ParseError as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1

    # 4. 概要
    print()
    print(f"  标题   : {note.title or '(无标题)'}")
    print(f"  作者   : {note.nickname or '(未知)'}  类型: {note.type}  来源: {note.source}")
    print(f"  互动   : 赞 {note.likes or '-'} 藏 {note.collects or '-'} 评 {note.comments or '-'}")
    if note.time_ms:
        t = dt.datetime.fromtimestamp(note.time_ms / 1000)
        print(f"  发布   : {t:%Y-%m-%d %H:%M}  IP: {note.ip_location or '-'}")
    print(f"  正文   : {len(note.desc)} 字  标签: {len(note.tags)}")
    for m in note.media:
        print(f"  媒体   : [{m.kind}] {m.note}  {m.url[:88]}{'...' if len(m.url) > 88 else ''}")
    print()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base_dir = outdir / f"{note.safe_title}_{note.note_id[:8]}"
    base_dir.mkdir(parents=True, exist_ok=True)

    # 5. 元数据
    info = {
        "note_id": note.note_id,
        "url": page_url,
        "type": note.type,
        "title": note.title,
        "desc": note.desc,
        "author": {"nickname": note.nickname, "userId": note.user_id},
        "interact": {"likes": note.likes, "collects": note.collects,
                     "comments": note.comments, "shares": note.shares},
        "time": note.time_ms,
        "time_iso": (dt.datetime.fromtimestamp(note.time_ms / 1000).isoformat()
                     if note.time_ms else ""),
        "ip_location": note.ip_location,
        "tags": note.tags,
        "parser": note.source,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "ffmpeg": check_ffmpeg() or None,
    }
    info_path = base_dir / "info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 元数据 → {info_path}")

    # 6. 文章 markdown
    if not args.no_article and (note.title or note.desc):
        md_path = base_dir / f"{note.safe_title}.md"
        md_path.write_text(note.article_markdown(), encoding="utf-8")
        print(f"  ✓ 文章 → {md_path}")

    # 7. 媒体
    if args.info_only:
        print("  --info-only：跳过媒体下载")
        return 0
    try:
        saved = download_note_media(
            session, note, outdir, cfg,
            skip_video=args.no_video, skip_images=args.no_images, quiet=args.quiet,
        )
    except FetchError as exc:
        print(str(exc), file=sys.stderr)
        saved = []
    for p in saved:
        size = p.stat().st_size
        print(f"  ✓ {p.relative_to(outdir)}  ({human_size(size)})")
    if not saved:
        print("  （没有媒体落盘）")
    else:
        total = sum(p.stat().st_size for p in saved)
        print(f"\n完成：{len(saved)} 个文件，共 {human_size(total)} → {base_dir}")
    return 0 if saved or args.info_only or args.no_video else 1


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
