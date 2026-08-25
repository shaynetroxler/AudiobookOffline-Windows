from __future__ import annotations

import io
import os
from pathlib import Path

import requests
from PIL import Image

CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AudiobookOffline" / "cache" / "covers"


def _cache_path(item_id: str, width: int) -> Path:
    return CACHE_ROOT / f"{item_id}_{width}.png"


def fetch(client, item_id: str, width: int = 80) -> Path | None:
    """Return a local file path for this item's cover, downloading and
    caching it on disk first if needed. Safe to call from any thread."""
    path = _cache_path(item_id, width)
    if path.exists():
        return path
    response = requests.get(client.cover_url(item_id, width=width), timeout=10)
    if not response.ok:
        return None
    try:
        image = Image.open(io.BytesIO(response.content))
        image.load()
    except Exception:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "PNG")
    return path
