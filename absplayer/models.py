from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Library:
    id: str
    name: str
    media_type: str

    @staticmethod
    def from_json(data: dict) -> "Library":
        return Library(id=data["id"], name=data["name"], media_type=data["mediaType"])


@dataclass
class BookMetadata:
    title: str
    author_name: str | None
    series_name: str | None

    @staticmethod
    def from_json(data: dict) -> "BookMetadata":
        return BookMetadata(
            title=data["title"],
            author_name=data.get("authorName"),
            series_name=data.get("seriesName"),
        )


@dataclass
class LibraryItem:
    id: str
    library_id: str
    metadata: BookMetadata
    cover_path: str | None
    duration: float | None

    @staticmethod
    def from_json(data: dict) -> "LibraryItem":
        media = data["media"]
        return LibraryItem(
            id=data["id"],
            library_id=data["libraryId"],
            metadata=BookMetadata.from_json(media["metadata"]),
            cover_path=media.get("coverPath"),
            duration=media.get("duration"),
        )


@dataclass
class Track:
    index: int
    duration: float
    content_url: str
    mime_type: str

    @staticmethod
    def from_json(data: dict) -> "Track":
        return Track(
            index=data["index"],
            duration=data["duration"],
            content_url=data["contentUrl"],
            mime_type=data["mimeType"],
        )


@dataclass
class MediaProgress:
    library_item_id: str
    current_time: float
    duration: float
    is_finished: bool

    @staticmethod
    def from_json(data: dict) -> "MediaProgress":
        return MediaProgress(
            library_item_id=data["libraryItemId"],
            current_time=data.get("currentTime", 0.0),
            duration=data.get("duration", 0.0),
            is_finished=data.get("isFinished", False),
        )


@dataclass
class BookGroup:
    id: str
    name: str
    books: list[LibraryItem]

    @staticmethod
    def from_json(data: dict) -> "BookGroup":
        return BookGroup(
            id=data["id"],
            name=data["name"],
            books=[LibraryItem.from_json(b) for b in data.get("books", [])],
        )


@dataclass
class AuthorCount:
    name: str
    count: int


@dataclass
class GenreCount:
    genre: str
    count: int


@dataclass
class SizedItem:
    id: str
    title: str
    value: float


@dataclass
class LibraryStats:
    total_items: int
    total_authors: int
    total_genres: int
    total_size: int
    total_duration: float
    num_tracks: int
    top_authors: list[AuthorCount]
    top_genres: list[GenreCount]
    largest_items: list[SizedItem]
    longest_items: list[SizedItem]

    @staticmethod
    def from_json(data: dict) -> "LibraryStats":
        return LibraryStats(
            total_items=data.get("totalItems", 0),
            total_authors=data.get("totalAuthors", 0),
            total_genres=data.get("totalGenres", 0),
            total_size=data.get("totalSize", 0),
            total_duration=data.get("totalDuration", 0.0),
            num_tracks=data.get("numAudioTracks", 0),
            top_authors=[AuthorCount(a["name"], a["count"]) for a in data.get("authorsWithCount", [])],
            top_genres=[GenreCount(g["genre"], g["count"]) for g in data.get("genresWithCount", [])],
            largest_items=[SizedItem(i["id"], i["title"], i["size"]) for i in data.get("largestItems", [])],
            longest_items=[SizedItem(i["id"], i["title"], i["duration"]) for i in data.get("longestItems", [])],
        )


@dataclass
class Chapter:
    start: float
    end: float
    title: str

    @staticmethod
    def from_json(data: dict) -> "Chapter":
        return Chapter(start=data["start"], end=data["end"], title=data["title"])


@dataclass
class LibraryItemDetail:
    id: str
    library_id: str
    metadata: BookMetadata
    cover_path: str | None
    tracks: list[Track]
    chapters: list[Chapter]

    @staticmethod
    def from_json(data: dict) -> "LibraryItemDetail":
        media = data["media"]
        tracks = [Track.from_json(t) for t in media["tracks"]]
        chapters = [Chapter.from_json(c) for c in media.get("chapters", [])]
        if not chapters:
            chapters = [Chapter(start=0.0, end=sum(t.duration for t in tracks), title=media["metadata"]["title"])]
        return LibraryItemDetail(
            id=data["id"],
            library_id=data["libraryId"],
            metadata=BookMetadata.from_json(media["metadata"]),
            cover_path=media.get("coverPath"),
            tracks=tracks,
            chapters=chapters,
        )
