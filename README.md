# AudiobookOffline (Windows)

A native PySide6 (Qt) desktop client for [Audiobookshelf](https://github.com/advplyr/audiobookshelf) — browse your library, stream, download books for true offline playback, and keep listening progress synced back to your server.

A Windows counterpart to the [macOS AudiobookOffline app](https://github.com/shaynetroxler/AudiobookOffline) and the [Linux AudiobookOffline app](https://github.com/shaynetroxler/AudiobookOffline-Linux), built for the same reason: none of the existing Audiobookshelf clients do local pre-download for offline use.

## Status

Early port from the Linux (GTK) version — core flow (login, browse, stream, download, chapters, speed, sleep timer, stats) is implemented and untested against a real server. Lock-screen / media-key integration (System Media Transport Controls) is stubbed out for now; see `absplayer/media_controls.py`.

## Features

- Log in to any self-hosted Audiobookshelf server
- Browse your full library, search by title or author
- Browse by Series or Collections
- Continue Listening shelf, with the ability to remove a book from it at any time
- Library stats dashboard — item/author/genre/track counts, total listening time and size, top authors and genres, longest and largest items
- Stream playback, or download a book for fully offline listening
- Chapter list with jump-to-chapter, current chapter highlighted, seek slider scoped to the current chapter
- ±30s skip buttons
- Variable playback speed (0.75×–2×) — pitch correction on Windows not yet verified by ear, see the porting notes
- Sleep timer (5–60 min, or end of chapter)
- Progress reported back to the server as you listen, reconciled on resume so progress made on another device is picked up correctly
- Cover art throughout

## Download

Don't want to deal with Python? Grab the latest `AudiobookOffline.exe` from the
[Releases page](https://github.com/shaynetroxler/AudiobookOffline-Windows/releases) —
download it, double-click it, done. No install, no dependencies.

Windows will likely warn that the exe is from an unrecognized publisher (it's
not code-signed) — click "More info" → "Run anyway" to proceed.

## Running from source

- Python 3.11+
- An Audiobookshelf server you can reach (local network or otherwise)

```
pip install -r requirements.txt
python -m absplayer.app
```

## License

MIT
