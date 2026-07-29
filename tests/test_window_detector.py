import json
import unittest
from datetime import datetime
from unittest.mock import patch

from src.models import PlayerState, PlaybackInfo, TrackInfo
from src.window_detector import WindowTitleDetector


class WindowTitleDetectorTests(unittest.TestCase):
    def setUp(self):
        with patch("src.window_detector.ctypes.windll"):
            self.detector = WindowTitleDetector()

    def test_only_accepts_window_owned_by_qobuz(self):
        windows = [
            (10, "Proyecto - Visual Studio Code"),
            (20, "Stairway to Heaven (Remaster) - Led Zeppelin"),
            (30, "Consumo - Falabella"),
        ]
        process_names = {
            10: "code.exe",
            20: "qobuz.exe",
            30: "chrome.exe",
        }

        with (
            patch.object(
                self.detector, "_enumerate_visible_windows", return_value=windows
            ),
            patch.object(
                self.detector,
                "_get_window_process_name",
                side_effect=process_names.get,
            ),
        ):
            title = self.detector._get_qobuz_window_title()

        self.assertEqual(
            title, "Stairway to Heaven (Remaster) - Led Zeppelin"
        )

    def test_does_not_use_unrelated_hyphenated_windows(self):
        with (
            patch.object(
                self.detector,
                "_enumerate_visible_windows",
                return_value=[(10, "Consumo - Falabella")],
            ),
            patch.object(
                self.detector,
                "_get_window_process_name",
                return_value="chrome.exe",
            ),
        ):
            self.assertIsNone(self.detector._get_qobuz_window_title())

    def test_parses_artist_from_last_separator(self):
        track = self.detector._parse_window_title("Song - Live - Artist")

        self.assertEqual(track.title, "Song - Live")
        self.assertEqual(track.artist, "Artist")


def _write_position(path, position_ms, timestamp_ms):
    path.write_text(
        json.dumps(
            {
                "player": {
                    "data": {
                        "position": {
                            "value": position_ms,
                            "timestamp": timestamp_ms,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_qobuz_state_seek_updates_real_position_and_notifies(tmp_path):
    state_path = tmp_path / "player-0.json"
    timestamp_ms = int(datetime.now().timestamp() * 1000)
    _write_position(state_path, 11000, timestamp_ms)

    with patch("src.window_detector.ctypes.windll"):
        detector = WindowTitleDetector(
            poll_interval=0.1, qobuz_state_path=state_path
        )
    detector._current_track = TrackInfo(title="Song", artist="Artist")
    detector._current_playback = PlaybackInfo(
        state=PlayerState.PLAYING,
        position_ms=21000,
    )
    detector._is_playing = True
    detector._paused_position_ms = 21000
    detector._playback_start_time = datetime.now()
    seeks = []
    detector.on_seeked(seeks.append)

    detector._update_position_from_qobuz_state()

    assert len(seeks) == 1
    assert abs(seeks[0] - 11000) < 100
    assert abs(detector.get_interpolated_position_ms() - 11000) < 100


def test_qobuz_state_does_not_repeat_same_seek(tmp_path):
    state_path = tmp_path / "player-0.json"
    timestamp_ms = int(datetime.now().timestamp() * 1000)
    _write_position(state_path, 45000, timestamp_ms)

    with patch("src.window_detector.ctypes.windll"):
        detector = WindowTitleDetector(qobuz_state_path=state_path)
    detector._current_track = TrackInfo(title="Song", artist="Artist")
    detector._is_playing = True
    seeks = []
    detector.on_seeked(seeks.append)

    detector._update_position_from_qobuz_state()
    detector._update_position_from_qobuz_state()

    assert len(seeks) == 1
    assert abs(seeks[0] - 45000) < 100
