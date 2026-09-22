"""YouTube-only metadata extraction and video downloads via yt-dlp."""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

YOUTUBE_REQUEST_TIMEOUT_SEC = 60.0
YOUTUBE_URL_PATTERN = r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)(?=$|[/?#])(?:/[^\s'\"<>]*)?"
YOUTUBE_MESSAGE_PATTERN = rf"(?s).*(?:{YOUTUBE_URL_PATTERN})"
_YOUTUBE_RE = re.compile(YOUTUBE_URL_PATTERN, re.IGNORECASE)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class YoutubeParseError(RuntimeError):
    """The supplied URL is not a supported YouTube URL."""


class YoutubeDownloadError(RuntimeError):
    """yt-dlp could not inspect or download the video."""


@dataclass(slots=True)
class YoutubeResult:
    video_id: str
    title: str | None
    uploader: str | None
    duration: int | None
    source_url: str
    thumbnail_url: str | None = None
    filesize: int | None = None


def _normalize_url(raw: str) -> str:
    url = (raw or "").strip().rstrip(")],.!?;，。！？")
    if not url:
        return url
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def _is_youtube_url(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() in _YOUTUBE_HOSTS
    except ValueError:
        return False


def extract_youtube_links(text: str) -> list[str]:
    """Return distinct YouTube links in message order."""
    links: list[str] = []
    for match in _YOUTUBE_RE.finditer(text or ""):
        url = _normalize_url(match.group(0))
        if _is_youtube_url(url) and url not in links:
            links.append(url)
    return links


def _get_yt_dlp_class():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise YoutubeDownloadError("缺少 yt-dlp 依赖，请重载插件以安装 requirements.txt") from exc
    return YoutubeDL


class YoutubeExtractor:
    def __init__(self, timeout: float = YOUTUBE_REQUEST_TIMEOUT_SEC):
        self.timeout = timeout

    @staticmethod
    def _validate_url(url: str) -> str:
        normalized = _normalize_url(url)
        if not _is_youtube_url(normalized):
            raise YoutubeParseError(f"不是支持的 YouTube 链接: {url}")
        return normalized

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _result_from_info(self, info: dict[str, Any], source_url: str) -> YoutubeResult:
        video_id = str(info.get("id") or "").strip()
        if not video_id:
            raise YoutubeParseError("yt-dlp 未返回视频 ID")
        return YoutubeResult(
            video_id=video_id,
            title=str(info.get("title") or "").strip() or None,
            uploader=str(info.get("uploader") or info.get("channel") or "").strip() or None,
            duration=self._integer(info.get("duration")),
            source_url=str(info.get("webpage_url") or source_url),
            thumbnail_url=str(info.get("thumbnail") or "").strip() or None,
            filesize=self._integer(info.get("filesize") or info.get("filesize_approx")),
        )

    def _base_options(self, cookie_file: str | None) -> dict[str, Any]:
        options: dict[str, Any] = {"noplaylist": True, "quiet": True, "no_warnings": True, "socket_timeout": self.timeout, "http_headers": {"User-Agent": "Mozilla/5.0"}}
        if cookie_file:
            path = Path(cookie_file).expanduser()
            if not path.is_file():
                raise YoutubeDownloadError(f"YouTube Cookie 文件不存在: {path}")
            options["cookiefile"] = str(path)
        return options

    async def inspect(self, url: str, cookie_file: str | None = None) -> YoutubeResult:
        return await asyncio.to_thread(self._inspect_sync, self._validate_url(url), cookie_file)

    def _inspect_sync(self, url: str, cookie_file: str | None) -> YoutubeResult:
        try:
            with _get_yt_dlp_class()({**self._base_options(cookie_file), "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
        except (YoutubeParseError, YoutubeDownloadError):
            raise
        except Exception as exc:
            raise YoutubeDownloadError(f"YouTube 信息获取失败: {exc}") from exc
        if not isinstance(info, dict):
            raise YoutubeParseError("yt-dlp 返回的信息格式异常")
        return self._result_from_info(info, url)

    async def download(self, url: str, output_dir: Path, request_id: str, *, max_height: int = 720, max_bytes: int | None = None, cookie_file: str | None = None) -> tuple[YoutubeResult, Path]:
        return await asyncio.to_thread(self._download_sync, self._validate_url(url), output_dir, request_id, max_height, max_bytes, cookie_file)

    def _download_sync(self, url: str, output_dir: Path, request_id: str, max_height: int, max_bytes: int | None, cookie_file: str | None) -> tuple[YoutubeResult, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Prefer a progressive single-file stream so ffmpeg is not mandatory.
        height = f"[height<={max_height}]" if max_height > 0 else ""
        if shutil.which("ffmpeg"):
            format_selector = f"bv*[ext=mp4]{height}+ba[ext=m4a]/b[ext=mp4]{height}/bv*[ext=mp4]{height}/best{height}"
        else:
            # YouTube commonly exposes DASH-only streams. Without ffmpeg, keep
            # a playable MP4 video rather than failing every such download.
            format_selector = f"bv*[ext=mp4]{height}/best{height}"
        options = {**self._base_options(cookie_file), "format": format_selector, "outtmpl": str(output_dir / f"%(id)s_{request_id}.%(ext)s"), "max_filesize": max_bytes, "overwrites": False}
        try:
            with _get_yt_dlp_class()(options) as ydl:
                info = ydl.extract_info(url, download=True)
                if not isinstance(info, dict):
                    raise YoutubeParseError("yt-dlp 返回的信息格式异常")
                result = self._result_from_info(info, url)
                candidates = [Path(ydl.prepare_filename(info))]
                candidates.extend(Path(str(item["filepath"])) for item in info.get("requested_downloads") or [] if isinstance(item, dict) and item.get("filepath"))
        except (YoutubeParseError, YoutubeDownloadError):
            raise
        except Exception as exc:
            raise YoutubeDownloadError(f"YouTube 下载失败: {exc}") from exc
        output_path = next((path for path in candidates if path.is_file() and path.stat().st_size > 0), None)
        if output_path is None:
            output_path = next((path for path in output_dir.glob(f"{result.video_id}_{request_id}.*") if path.is_file() and not path.name.endswith(".part") and path.stat().st_size > 0), None)
        if output_path is None:
            raise YoutubeDownloadError("yt-dlp 未生成可发送的视频文件")
        if max_bytes is not None and output_path.stat().st_size > max_bytes:
            output_path.unlink(missing_ok=True)
            raise YoutubeDownloadError("下载后的视频超过大小限制")
        return result, output_path
