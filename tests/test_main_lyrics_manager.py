from types import SimpleNamespace

from src.lrc_parser import LyricLine, LyricsData
from src.lyrics_library import LyricsCandidate, UserLyricsEntry
from src.main import LetraCancionApp
from src.models import PlaybackInfo, PlayerState, TrackInfo
from src.ui.lyrics_manager import LyricsSaveRequest


class FakeCache:
    def __init__(self):
        self.saved = []

    def save(self, artist, title, lyrics):
        self.saved.append((artist, title, lyrics))


class FakeLyricsService:
    def __init__(self):
        self.cache = FakeCache()
        self.saved = []

    def has_user_lyrics(self, artist, title):
        return False

    def save_user_lyrics(self, **kwargs):
        self.saved.append(kwargs)
        return UserLyricsEntry(
            artist=kwargs["artist"],
            title=kwargs["title"],
            album=kwargs["album"],
            duration_ms=kwargs["duration_ms"],
            source=kwargs["source"],
            lyrics_data=kwargs["lyrics_data"],
        )


class FakeManager:
    def __init__(self):
        self.saved_success = []
        self.captured = []

    def show_save_success(self, artist, title):
        self.saved_success.append((artist, title))

    def set_captured_timestamp(self, row, timestamp_ms):
        self.captured.append((row, timestamp_ms))


class FakeTranslationService:
    def __init__(self):
        self.invalidated = []

    def invalidate_track(self, artist, title):
        self.invalidated.append((artist, title))


class FakeSyncEngine:
    def __init__(self):
        self.loaded = []

    def set_lyrics(self, lyrics, duration_ms):
        self.loaded.append((lyrics, duration_ms))


class FakeOverlay:
    def __init__(self):
        self.loaded = []
        self.offsets = []

    def set_lyrics(self, lyrics, duration_ms):
        self.loaded.append((lyrics, duration_ms))

    def show_offset_indicator(self, offset_ms):
        self.offsets.append(offset_ms)


class FakeTray:
    def __init__(self):
        self.notifications = []
        self.errors = []

    def show_notification(self, title, message, **kwargs):
        self.notifications.append((title, message))

    def show_error(self, message):
        self.errors.append(message)


def make_app():
    app = LetraCancionApp.__new__(LetraCancionApp)
    app.lyrics_service = FakeLyricsService()
    app.translation_service = FakeTranslationService()
    app.lyrics_manager = FakeManager()
    app.sync_engine = FakeSyncEngine()
    app.overlay = FakeOverlay()
    app.tray = FakeTray()
    app._current_track = TrackInfo(title="Creep", artist="Radiohead")
    app._translation_enabled = False
    app._translation_cancel_event = None
    app.detector = SimpleNamespace(
        current_playback=PlaybackInfo(
            state=PlayerState.PLAYING,
            position_ms=32000,
            duration_ms=238000,
        ),
        get_interpolated_position_ms=lambda: 32500,
    )
    return app


def make_lyrics():
    return LyricsData(
        lines=[LyricLine(1000, "When you were here before")],
        artist="Radiohead",
        title="Creep",
        is_synced=True,
    )


def test_save_from_manager_invalidates_translation_and_refreshes_current_track():
    app = make_app()
    request = LyricsSaveRequest(
        artist="Radiohead",
        title="Creep",
        album="Pablo Honey",
        duration_ms=238000,
        lyrics_data=make_lyrics(),
    )

    app._on_manager_save_requested(request)

    assert len(app.lyrics_service.saved) == 1
    assert app.translation_service.invalidated == [("Radiohead", "Creep")]
    assert app.lyrics_manager.saved_success == [("Radiohead", "Creep")]
    assert app.sync_engine.loaded[0][1] == 238000
    assert app.overlay.loaded[0][0].lines[0].text == (
        "When you were here before"
    )


def test_apply_remote_candidate_caches_and_activates_current_track():
    app = make_app()
    match = LyricsCandidate(
        provider="LRCLIB",
        provider_id="1",
        artist="Radiohead",
        title="Creep",
        duration_ms=238000,
        lyrics_data=make_lyrics(),
    )

    app._on_manager_apply_requested(match)

    assert len(app.lyrics_service.cache.saved) == 1
    assert app.sync_engine.loaded[0][1] == 238000
    assert app.overlay.offsets == [0]
    assert app.tray.errors == []


def test_capture_uses_interpolated_qobuz_position():
    app = make_app()

    app._on_manager_capture_requested(2)

    assert app.lyrics_manager.captured == [(2, 32500)]
