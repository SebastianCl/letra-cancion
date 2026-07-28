import unittest
from unittest.mock import AsyncMock, patch

from src.detector import MediaDetector
from src.models import TrackInfo


class FakeSessions:
    def __init__(self, sessions):
        self._sessions = sessions

    @property
    def size(self):
        return len(self._sessions)

    def get_at(self, index):
        return self._sessions[index]


class FakeSession:
    def __init__(self, source_id):
        self.source_app_user_model_id = source_id
        self.removed_tokens = []

    def add_media_properties_changed(self, callback):
        return "media-token"

    def add_playback_info_changed(self, callback):
        return "playback-token"

    def add_timeline_properties_changed(self, callback):
        return "timeline-token"

    def remove_media_properties_changed(self, token):
        self.removed_tokens.append(token)

    def remove_playback_info_changed(self, token):
        self.removed_tokens.append(token)

    def remove_timeline_properties_changed(self, token):
        self.removed_tokens.append(token)


class FakeManager:
    def __init__(self, sessions, current=None):
        self.sessions = FakeSessions(sessions)
        self.current = current
        self.removed_tokens = []

    def get_sessions(self):
        return self.sessions

    def get_current_session(self):
        return self.current

    def add_current_session_changed(self, callback):
        return "current-token"

    def add_sessions_changed(self, callback):
        return "sessions-token"

    def remove_current_session_changed(self, token):
        self.removed_tokens.append(token)

    def remove_sessions_changed(self, token):
        self.removed_tokens.append(token)


def media_manager_type(manager):
    class FakeMediaManagerType:
        @staticmethod
        async def request_async():
            return manager

    return FakeMediaManagerType


class MediaDetectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_fails_without_qobuz_session(self):
        other = FakeSession("Spotify.exe")
        manager = FakeManager([other], current=other)

        with (
            patch("src.detector.WINSDK_AVAILABLE", True),
            patch("src.detector.MediaManager", media_manager_type(manager)),
        ):
            detector = MediaDetector(target_app="Qobuz")
            self.assertFalse(await detector.initialize())
            self.assertIsNone(detector.current_track)
            await detector.close()

        self.assertEqual(
            manager.removed_tokens, ["current-token", "sessions-token"]
        )

    async def test_selects_qobuz_instead_of_unrelated_current_session(self):
        other = FakeSession("Spotify.exe")
        qobuz = FakeSession("Qobuz.exe")
        manager = FakeManager([other, qobuz], current=other)

        with (
            patch("src.detector.WINSDK_AVAILABLE", True),
            patch("src.detector.MediaManager", media_manager_type(manager)),
        ):
            detector = MediaDetector(target_app="Qobuz")
            detector._update_track_info = AsyncMock()
            detector._update_playback_info = AsyncMock()

            self.assertTrue(await detector.initialize())
            self.assertIs(detector._current_session, qobuz)
            detector._update_track_info.assert_awaited_once()
            detector._update_playback_info.assert_awaited_once()
            await detector.close()

        self.assertEqual(
            qobuz.removed_tokens,
            ["media-token", "playback-token", "timeline-token"],
        )

    async def test_session_removal_clears_current_track(self):
        qobuz = FakeSession("Qobuz.exe")
        manager = FakeManager([qobuz], current=qobuz)

        with (
            patch("src.detector.WINSDK_AVAILABLE", True),
            patch("src.detector.MediaManager", media_manager_type(manager)),
        ):
            detector = MediaDetector(target_app="Qobuz")
            detector._update_track_info = AsyncMock()
            detector._update_playback_info = AsyncMock()
            self.assertTrue(await detector.initialize())

            changes = []
            detector.on_track_changed(changes.append)
            detector._current_track = TrackInfo(title="Song", artist="Artist")
            manager.sessions = FakeSessions([])

            await detector._on_session_changed()

            self.assertIsNone(detector.current_track)
            self.assertEqual(changes, [None])
            await detector.close()


if __name__ == "__main__":
    unittest.main()
