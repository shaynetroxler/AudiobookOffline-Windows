from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import covers, downloads
from .client import ABSClient, ABSError
from .credentials import ServerCredentials, load as load_creds, save as save_creds
from .media_controls import MediaControls
from .models import LibraryItem

_ICON_PATH = Path(__file__).resolve().parent.parent / "data" / "icon.png"

_HELP_HTML = """
<h2>Audiobook Offline — Help</h2>

<h3>Logging in</h3>
<p>Enter your Audiobookshelf server's URL (e.g. <code>http://192.168.1.10:13378</code>),
your username, and password. Your credentials are saved to Windows Credential
Manager, so you won't need to log in again on this PC.</p>

<h3>Browsing your library</h3>
<p>Use the search box to filter by title or author. The <b>Books / Series /
Collections</b> buttons switch how the list below is grouped — tap a series or
collection to see the books inside it, and use the "← All" row to go back.</p>

<h3>Continue Listening &amp; offline downloads</h3>
<p>Books you're partway through appear in the Continue Listening shelf at the
top. Each row has two icons:</p>
<ul>
<li><b>🔵 Blue button</b> — tap to download that book for offline listening.
Tap it again to remove the downloaded copy and free up space.</li>
<li><b>🟢 Green dot</b> — lights up once every part of the book has finished
downloading. Check for the green dot before you leave your home network if
you want to keep listening without a connection.</li>
</ul>
<p>Tap the ✕ on a Continue Listening row to remove that book from the shelf
(your progress is kept — it just stops showing up here).</p>

<h3>The player screen</h3>
<ul>
<li><b>Seek bar</b> — scoped to the current chapter; drag or click to seek.</li>
<li><b>-30s / +30s</b> — skip backward or forward.</li>
<li><b>⏮ Chapter / Chapter ⏭</b> — jump to the previous or next chapter.</li>
<li><b>Chapter list</b> — tap any chapter to jump straight to it.</li>
<li><b>Speed</b> — 0.75× to 2× playback speed.</li>
<li><b>Sleep</b> — pause automatically after a set number of minutes, or at
the end of the current chapter.</li>
<li><b>Download / Remove Download</b> — same offline download as the Continue
Listening shelf, from inside the book itself.</li>
<li><b>Spacebar</b> — play/pause, from anywhere on this screen.</li>
</ul>
<p>Your listening progress is saved back to the server automatically as you
listen, so picking the book up on another device stays in sync.</p>

<h3>Stats</h3>
<p>The Stats button on the library screen shows totals for your library —
book/author/genre counts, total listening time and size, and your longest
and largest books.</p>
"""

_ABOUT_TEXT = (
    "<h3>Audiobook Offline</h3>"
    "<p>Windows edition</p>"
    "<p>Written by Shayne Troxler, 2026.</p>"
    "<p>A native desktop client for "
    "<a href=\"https://github.com/advplyr/audiobookshelf\">Audiobookshelf</a>, "
    "built for offline listening. Also available for "
    "<a href=\"https://github.com/shaynetroxler/AudiobookOffline\">macOS</a> and "
    "<a href=\"https://github.com/shaynetroxler/AudiobookOffline-Linux\">Linux</a>.</p>"
    "<p>Released under the MIT License.</p>"
)

_active_signal_objects = set()


class _WorkerSignals(QObject):
    finished = Signal(object, object)


class _UiPoster(QObject):
    call = Signal(object)


_ui_poster = _UiPoster()
_ui_poster.call.connect(lambda fn: fn(), Qt.ConnectionType.QueuedConnection)


def post_to_ui(fn):
    """Queue `fn` to run on the Qt main thread, without spawning a thread."""
    _ui_poster.call.emit(fn)


def run_in_background(work, on_done):
    """Run `work()` off the main thread; deliver its result (or exception) to
    `on_done` back on the Qt main thread via a queued signal, since widgets
    may only be touched from there."""
    signals = _WorkerSignals()
    _active_signal_objects.add(signals)

    def cleanup(result, error):
        _active_signal_objects.discard(signals)
        on_done(result, error)

    signals.finished.connect(cleanup, Qt.ConnectionType.QueuedConnection)

    def target():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
            signals.finished.emit(None, exc)
        else:
            signals.finished.emit(result, None)

    threading.Thread(target=target, daemon=True).start()


def elide(label: QLabel, text: str, width: int = 260):
    label.setText(QFontMetrics(label.font()).elidedText(text, Qt.TextElideMode.ElideRight, width))


class LoginPage(QWidget):
    def __init__(self, on_success):
        super().__init__()
        self.on_success = on_success

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(12)

        self.server_entry = QLineEdit(placeholderText="Server URL, e.g. http://192.168.1.10:13378")
        self.username_entry = QLineEdit(placeholderText="Username")
        self.password_entry = QLineEdit(placeholderText="Password")
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d33;")

        login_button = QPushButton("Log In")
        login_button.clicked.connect(self._on_login_clicked)

        for widget in (self.server_entry, self.username_entry, self.password_entry, login_button, self.status_label):
            layout.addWidget(widget)
        layout.addStretch(1)

    def _on_login_clicked(self):
        server = self.server_entry.text().strip()
        username = self.username_entry.text().strip()
        password = self.password_entry.text()
        self.status_label.setText("Logging in…")

        def work():
            client, token = ABSClient.login(server, username, password)
            save_creds(ServerCredentials(server_url=client.base_url, username=username, token=token))
            return client

        def done(client, error):
            if error is not None:
                self.status_label.setText(str(error))
                return
            self.on_success(client)

        run_in_background(work, done)


class LibraryPage(QWidget):
    def __init__(self, client: ABSClient, on_item_activated, on_stats_activated):
        super().__init__()
        self.client = client
        self.on_item_activated = on_item_activated
        self.on_stats_activated = on_stats_activated
        self.library_id = None
        self._all_items = []
        self._continue_items = []
        self._series_groups = []
        self._collection_groups = []
        self.browse_mode = "books"
        self._current_group = None

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        self.search_entry = QLineEdit(placeholderText="Search title or author…")
        self.search_entry.textChanged.connect(self._on_search_changed)
        header_row.addWidget(self.search_entry, 1)
        stats_button = QPushButton("Stats")
        stats_button.clicked.connect(lambda: self.on_stats_activated())
        header_row.addWidget(stats_button)
        layout.addLayout(header_row)

        browse_row = QHBoxLayout()
        browse_row.addStretch(1)
        self.books_toggle = QPushButton("Books", checkable=True, checked=True)
        self.series_toggle = QPushButton("Series", checkable=True)
        self.collections_toggle = QPushButton("Collections", checkable=True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for button, mode in ((self.books_toggle, "books"), (self.series_toggle, "series"), (self.collections_toggle, "collections")):
            group.addButton(button)
            button.clicked.connect(lambda _checked, m=mode: self._on_browse_mode_changed(m))
            browse_row.addWidget(button)
        browse_row.addStretch(1)
        layout.addLayout(browse_row)

        scroller = QScrollArea(widgetResizable=True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(6)
        scroller.setWidget(content)
        layout.addWidget(scroller, 1)

        self.continue_label = QLabel("Continue Listening")
        self.continue_label.setStyleSheet("font-weight: 600;")
        self.continue_label.setVisible(False)
        content_layout.addWidget(self.continue_label)

        self.continue_list = QListWidget(visible=False)
        self.continue_list.itemClicked.connect(self._on_row_activated)
        self.continue_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content_layout.addWidget(self.continue_list)

        self.status_label = QLabel("Loading libraries…")
        content_layout.addWidget(self.status_label)

        self.list_box = QListWidget()
        self.list_box.itemClicked.connect(self._on_row_activated)
        self.list_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content_layout.addWidget(self.list_box)

        run_in_background(self._load_first_library, self._on_items_loaded)

    def _load_first_library(self):
        libraries = self.client.libraries()
        if not libraries:
            return None, [], [], [], []
        library_id = libraries[0].id
        items = self.client.items(library_id)
        continue_items = self.client.continue_listening(library_id)
        series_groups = self.client.series(library_id)
        collection_groups = self.client.collections(library_id)
        return library_id, items, continue_items, series_groups, collection_groups

    def _on_items_loaded(self, result, error):
        if error is not None:
            self.status_label.setText(f"Failed to load library: {error}")
            return
        library_id, items, continue_items, series_groups, collection_groups = result
        self.library_id = library_id
        self._all_items = items
        self._continue_items = continue_items
        self._series_groups = series_groups
        self._collection_groups = collection_groups
        self._populate_continue(continue_items)
        self.status_label.setText(f"{len(items)} books")
        self._populate(items)

    def _make_row_widget(self, item: LibraryItem, removable=False, show_download_status=False):
        author = item.metadata.author_name or "Unknown author"

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)

        cover = QLabel()
        cover.setFixedSize(40, 56)
        cover.setScaledContents(True)
        self._load_cover(item, cover)
        row_layout.addWidget(cover)

        text_box = QVBoxLayout()
        title_label = QLabel()
        elide(title_label, item.metadata.title)
        author_label = QLabel()
        elide(author_label, author)
        author_label.setStyleSheet("color: gray;")
        text_box.addWidget(title_label)
        text_box.addWidget(author_label)
        row_layout.addLayout(text_box, 1)

        if show_download_status:
            row_layout.addWidget(self._make_download_controls(item))

        if removable:
            remove_button = QPushButton("✕")
            remove_button.setFlat(True)
            remove_button.setToolTip("Remove from Continue Listening")
            remove_button.clicked.connect(lambda: self._on_remove_continue(item))
            row_layout.addWidget(remove_button)

        return row

    def _load_cover(self, item, label: QLabel):
        client = self.client

        def done(path, error):
            if error is None and path is not None:
                label.setPixmap(QPixmap(str(path)))

        run_in_background(lambda: covers.fetch(client, item.id, width=80), done)

    def _make_download_controls(self, item) -> QWidget:
        """Blue button + green status dot shown on Continue Listening rows, so
        someone about to leave home network can see at a glance what's safe to
        listen to offline. See the Help menu for what the icons mean."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        download_button = QPushButton("⬇")
        download_button.setFixedSize(20, 20)
        download_button.setEnabled(False)
        download_button.setStyleSheet(
            "QPushButton { background-color: #2f7de1; color: white; border: none; border-radius: 10px; font-size: 10px; }"
            "QPushButton:disabled { background-color: #a9c2e8; }"
            "QPushButton:hover:!disabled { background-color: #1f63c4; }"
        )
        layout.addWidget(download_button)

        status_dot = QLabel()
        status_dot.setFixedSize(10, 10)
        status_dot.setStyleSheet("background-color: transparent; border-radius: 5px;")
        layout.addWidget(status_dot)

        self._init_download_controls(item, download_button, status_dot)
        return container

    def _init_download_controls(self, item, button: QPushButton, dot: QLabel):
        client = self.client
        state = {"tracks": None}

        def refresh():
            is_downloaded = state["tracks"] is not None and downloads.is_fully_downloaded(item.id, state["tracks"])
            dot.setStyleSheet(
                "background-color: #2ecc71; border-radius: 5px;" if is_downloaded
                else "background-color: transparent; border-radius: 5px;"
            )
            button.setToolTip("Downloaded — tap to remove and free up space" if is_downloaded else "Download for offline listening")

        def on_detail(detail, error):
            if error is not None:
                return
            state["tracks"] = detail.tracks
            button.setEnabled(True)
            refresh()

        def on_click():
            tracks = state["tracks"]
            if tracks is None:
                return
            if downloads.is_fully_downloaded(item.id, tracks):
                downloads.delete_downloads(item.id)
                refresh()
                return
            button.setEnabled(False)

            def work():
                downloads.download_tracks(client, item.id, tracks, lambda *_a: None)

            def done(_result, error):
                button.setEnabled(True)
                refresh()

            run_in_background(work, done)

        button.clicked.connect(on_click)
        run_in_background(lambda: client.item_detail(item.id), on_detail)

    def _add_item_row(self, list_widget: QListWidget, item, removable=False, show_download_status=False):
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, ("item", item))
        row_widget = self._make_row_widget(item, removable=removable, show_download_status=show_download_status)
        list_item.setSizeHint(row_widget.sizeHint())
        list_widget.addItem(list_item)
        list_widget.setItemWidget(list_item, row_widget)

    def _populate(self, items):
        self.list_box.clear()
        for item in items:
            self._add_item_row(self.list_box, item)

    def _populate_continue(self, items):
        self.continue_list.clear()
        has_items = bool(items)
        self.continue_label.setVisible(has_items)
        self.continue_list.setVisible(has_items)
        for item in items:
            self._add_item_row(self.continue_list, item, removable=True, show_download_status=True)

    def _on_remove_continue(self, item):
        client = self.client
        run_in_background(
            lambda: client.hide_from_continue_listening(item.id),
            lambda _result, error: self._on_removed_from_continue(item, error),
        )

    def _on_removed_from_continue(self, item, error):
        if error is not None:
            self.status_label.setText(f"Couldn't remove from Continue Listening: {error}")
            return
        self._continue_items = [i for i in self._continue_items if i.id != item.id]
        self._populate_continue(self._continue_items)

    def _on_row_activated(self, list_item: QListWidgetItem):
        kind, payload = list_item.data(Qt.ItemDataRole.UserRole)
        if kind == "back":
            groups = self._series_groups if self.browse_mode == "series" else self._collection_groups
            self._show_groups(groups, self.browse_mode)
        elif kind == "group":
            self._show_group_detail(payload)
        elif kind == "item":
            self.on_item_activated(payload)

    def _on_browse_mode_changed(self, mode):
        self.browse_mode = mode
        self._current_group = None
        if mode == "books":
            self.status_label.setText(f"{len(self._all_items)} books")
            self._populate(self._all_items)
        elif mode == "series":
            self._show_groups(self._series_groups, "series")
        elif mode == "collections":
            self._show_groups(self._collection_groups, "collections")

    def _show_groups(self, groups, kind):
        self.status_label.setText(f"{len(groups)} {kind}")
        self.list_box.clear()
        for group in groups:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 8, 4)
            name_label = QLabel()
            elide(name_label, group.name)
            count_label = QLabel(f"{len(group.books)} books")
            count_label.setStyleSheet("color: gray;")
            row_layout.addWidget(name_label, 1)
            row_layout.addWidget(count_label)

            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, ("group", group))
            list_item.setSizeHint(row.sizeHint())
            self.list_box.addItem(list_item)
            self.list_box.setItemWidget(list_item, row)

    def _show_group_detail(self, group):
        self._current_group = group
        self.status_label.setText(f"{group.name} · {len(group.books)} books")
        self.list_box.clear()

        back_row = QWidget()
        back_layout = QHBoxLayout(back_row)
        back_layout.setContentsMargins(8, 4, 8, 4)
        back_layout.addWidget(QLabel(f"← All {self.browse_mode.capitalize()}"))
        back_item = QListWidgetItem()
        back_item.setData(Qt.ItemDataRole.UserRole, ("back", None))
        back_item.setSizeHint(back_row.sizeHint())
        self.list_box.addItem(back_item)
        self.list_box.setItemWidget(back_item, back_row)

        for item in group.books:
            self._add_item_row(self.list_box, item)

    def _on_search_changed(self, text):
        if self.library_id is None:
            return
        query = text.strip()
        if not query:
            self.status_label.setText(f"{len(self._all_items)} books")
            self._populate(self._all_items)
            return
        self.status_label.setText("Searching…")
        run_in_background(lambda: self.client.search(self.library_id, query, limit=40), self._on_search_results)

    def _on_search_results(self, items, error):
        if error is not None:
            self.status_label.setText(f"Search failed: {error}")
            return
        self.status_label.setText(f"{len(items)} result{'s' if len(items) != 1 else ''}")
        self._populate(items)


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_duration_long(seconds: float) -> str:
    total_hours = seconds / 3600
    days, hours = divmod(int(total_hours), 24)
    return f"{days}d {hours}h" if days else f"{hours}h"


class PlayerPage(QWidget):
    def __init__(self, client: ABSClient, item: LibraryItem, on_back, media_controls=None):
        super().__init__()
        self.client = client
        self.item = item
        self.on_back = on_back
        self.media_controls = media_controls
        self.tracks = []
        self.total_duration = 0.0
        self.track_index = 0
        self.seeking = False
        self.chapters = []
        self.chapter_index = 0
        self.chapter_rows = []
        self.playback_rate = 1.0
        self._pending_seek_ms = None
        self._pending_autoplay = False
        self._sleep_end_of_chapter = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 12)
        outer.setSpacing(12)

        back_button = QPushButton("← Back")
        back_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back_button.clicked.connect(self._go_back)
        outer.addWidget(back_button, 0, Qt.AlignmentFlag.AlignLeft)

        scroller = QScrollArea(widgetResizable=True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        scroller.setWidget(content)
        outer.addWidget(scroller, 1)

        cover = QLabel()
        cover.setFixedSize(180, 180)
        cover.setScaledContents(True)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def on_cover_done(path, error):
            if error is None and path is not None:
                cover.setPixmap(QPixmap(str(path)))

        run_in_background(lambda: covers.fetch(client, item.id, width=300), on_cover_done)
        content_layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(item.metadata.title)
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 16pt; font-weight: 600;")
        content_layout.addWidget(title_label)

        author_label = QLabel(item.metadata.author_name or "Unknown author")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setStyleSheet("color: gray;")
        content_layout.addWidget(author_label)

        self.download_status_label = QLabel("")
        self.download_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.download_status_label.setStyleSheet("color: gray; font-size: 9pt;")
        self.download_status_label.setVisible(False)
        content_layout.addWidget(self.download_status_label)

        self.chapter_label = QLabel("")
        self.chapter_label.setWordWrap(True)
        self.chapter_label.setStyleSheet("color: gray;")
        content_layout.addWidget(self.chapter_label)

        self.status_label = QLabel("Loading…")
        content_layout.addWidget(self.status_label)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.position_slider.setRange(0, 1)
        self.position_slider.setEnabled(False)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        content_layout.addWidget(self.position_slider)

        time_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00")
        self.remaining_label = QLabel("0:00")
        time_row.addWidget(self.elapsed_label)
        time_row.addStretch(1)
        time_row.addWidget(self.remaining_label)
        content_layout.addLayout(time_row)

        transport_row = QHBoxLayout()
        transport_row.addStretch(1)

        self.prev_chapter_button = QPushButton("⏮ Chapter")
        self.prev_chapter_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_chapter_button.setEnabled(False)
        self.prev_chapter_button.clicked.connect(lambda: self._jump_chapter(-1))
        transport_row.addWidget(self.prev_chapter_button)

        self.skip_back_button = QPushButton("-30s")
        self.skip_back_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_back_button.setEnabled(False)
        self.skip_back_button.clicked.connect(lambda: self._skip(-30))
        transport_row.addWidget(self.skip_back_button)

        self.play_button = QPushButton("Play")
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_play)
        transport_row.addWidget(self.play_button)

        self.skip_forward_button = QPushButton("+30s")
        self.skip_forward_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_forward_button.setEnabled(False)
        self.skip_forward_button.clicked.connect(lambda: self._skip(30))
        transport_row.addWidget(self.skip_forward_button)

        self.next_chapter_button = QPushButton("Chapter ⏭")
        self.next_chapter_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next_chapter_button.setEnabled(False)
        self.next_chapter_button.clicked.connect(lambda: self._jump_chapter(1))
        transport_row.addWidget(self.next_chapter_button)

        transport_row.addStretch(1)
        content_layout.addLayout(transport_row)

        self.download_button = QPushButton("Download")
        self.download_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._on_download_clicked)
        content_layout.addWidget(self.download_button, 0, Qt.AlignmentFlag.AlignHCenter)

        options_row = QHBoxLayout()
        options_row.addStretch(1)

        self._speed_options = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        self.speed_dropdown = QComboBox()
        self.speed_dropdown.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed_dropdown.addItems([f"{s}×" for s in self._speed_options])
        self.speed_dropdown.setCurrentIndex(self._speed_options.index(1.0))
        self.speed_dropdown.currentIndexChanged.connect(self._on_speed_changed)
        options_row.addWidget(self.speed_dropdown)

        self._sleep_options = [0, 5, 10, 15, 30, 45, 60, -1]
        self.sleep_dropdown = QComboBox()
        self.sleep_dropdown.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sleep_dropdown.addItems(["Sleep: Off", "5 min", "10 min", "15 min", "30 min", "45 min", "60 min", "End of Chapter"])
        self.sleep_dropdown.currentIndexChanged.connect(self._on_sleep_changed)
        options_row.addWidget(self.sleep_dropdown)

        self.sleep_countdown_label = QLabel("")
        self.sleep_countdown_label.setStyleSheet("color: gray;")
        options_row.addWidget(self.sleep_countdown_label)

        options_row.addStretch(1)
        content_layout.addLayout(options_row)

        self.chapters_heading = QLabel("")
        self.chapters_heading.setStyleSheet("font-weight: 600; margin-top: 12px;")
        self.chapters_heading.setVisible(False)
        content_layout.addWidget(self.chapters_heading)

        self.chapter_list = QListWidget(visible=False)
        self.chapter_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chapter_list.itemClicked.connect(self._on_chapter_row_activated)
        content_layout.addWidget(self.chapter_list)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(500)

        self._report_timer = QTimer(self)
        self._report_timer.timeout.connect(self._periodic_report)
        self._report_timer.start(20_000)

        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._on_sleep_fire)

        def work():
            detail = client.item_detail(item.id)
            progress = client.media_progress().get(item.id)
            return detail, progress

        run_in_background(work, self._on_detail_loaded)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_detail_loaded(self, result, error):
        if error is not None:
            self.status_label.setText(f"Failed to load book: {error}")
            return
        detail, progress = result
        self.tracks = detail.tracks
        if not self.tracks:
            self.status_label.setText("This book has no playable tracks.")
            return
        self.chapters = detail.chapters
        self._populate_chapter_list()
        self.total_duration = sum(t.duration for t in self.tracks)
        self.status_label.setText("")
        self.position_slider.setEnabled(True)
        self.play_button.setEnabled(True)
        self.skip_back_button.setEnabled(True)
        self.skip_forward_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self._refresh_download_button()
        if progress is not None and 0 < progress.current_time < self.total_duration and not progress.is_finished:
            index, offset = self._resolve_position(progress.current_time)
            self._load_track(index, autoplay=False, seek_offset=offset)
        else:
            self._load_track(0, autoplay=False)

    def _resolve_position(self, global_pos):
        remaining = global_pos
        for i, track in enumerate(self.tracks):
            if remaining < track.duration or i == len(self.tracks) - 1:
                return i, max(0.0, remaining)
            remaining -= track.duration
        return 0, 0.0

    def _track_start_offset(self, index):
        return sum(t.duration for t in self.tracks[:index])

    def _local_path(self, track):
        return downloads.track_path(self.item.id, track.index, track.mime_type)

    def _track_url(self, track) -> QUrl:
        local_path = self._local_path(track)
        if local_path.exists():
            return QUrl.fromLocalFile(str(local_path))
        return QUrl(self.client.stream_url(track.content_url))

    def _refresh_download_button(self):
        if downloads.is_fully_downloaded(self.item.id, self.tracks):
            self.download_button.setText("Remove Download")
            size = downloads.downloaded_size(self.item.id, self.tracks)
            self.download_status_label.setText(f"Downloaded · {downloads.format_size(size)}")
            self.download_status_label.setVisible(True)
        else:
            self.download_button.setText("Download")
            self.download_status_label.setVisible(False)

    def _on_download_clicked(self):
        if downloads.is_fully_downloaded(self.item.id, self.tracks):
            downloads.delete_downloads(self.item.id)
            self._refresh_download_button()
            return

        self.download_button.setEnabled(False)
        item_id, client, tracks = self.item.id, self.client, list(self.tracks)

        def progress(done, total):
            post_to_ui(lambda: self.download_button.setText(f"Downloading {done}/{total}…"))

        def work():
            downloads.download_tracks(client, item_id, tracks, progress)

        def done(_result, error):
            self.download_button.setEnabled(True)
            if error is not None:
                self.download_button.setText("Download failed — retry")
                return
            self._refresh_download_button()

        run_in_background(work, done)

    def _is_playing(self):
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _find_chapter_index(self, global_pos):
        for i, chapter in enumerate(self.chapters):
            if chapter.start <= global_pos < chapter.end:
                return i
        return len(self.chapters) - 1

    def _sync_chapter_ui(self, global_pos):
        self.chapter_index = self._find_chapter_index(global_pos)
        chapter = self.chapters[self.chapter_index]
        if len(self.chapters) > 1:
            self.chapter_label.setText(f"Chapter {self.chapter_index + 1} of {len(self.chapters)}: {chapter.title}")
        else:
            self.chapter_label.setText(chapter.title)
        self.position_slider.blockSignals(True)
        self.position_slider.setRange(0, max(1, int(chapter.end - chapter.start)))
        rel = global_pos - chapter.start
        self.position_slider.setValue(int(rel))
        self.position_slider.blockSignals(False)
        self.elapsed_label.setText(format_time(rel))
        self.remaining_label.setText(f"-{format_time(chapter.end - global_pos)}")
        self.prev_chapter_button.setEnabled(self.chapter_index > 0)
        self.next_chapter_button.setEnabled(self.chapter_index < len(self.chapters) - 1)
        if self.chapter_rows:
            self.chapter_list.setCurrentRow(self.chapter_index)

    def _populate_chapter_list(self):
        self.chapter_list.clear()
        self.chapter_rows = []

        if len(self.chapters) <= 1:
            self.chapters_heading.setVisible(False)
            self.chapter_list.setVisible(False)
            return

        self.chapters_heading.setText(f"Chapters ({len(self.chapters)})")
        self.chapters_heading.setVisible(True)
        self.chapter_list.setVisible(True)
        for i, chapter in enumerate(self.chapters):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 8, 4)
            title_label = QLabel()
            elide(title_label, f"{i + 1}. {chapter.title}")
            duration_label = QLabel(format_time(chapter.end - chapter.start))
            duration_label.setStyleSheet("color: gray;")
            row_layout.addWidget(title_label, 1)
            row_layout.addWidget(duration_label)

            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, i)
            list_item.setSizeHint(row.sizeHint())
            self.chapter_list.addItem(list_item)
            self.chapter_list.setItemWidget(list_item, row)
            self.chapter_rows.append(list_item)

    def _on_chapter_row_activated(self, list_item: QListWidgetItem):
        chapter_index = list_item.data(Qt.ItemDataRole.UserRole)
        chapter = self.chapters[chapter_index]
        self._seek_to_global(chapter.start, autoplay=self._is_playing())

    def _load_track(self, index, autoplay, seek_offset=0):
        self.track_index = index
        track = self.tracks[index]
        self._pending_seek_ms = int(seek_offset * 1000) if seek_offset > 0 else None
        self._pending_autoplay = autoplay
        self.player.setPlaybackRate(self.playback_rate)
        self.player.setSource(self._track_url(track))
        self._sync_chapter_ui(self._track_start_offset(index) + seek_offset)
        self.play_button.setText("Pause" if autoplay else "Play")
        if self.media_controls is not None:
            self.media_controls.notify()

    def _seek_to_global(self, global_pos, autoplay):
        index, offset = self._resolve_position(global_pos)
        if index == self.track_index:
            self.player.setPosition(int(offset * 1000))
            if autoplay and not self._is_playing():
                self.player.play()
            self._sync_chapter_ui(global_pos)
        else:
            self._load_track(index, autoplay=autoplay, seek_offset=offset)
        if self.media_controls is not None:
            self.media_controls.seeked(int(global_pos * 1_000_000))

    def _jump_chapter(self, direction):
        target = self.chapter_index + direction
        if not (0 <= target < len(self.chapters)):
            return
        self._seek_to_global(self.chapters[target].start, autoplay=self._is_playing())

    def _skip(self, seconds):
        if not self.tracks:
            return
        current_global = self._track_start_offset(self.track_index) + self.player.position() / 1000
        target = min(max(0.0, current_global + seconds), self.total_duration - 0.1)
        self._seek_to_global(target, autoplay=self._is_playing())

    def _toggle_play(self):
        if not self.tracks:
            return
        if self._is_playing():
            self.player.pause()
            self.play_button.setText("Play")
            self._report_progress()
        else:
            self.player.play()
            self.play_button.setText("Pause")
        if self.media_controls is not None:
            self.media_controls.notify()

    def _on_slider_pressed(self):
        self.seeking = True

    def _on_slider_released(self):
        self.seeking = False
        chapter = self.chapters[self.chapter_index]
        self._seek_to_global(chapter.start + self.position_slider.value(), autoplay=self._is_playing())

    def _on_speed_changed(self, index):
        self.playback_rate = self._speed_options[index]
        if not self.tracks:
            return
        self.player.setPlaybackRate(self.playback_rate)

    def _on_sleep_changed(self, index):
        self._sleep_timer.stop()
        self._sleep_end_of_chapter = False
        choice = self._sleep_options[index]
        if choice == 0:
            self.sleep_countdown_label.setText("")
            return
        if choice == -1:
            self.sleep_countdown_label.setText("Sleeping at end of chapter")
            return
        self._sleep_timer.start(choice * 60_000)
        self.sleep_countdown_label.setText(f"-{format_time(choice * 60)}")

    def _on_sleep_fire(self):
        self.sleep_dropdown.setCurrentIndex(0)
        self.sleep_countdown_label.setText("")
        self._pause_for_sleep()

    def _pause_for_sleep(self):
        if self._is_playing():
            self.player.pause()
            self.play_button.setText("Play")
            self._report_progress()

    def _on_tick(self):
        if self._sleep_timer.isActive():
            self.sleep_countdown_label.setText(f"-{format_time(self._sleep_timer.remainingTime() / 1000)}")
        if not self.tracks or self.seeking:
            return
        global_pos = self._track_start_offset(self.track_index) + self.player.position() / 1000
        chapter_idx = self._find_chapter_index(global_pos)
        if chapter_idx != self.chapter_index:
            if self._sleep_end_of_chapter:
                self._sleep_end_of_chapter = False
                self.sleep_dropdown.setCurrentIndex(0)
                self._pause_for_sleep()
            self._sync_chapter_ui(global_pos)
        else:
            chapter = self.chapters[self.chapter_index]
            rel = global_pos - chapter.start
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(int(rel))
            self.position_slider.blockSignals(False)
            self.elapsed_label.setText(format_time(rel))
            self.remaining_label.setText(f"-{format_time(chapter.end - global_pos)}")
        if self.media_controls is not None:
            self.media_controls.notify()

    def _on_media_status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending_seek_ms is not None:
                self.player.setPosition(self._pending_seek_ms)
                self._pending_seek_ms = None
            if self._pending_autoplay:
                self._pending_autoplay = False
                self.player.play()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.track_index + 1 < len(self.tracks):
                self._load_track(self.track_index + 1, autoplay=True)
            else:
                self.player.pause()
                self.play_button.setText("Play")
                self._report_progress(is_finished=True)

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.status_label.setText(f"Playback error: {error_string}")

    def _periodic_report(self):
        if self._is_playing():
            self._report_progress()

    def _report_progress(self, is_finished=False):
        if not self.tracks:
            return
        global_pos = self._track_start_offset(self.track_index) + self.player.position() / 1000
        item_id, client, total_duration = self.item.id, self.client, self.total_duration
        run_in_background(
            lambda: client.update_progress(item_id, global_pos, total_duration, is_finished),
            lambda _result, _error: None,
        )

    def _go_back(self):
        self._report_progress()
        self.player.stop()
        self._tick_timer.stop()
        self._report_timer.stop()
        self._sleep_timer.stop()
        self.on_back()


class StatsPage(QWidget):
    def __init__(self, client: ABSClient, library_id: str | None, on_back):
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 12)
        outer.setSpacing(12)

        back_button = QPushButton("← Back")
        back_button.clicked.connect(lambda: on_back())
        outer.addWidget(back_button, 0, Qt.AlignmentFlag.AlignLeft)

        title = QLabel("Library Stats")
        title.setStyleSheet("font-size: 16pt; font-weight: 600;")
        outer.addWidget(title)

        scroller = QScrollArea(widgetResizable=True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setSpacing(16)
        scroller.setWidget(self.content)
        outer.addWidget(scroller, 1)

        self.status_label = QLabel("Loading…")
        self.content_layout.addWidget(self.status_label)

        if library_id is None:
            self.status_label.setText("Library not loaded yet — go back and try again.")
            return

        run_in_background(lambda: client.library_stats(library_id), self._on_stats_loaded)

    def _on_stats_loaded(self, stats, error):
        if error is not None:
            self.status_label.setText(f"Failed to load stats: {error}")
            return
        self.status_label.setVisible(False)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        rows = [
            ("Books", str(stats.total_items)),
            ("Authors", str(stats.total_authors)),
            ("Genres", str(stats.total_genres)),
            ("Audio tracks", str(stats.num_tracks)),
            ("Total listening time", format_duration_long(stats.total_duration)),
            ("Total size", downloads.format_size(stats.total_size)),
        ]
        for label, value in rows:
            row = QHBoxLayout()
            label_widget = QLabel(label)
            label_widget.setStyleSheet("color: gray;")
            value_widget = QLabel(value)
            value_widget.setStyleSheet("font-size: 12pt; font-weight: 600;")
            row.addWidget(label_widget)
            row.addStretch(1)
            row.addWidget(value_widget)
            overview_layout.addLayout(row)
        self.content_layout.addWidget(overview)

        self.content_layout.addWidget(self._section("Top 10 Authors", [(a.name, f"{a.count} books") for a in stats.top_authors]))
        self.content_layout.addWidget(self._section("Top 5 Genres", [(g.genre, f"{g.count} books") for g in stats.top_genres[:5]]))
        self.content_layout.addWidget(self._section("Longest Books", [(i.title, format_time(i.value)) for i in stats.longest_items]))
        self.content_layout.addWidget(self._section("Largest Books", [(i.title, downloads.format_size(int(i.value))) for i in stats.largest_items]))

    @staticmethod
    def _section(heading_text, rows):
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(4)
        heading = QLabel(heading_text)
        heading.setStyleSheet("font-weight: 600;")
        box_layout.addWidget(heading)

        for title, value in rows:
            row_box = QVBoxLayout()
            title_label = QLabel(title)
            title_label.setWordWrap(True)
            value_label = QLabel(value)
            value_label.setStyleSheet("color: gray;")
            row_box.addWidget(title_label)
            row_box.addWidget(value_label)
            box_layout.addLayout(row_box)
        return box


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audiobook Offline")
        self.resize(480, 640)
        if _ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(_ICON_PATH)))

        help_menu = self.menuBar().addMenu("Help")
        help_action = help_menu.addAction("Audiobook Offline Help")
        help_action.triggered.connect(self._show_help)
        help_menu.addSeparator()
        about_action = help_menu.addAction("About Audiobook Offline")
        about_action.triggered.connect(self._show_about)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._pages = {}
        self.active_player = None
        self.media_controls = MediaControls(
            get_status=self._mc_status,
            get_metadata=self._mc_metadata,
            get_position_us=self._mc_position_us,
            actions={
                "play": self._mc_play,
                "pause": self._mc_pause,
                "play_pause": self._mc_play_pause,
                "next": self._mc_next,
                "previous": self._mc_previous,
                "seek": self._mc_seek,
                "set_position": self._mc_set_position,
            },
        )

        self.client = None
        creds = load_creds()
        if creds is not None:
            self.client = ABSClient(creds.server_url, creds.token)
            self._show_page("library", LibraryPage(self.client, self._on_item_activated, self._on_stats_activated))
        else:
            self._show_page("login", LoginPage(self._on_logged_in))

    def _show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Audiobook Offline Help")
        dialog.resize(520, 600)
        layout = QVBoxLayout(dialog)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        dialog.exec()

    def _show_about(self):
        QMessageBox.about(self, "About Audiobook Offline", _ABOUT_TEXT)

    def _show_page(self, name, widget):
        old = self._pages.get(name)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        self._pages[name] = widget
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)
        widget.setFocus()

    def _on_logged_in(self, client: ABSClient):
        self.client = client
        self._show_page("library", LibraryPage(client, self._on_item_activated, self._on_stats_activated))

    def _on_item_activated(self, item):
        player = PlayerPage(self.client, item, self._show_library, media_controls=self.media_controls)
        self.active_player = player
        self._show_page("player", player)

    def _on_stats_activated(self):
        library_page = self._pages.get("library")
        library_id = library_page.library_id if library_page is not None else None
        self._show_page("stats", StatsPage(self.client, library_id, self._show_library))

    def _show_library(self):
        self.active_player = None
        self.stack.setCurrentWidget(self._pages["library"])

    def _mc_status(self):
        p = self.active_player
        if p is None or not p.tracks:
            return "Stopped"
        return "Playing" if p._is_playing() else "Paused"

    def _mc_metadata(self):
        p = self.active_player
        if p is None or not p.tracks:
            return None
        return {
            "title": p.item.metadata.title,
            "artist": p.item.metadata.author_name or "",
            "length_us": int(p.total_duration * 1_000_000),
            "track_id": f"/org/audiobookoffline/track/{p.item.id.replace('-', '_')}",
        }

    def _mc_position_us(self):
        p = self.active_player
        if p is None or not p.tracks:
            return 0
        return int((p._track_start_offset(p.track_index) + p.player.position() / 1000) * 1_000_000)

    def _mc_play(self):
        if self.active_player is not None and not self.active_player._is_playing():
            self.active_player._toggle_play()

    def _mc_pause(self):
        if self.active_player is not None and self.active_player._is_playing():
            self.active_player._toggle_play()

    def _mc_play_pause(self):
        if self.active_player is not None:
            self.active_player._toggle_play()

    def _mc_next(self):
        if self.active_player is not None:
            self.active_player._jump_chapter(1)

    def _mc_previous(self):
        if self.active_player is not None:
            self.active_player._jump_chapter(-1)

    def _mc_seek(self, offset_us):
        p = self.active_player
        if p is None:
            return
        target = max(0.0, (self._mc_position_us() + offset_us) / 1_000_000)
        p._seek_to_global(target, autoplay=p._is_playing())

    def _mc_set_position(self, _track_id, position_us):
        p = self.active_player
        if p is None:
            return
        p._seek_to_global(position_us / 1_000_000, autoplay=p._is_playing())


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Audiobook Offline")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
