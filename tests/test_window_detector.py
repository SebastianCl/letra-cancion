import unittest
from unittest.mock import patch

from src.window_detector import WindowTitleDetector


class WindowTitleDetectorTests(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
