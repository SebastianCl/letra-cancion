import asyncio
import threading
from types import SimpleNamespace

from src.lrc_parser import LyricLine, LyricsData
from src.main import LetraCancionApp
from src.models import TrackInfo


class PendingTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


class CancelEvent:
    def __init__(self):
        self.was_set = False

    def set(self):
        self.was_set = True


class OverlayStub:
    def set_lyrics(self, lyrics, duration_ms=0):
        pass

    def set_track_info(self, artist, title):
        pass

    def set_searching_lyrics(self):
        pass

    def set_translation_enabled(self, enabled):
        self.translation_enabled = enabled


def test_track_change_cancels_previous_lyrics_fetch(monkeypatch):
    app = LetraCancionApp.__new__(LetraCancionApp)
    previous = PendingTask()
    scheduled = PendingTask()
    app._lyrics_fetch_task = previous
    app._translation_cancel_event = None
    app.lyrics_manager = None
    app.sync_engine = SimpleNamespace(clear_lyrics=lambda: None)
    app.overlay = OverlayStub()
    app.tray = SimpleNamespace(
        update_track_info=lambda artist, title: None,
        clear_track_info=lambda: None,
    )

    async def fake_fetch(track):
        return track

    def fake_create_task(coroutine):
        coroutine.close()
        return scheduled

    app._fetch_lyrics = fake_fetch
    monkeypatch.setattr("src.main.asyncio.create_task", fake_create_task)

    app._on_track_changed(TrackInfo(title="New song", artist="Artist"))

    assert previous.cancelled is True
    assert app._lyrics_fetch_task is scheduled


def test_new_lyrics_cancel_previous_translation_task(monkeypatch):
    app = LetraCancionApp.__new__(LetraCancionApp)
    previous = PendingTask()
    scheduled = PendingTask()
    cancel_event = CancelEvent()
    app._translation_task = previous
    app._translation_cancel_event = cancel_event
    app._translation_enabled = True
    app.translation_service = object()
    app.settings_manager = SimpleNamespace(
        settings=SimpleNamespace(translation_enabled=True)
    )
    app.sync_engine = SimpleNamespace(set_lyrics=lambda lyrics, duration: None)
    app.overlay = OverlayStub()
    app.tray = SimpleNamespace(
        show_lyrics_found=lambda provider: None,
        set_translation_enabled=lambda enabled: None,
    )
    app._current_track = TrackInfo(title="Song", artist="Artist")

    async def fake_translate(track, lyrics, duration):
        return None

    def fake_create_task(coroutine):
        coroutine.close()
        return scheduled

    app._translate_active_lyrics = fake_translate
    monkeypatch.setattr("src.main.asyncio.create_task", fake_create_task)
    lyrics = LyricsData(
        lines=[LyricLine(1000, "You are the one I want")],
        title="Song",
        artist="Artist",
    )

    app._activate_lyrics(app._current_track, lyrics)

    assert cancel_event.was_set is True
    assert previous.cancelled is True
    assert app._translation_task is scheduled


def test_enabling_translation_manually_starts_translation_for_active_lyrics(
    monkeypatch,
):
    app = LetraCancionApp.__new__(LetraCancionApp)
    scheduled = PendingTask()
    lyrics = LyricsData(
        lines=[LyricLine(1000, "You are the one I want")],
        title="Song",
        artist="Artist",
    )
    app._translation_enabled = False
    app._translation_task = None
    app._current_track = TrackInfo(title="Song", artist="Artist")
    app.translation_service = object()
    app.sync_engine = SimpleNamespace(lyrics=lyrics)
    app.overlay = SimpleNamespace(
        toggle_translation=lambda: True,
        _duration_ms=120000,
    )
    app.tray = SimpleNamespace(set_translation_enabled=lambda enabled: None)
    app.settings_manager = SimpleNamespace(
        settings=SimpleNamespace(translation_enabled=False),
        save=lambda: None,
    )

    async def fake_translate(track, active_lyrics, duration):
        return None

    def fake_create_task(coroutine):
        coroutine.close()
        return scheduled

    app._translate_active_lyrics = fake_translate
    monkeypatch.setattr("src.main.asyncio.create_task", fake_create_task)

    app._toggle_translation()

    assert app._translation_enabled is True
    assert app._translation_task is scheduled


def test_manager_search_replaces_its_previous_task(monkeypatch):
    app = LetraCancionApp.__new__(LetraCancionApp)
    previous = PendingTask()
    scheduled = PendingTask()
    app._manager_search_task = previous

    async def fake_search(artist, title):
        return artist, title

    def fake_create_task(coroutine):
        coroutine.close()
        return scheduled

    app._search_manager_candidates = fake_search
    monkeypatch.setattr("src.main.asyncio.create_task", fake_create_task)

    app._on_manager_search_requested("Artist", "Song")

    assert previous.cancelled is True
    assert app._manager_search_task is scheduled


def test_cancel_pending_tasks_stops_every_owned_async_task():
    async def scenario():
        app = LetraCancionApp.__new__(LetraCancionApp)
        app._translation_cancel_event = threading.Event()
        tasks = [
            asyncio.create_task(asyncio.Event().wait())
            for _ in range(5)
        ]
        (
            app._lyrics_fetch_task,
            app._translation_task,
            app._manager_search_task,
            app._manager_preview_task,
            app._detector_task,
        ) = tasks

        cancelled = app._cancel_pending_tasks()
        await asyncio.gather(*cancelled, return_exceptions=True)

        assert app._translation_cancel_event.is_set()
        assert cancelled == tasks
        assert all(task.cancelled() for task in tasks)

    asyncio.run(scenario())


def test_quit_is_cancelled_when_editor_has_unsaved_changes():
    app = LetraCancionApp.__new__(LetraCancionApp)
    app._running = True
    app.lyrics_manager = SimpleNamespace(
        confirm_application_exit=lambda: False
    )

    app._quit()

    assert app._running is True
