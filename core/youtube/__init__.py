"""YouTube link detection and yt-dlp-backed downloading."""

from .extractor import (
    YOUTUBE_MESSAGE_PATTERN,
    YoutubeDownloadError,
    YoutubeExtractor,
    YoutubeParseError,
    YoutubeResult,
    extract_youtube_links,
    is_youtube_403_error,
)

__all__ = [
    "YOUTUBE_MESSAGE_PATTERN",
    "YoutubeDownloadError",
    "YoutubeExtractor",
    "YoutubeParseError",
    "YoutubeResult",
    "extract_youtube_links",
    "is_youtube_403_error",
]
