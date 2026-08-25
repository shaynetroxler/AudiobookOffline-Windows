from __future__ import annotations

from urllib.parse import urljoin

import requests

from .models import BookGroup, Library, LibraryItem, LibraryItemDetail, LibraryStats, MediaProgress


class ABSError(Exception):
    pass


class ABSClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token

    @staticmethod
    def login(server_url: str, username: str, password: str) -> tuple["ABSClient", str]:
        url = server_url.rstrip("/") + "/"
        response = requests.post(
            urljoin(url, "login"),
            json={"username": username, "password": password},
            timeout=15,
        )
        if not response.ok:
            raise ABSError(f"Server responded with status {response.status_code}")
        data = response.json()
        token = data["user"]["token"]
        return ABSClient(url, token), token

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = requests.get(
            urljoin(self.base_url, path),
            headers={"Authorization": f"Bearer {self.token}"},
            params=params or {},
            timeout=15,
        )
        if not response.ok:
            raise ABSError(f"Server responded with status {response.status_code}")
        return response.json()

    def _patch(self, path: str, json_body: dict) -> None:
        response = requests.patch(
            urljoin(self.base_url, path),
            headers={"Authorization": f"Bearer {self.token}"},
            json=json_body,
            timeout=15,
        )
        if not response.ok:
            raise ABSError(f"Server responded with status {response.status_code}")

    def libraries(self) -> list[Library]:
        data = self._get("api/libraries")
        return [Library.from_json(lib) for lib in data["libraries"]]

    def items(self, library_id: str, page: int = 0, limit: int = 100_000) -> list[LibraryItem]:
        data = self._get(
            f"api/libraries/{library_id}/items",
            params={"limit": limit, "page": page, "sort": "media.metadata.title"},
        )
        return [LibraryItem.from_json(item) for item in data["results"]]

    def continue_listening(self, library_id: str) -> list[LibraryItem]:
        data = self._get(f"api/libraries/{library_id}/personalized")
        for shelf in data:
            if shelf.get("id") == "continue-listening":
                return [LibraryItem.from_json(entity) for entity in shelf.get("entities", [])]
        return []

    def search(self, library_id: str, query: str, limit: int = 25) -> list[LibraryItem]:
        data = self._get(f"api/libraries/{library_id}/search", params={"q": query, "limit": limit})
        return [LibraryItem.from_json(entry["libraryItem"]) for entry in data.get("book", [])]

    def series(self, library_id: str) -> list[BookGroup]:
        data = self._get(f"api/libraries/{library_id}/series", params={"limit": 1000})
        return [BookGroup.from_json(s) for s in data.get("results", [])]

    def collections(self, library_id: str) -> list[BookGroup]:
        data = self._get(f"api/libraries/{library_id}/collections", params={"limit": 1000})
        return [BookGroup.from_json(c) for c in data.get("results", [])]

    def library_stats(self, library_id: str) -> LibraryStats:
        return LibraryStats.from_json(self._get(f"api/libraries/{library_id}/stats"))

    def item_detail(self, item_id: str) -> LibraryItemDetail:
        data = self._get(f"api/items/{item_id}", params={"expanded": 1})
        return LibraryItemDetail.from_json(data)

    def cover_url(self, item_id: str, width: int | None = None) -> str:
        url = urljoin(self.base_url, f"api/items/{item_id}/cover") + f"?token={self.token}"
        if width is not None:
            url += f"&width={width}"
        return url

    def stream_url(self, content_path: str) -> str:
        path = content_path.lstrip("/")
        return urljoin(self.base_url, path) + f"?token={self.token}"

    def media_progress(self) -> dict[str, MediaProgress]:
        data = self._get("api/me")
        return {p["libraryItemId"]: MediaProgress.from_json(p) for p in data.get("mediaProgress", [])}

    def update_progress(self, item_id: str, current_time: float, duration: float, is_finished: bool = False) -> None:
        self._patch(
            f"api/me/progress/{item_id}",
            {"currentTime": current_time, "duration": duration, "isFinished": is_finished},
        )

    def hide_from_continue_listening(self, item_id: str) -> None:
        self._patch(f"api/me/progress/{item_id}", {"hideFromContinueListening": True})
