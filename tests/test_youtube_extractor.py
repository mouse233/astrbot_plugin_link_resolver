"""Tests for the isolated YouTube yt-dlp integration."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from youtube import YoutubeExtractor, YoutubeParseError, extract_youtube_links


class FakeYoutubeDL:
    options: dict = {}

    def __init__(self, options):
        type(self).options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, url, download=False):
        info = {
            "id": "RHXOhUKP5Y0",
            "title": "Demo",
            "uploader": "Example",
            "duration": 12,
            "webpage_url": url,
        }
        if download:
            path = Path(
                self.options["outtmpl"]
                .replace("%(id)s", info["id"])
                .replace("%(ext)s", "mp4")
            )
            path.write_bytes(b"video")
        return info

    def prepare_filename(self, info):
        return (
            self.options["outtmpl"]
            .replace("%(id)s", info["id"])
            .replace("%(ext)s", "mp4")
        )


class TestYoutubeExtractor(unittest.TestCase):
    def test_link_matching_accepts_youtube_variants_and_excludes_other_hosts(self):
        links = extract_youtube_links(
            "https://youtu.be/RHXOhUKP5Y0?t=1 "
            "youtube.com/shorts/abc https://youtube.com.example/video"
        )
        self.assertEqual(
            links,
            [
                "https://youtu.be/RHXOhUKP5Y0?t=1",
                "https://youtube.com/shorts/abc",
            ],
        )

    def test_rejects_non_youtube_link(self):
        with self.assertRaises(YoutubeParseError):
            YoutubeExtractor._validate_url("https://example.com/video")

    def test_download_uses_limit_and_returns_media_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("youtube.extractor._get_yt_dlp_class", return_value=FakeYoutubeDL):
                result, output = asyncio.run(
                    YoutubeExtractor().download(
                        "https://youtu.be/RHXOhUKP5Y0",
                        Path(directory),
                        "unit",
                        max_height=720,
                        max_bytes=1024,
                    )
                )
        self.assertEqual(result.video_id, "RHXOhUKP5Y0")
        self.assertEqual(output.suffix, ".mp4")
        self.assertEqual(FakeYoutubeDL.options["max_filesize"], 1024)
        self.assertIn("format", FakeYoutubeDL.options)


if __name__ == "__main__":
    unittest.main(verbosity=2)
