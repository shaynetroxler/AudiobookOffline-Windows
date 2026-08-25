from __future__ import annotations

import os
import shutil
from pathlib import Path

import requests

DOWNLOAD_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AudiobookOffline" / "downloads"

_EXTENSIONS = {
    "audio/mp4": "m4b",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
}


def track_path(item_id: str, track_index: int, mime_type: str) -> Path:
    ext = _EXTENSIONS.get(mime_type, "bin")
    return DOWNLOAD_ROOT / item_id / f"{track_index:03d}.{ext}"


def is_fully_downloaded(item_id: str, tracks) -> bool:
    return bool(tracks) and all(track_path(item_id, t.index, t.mime_type).exists() for t in tracks)


def downloaded_size(item_id: str, tracks) -> int:
    total = 0
    for t in tracks:
        path = track_path(item_id, t.index, t.mime_type)
        if path.exists():
            total += path.stat().st_size
    return total


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def download_tracks(client, item_id: str, tracks, on_progress) -> None:
    """Download every track for an item to local storage. `on_progress(done, total)`
    is called after each track completes (including ones already present)."""
    for i, track in enumerate(tracks):
        dest = track_path(item_id, track.index, track.mime_type)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with requests.get(client.stream_url(track.content_url), stream=True, timeout=30) as response:
                response.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            tmp.rename(dest)
        on_progress(i + 1, len(tracks))


def delete_downloads(item_id: str) -> None:
    path = DOWNLOAD_ROOT / item_id
    if path.exists():
        shutil.rmtree(path)
