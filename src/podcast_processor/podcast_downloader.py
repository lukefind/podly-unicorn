from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests
import validators
from flask import abort

from shared.interfaces import Post
from shared.processing_paths import get_in_root

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = str(get_in_root())


class DownloadError(Exception):
    def __init__(
        self, message: str, status_code: Optional[int] = None, url: str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class PodcastDownloader:
    """
    Handles downloading podcast episodes with robust file checking and path management.
    """

    def __init__(
        self, download_dir: str = DOWNLOAD_DIR, logger: Optional[logging.Logger] = None
    ):
        self.download_dir = download_dir
        self.logger = logger or logging.getLogger(__name__)

    def download_episode(self, post: Post, dest_path: str) -> Optional[str]:
        """
        Download a podcast episode if it doesn't already exist.

        Args:
            post: The Post object containing the podcast episode to download

        Returns:
            Path to the downloaded file, or None if download failed
        """
        # Destination is required; ensure parent directory exists
        download_path = dest_path
        Path(download_path).parent.mkdir(parents=True, exist_ok=True)
        if not download_path:
            self.logger.error(f"Invalid download path for post {post.id}")
            return None

        # First, check if the file truly exists and has nonzero size.
        try:
            if os.path.isfile(download_path):
                if os.path.getsize(download_path) > 0:
                    self.logger.info("Episode already downloaded.")
                    return download_path
                self.logger.info("File is zero bytes, re-downloading.")
                os.remove(download_path)

        except FileNotFoundError:
            # Covers both "file actually missing" and "broken symlink"
            pass

        # If we get here, the file is missing or zero bytes -> perform download
        audio_link = post.download_url
        if audio_link is None or not validators.url(audio_link):
            abort(404)
            return None

        self.logger.info(f"Downloading {audio_link} into {download_path}...")
        referer = "https://open.acast.com/" if "acast.com" in audio_link else None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": referer,
        }
        partial_path = f"{download_path}.part"

        def remove_partial() -> None:
            try:
                os.remove(partial_path)
            except FileNotFoundError:
                pass

        for attempt in range(3):
            remove_partial()
            try:
                with requests.get(
                    audio_link,
                    stream=True,
                    timeout=(10, 60),
                    headers=headers,
                ) as response:
                    status_code = response.status_code
                    if status_code != 200:
                        self.logger.info(
                            "Failed to download the podcast episode, response: %s",
                            status_code,
                        )
                        parsed_url = None
                        try:
                            parsed_url = requests.utils.urlparse(audio_link)
                        except Exception:
                            pass

                        host = parsed_url.hostname if parsed_url else None
                        if status_code == 403 and host and "podtrac.com" in host:
                            raise DownloadError(
                                "Download blocked by host (HTTP 403). Podtrac often blocks datacenter IPs. "
                                "Use a proxy/egress IP or a different source.",
                                status_code=status_code,
                                url=audio_link,
                            )

                        error = DownloadError(
                            f"Download failed (HTTP {status_code}).",
                            status_code=status_code,
                            url=audio_link,
                        )
                        if (status_code == 429 or status_code >= 500) and attempt < 2:
                            time.sleep(attempt + 1)
                            continue
                        raise error

                    with open(partial_path, "wb") as file:
                        for chunk in response.iter_content(chunk_size=8192):
                            file.write(chunk)

                os.replace(partial_path, download_path)
                self.logger.info("Download complete.")
                return download_path
            except (requests.Timeout, requests.ConnectionError) as error:
                remove_partial()
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise DownloadError(
                    "Download failed after three attempts due to a transient network error."
                ) from error
            except requests.RequestException as error:
                remove_partial()
                raise DownloadError("Download request failed.") from error
            except Exception:
                remove_partial()
                raise

        raise DownloadError("Download failed after three attempts.")

    def get_and_make_download_path(self, post_title: str) -> Path:
        """
        Generate the download path for a post and create necessary directories.

        Args:
            post_title: The title of the post to generate a path for

        Returns:
            Path object for the download location
        """
        sanitized_title = sanitize_title(post_title)

        post_directory = sanitized_title
        post_filename = sanitized_title + ".mp3"

        post_directory_path = Path(self.download_dir) / post_directory

        post_directory_path.mkdir(parents=True, exist_ok=True)

        return post_directory_path / post_filename


def sanitize_title(title: str) -> str:
    """Sanitize a title for use in file paths."""
    return re.sub(r"[^a-zA-Z0-9\s]", "", title)


def find_audio_link(entry: Any) -> str:
    """Find the audio link in a feed entry."""
    # Check for common audio types in order of preference
    audio_types = [
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/x-m4a",
        "audio/mp4",
        "audio/aac",
        "audio/wav",
        "audio/flac",
    ]

    # First pass: look for exact audio type matches
    for link in entry.links:
        link_type = getattr(link, "type", "") or ""
        if link_type in audio_types:
            href = link.href
            assert isinstance(href, str)
            return href

    # Second pass: look for any audio/* type
    for link in entry.links:
        link_type = getattr(link, "type", "") or ""
        if link_type.startswith("audio/"):
            href = link.href
            assert isinstance(href, str)
            return href

    # Third pass: look for enclosure with audio file extension
    for link in entry.links:
        href = getattr(link, "href", "") or ""
        if any(
            href.lower().endswith(ext)
            for ext in [".mp3", ".ogg", ".m4a", ".mp4", ".aac", ".wav", ".flac"]
        ):
            assert isinstance(href, str)
            return href

    return str(entry.id)


# Backward compatibility - create a default instance
_default_downloader = PodcastDownloader()


def download_episode(post: Post, dest_path: str) -> Optional[str]:
    return _default_downloader.download_episode(post, dest_path)


def get_and_make_download_path(post_title: str) -> Path:
    return _default_downloader.get_and_make_download_path(post_title)
