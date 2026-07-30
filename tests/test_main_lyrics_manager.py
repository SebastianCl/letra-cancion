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
        self.deleted = []

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

    def delete_user_lyrics(self, artist, title):
        self.deleted.append((artist, title))
        return True


class FakeManager:
    def __init__(self):
        self.saved_success = []
        self.captured = []
        self.removed = []

    def show_save_success(self, artist, title):
        self.saved_success.append((artist, title))

    def set_captured_timestamp(self, row, timestamp_ms):
        self.captured.append((row, timestamp_ms))

    def remove_candidate(self, candidate):
        self.removed.append(candidate)


class FakeTranslationService:
    def __init__(self):
        self.invalidated = []

    def invalidate_track(self, artist, title):
        self.invalidated.append((artist, title))


class FakeSyncEngine:
    def __init__(self):
        self.loaded = []
        self.cleared = 0

    def set_lyrics(self, lyrics, duration_ms):
        self.loaded.append((lyrics, duration_ms))

    def clear_lyrics(self):
        self.cleared += 1


class FakeOverlay:
    def __init__(self):
        self.loaded = []
        self.offsets = []
        self.searching = []

    def set_lyrics(self, lyrics, duration_ms):
        self.loaded.append((lyrics, duration_ms))

    def show_offset_indicator(self, offset_ms):
        self.offsets.append(offset_ms)

    def set_searching_lyrics(self, source=""):
        self.searching.append(source)


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


def test_delete_current_local_lyrics_refreshes_from_providers(monkeypatch):
    app = make_app()
    candidate = LyricsCandidate(
        provider="Biblioteca local",
        provider_id="radiohead-creep",
        artist="Radiohead",
        title="Creep",
        is_local=True,
        lyrics_data=make_lyrics(),
    )
    scheduled = []

    async def fake_fetch(track):
        return track

    def fake_create_task(coroutine):
        scheduled.append(coroutine)
        coroutine.close()
        return SimpleNamespace()

    app._fetch_lyrics = fake_fetch
    monkeypatch.setattr("src.main.asyncio.create_task", fake_create_task)

    app._on_manager_delete_requested(candidate)

    assert app.lyrics_service.deleted == [("Radiohead", "Creep")]
    assert app.translation_service.invalidated == [("Radiohead", "Creep")]
    assert app.lyrics_manager.removed == [candidate]
    assert app.sync_engine.cleared == 1
    assert app.overlay.searching == ["proveedores"]
    assert len(scheduled) == 1
