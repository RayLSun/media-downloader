"""媒体下载：流式写盘、进度显示、多候选回退、失败重试。"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import requests

from .fetch import ClientConfig, FetchError
from .parser import MediaItem, Note

def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _progress(current: int, total: int, width: int = 28) -> None:
    if total <= 0:
        sys.stdout.write(f"\r  已下载 {human_size(current)}")
        sys.stdout.flush()
        return
    pct = min(current * 100 // total, 100)
    bar = "█" * (pct * width // 100) + "░" * (width - pct * width // 100)
    speed = current / max(time.time() - _PROGRESS_T0, 0.001)
    sys.stdout.write(f"\r  {bar} {pct:3d}%  {human_size(current)}/{human_size(total)}  {human_size(speed)}/s")
    sys.stdout.flush()


_PROGRESS_T0 = 0.0


def download_url(session: requests.Session, item: MediaItem, dest: Path, cfg: ClientConfig,
                 quiet: bool = False) -> Path:
    """把一个媒体 URL 下载到 dest。失败重试，5xx/超时换下一个候选由调用方处理。"""
    global _PROGRESS_T0
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for attempt in range(1, cfg.retries + 1):
        try:
            _PROGRESS_T0 = time.time()
            with session.get(
                item.url, stream=True, timeout=cfg.timeout,
                headers={"Referer": "https://www.xiaohongshu.com/"},
            ) as r:
                if r.status_code != 200:
                    raise FetchError(f"HTTP {r.status_code}")
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if not quiet and total:
                                _progress(done, total)
            if not quiet:
                _progress(total or done, total)
                sys.stdout.write("\n")
            return dest
        except requests.exceptions.RequestException as exc:
            # 超时/连接/协议/重定向等所有 requests 层错误统一转 FetchError
            last_exc = exc
            if dest.exists():
                dest.unlink(missing_ok=True)
            if attempt < cfg.retries:
                time.sleep(min(2 ** attempt, 8))
        except FetchError as exc:
            last_exc = exc
            if dest.exists():
                dest.unlink(missing_ok=True)
            if attempt < cfg.retries:
                time.sleep(min(2 ** attempt, 8))
    raise FetchError(f"下载失败（重试 {cfg.retries} 次）：{item.url} —— {last_exc}")


def download_note_media(session: requests.Session, note: Note, outdir: Path, cfg: ClientConfig,
                        *, skip_video: bool = False, skip_images: bool = False,
                        quiet: bool = False) -> list[Path]:
    """按候选顺序下载笔记媒体，返回成功落盘的文件列表。

    每类媒体有多个候选 URL（无水印直链 → h264 → h265 …），第一个成功即止。
    """
    base = outdir / _note_dirname(note)
    saved: list[Path] = []
    errors: list[str] = []

    videos = [m for m in note.media if m.kind == "video"] if not skip_video else []
    images = [m for m in note.media if m.kind == "image"] if not skip_images else []

    if videos:
        dest = base / f"{note.safe_title}.mp4"
        for cand in videos:
            real_dest = dest if cand.ext == "mp4" else dest.with_suffix(f".{cand.ext}")
            try:
                if not quiet:
                    print(f"  ↓ 视频（{cand.note}）→ {real_dest.name}")
                download_url(session, cand, real_dest, cfg, quiet=quiet)
                if real_dest.stat().st_size < 10 * 1024:
                    raise FetchError(f"文件只有 {real_dest.stat().st_size} 字节，像是风控占位页")
                saved.append(real_dest)
                break
            except FetchError as exc:
                errors.append(f"{cand.note}: {exc}")
                continue
        if not saved and videos:
            raise FetchError("所有视频候选都失败了：\n    " + "\n    ".join(errors))

    for i, img in enumerate(images, start=1):
        dest = base / f"{note.safe_title}_{i:02d}.{img.ext}"
        try:
            download_url(session, img, dest, cfg, quiet=quiet)
            saved.append(dest)
        except FetchError as exc:
            # 原图（去后缀）失败 → 退回带规格的原始 URL
            fallback = MediaItem(url=img.url, kind="image", ext=img.ext)
            try:
                download_url(session, fallback, dest, cfg, quiet=quiet)
                saved.append(dest)
            except FetchError:
                errors.append(f"{img.note}: {exc}")
                print(f"  ✗ {img.note} 下载失败：{exc}", file=sys.stderr)

    return saved


def _note_dirname(note: Note) -> str:
    return f"{note.safe_title}_{note.note_id[:8]}"


def check_ffmpeg() -> str | None:
    """检测 ffmpeg 是否可用（合并音视频流用；目前下载的都是已混流的 mp4，可选）。"""
    return shutil.which("ffmpeg")
