from src.lrc_parser import LRCParser
from src.sync_engine import SyncEngine


class FakeDetector:
    def __init__(self):
        self.position_ms = 1000
        self.is_playing = True
        self.seek_callback = None

    def get_interpolated_position_ms(self):
        return self.position_ms

    def on_seeked(self, callback):
        self.seek_callback = callback

    def seek(self, position_ms):
        self.position_ms = position_ms
        self.seek_callback(position_ms)


def test_sync_engine_publishes_progress_when_line_does_not_change():
    detector = FakeDetector()
    engine = SyncEngine(detector)
    lyrics = LRCParser.parse(
        "[00:00.00]First line\n[00:10.00]Second line"
    )
    engine.set_lyrics(lyrics, duration_ms=20000)
    updates = []
    engine.on_sync_update(updates.append)

    engine._update_sync()
    detector.position_ms = 1250
    engine._update_sync()

    assert len(updates) == 2
    assert updates[0].current_line_index == updates[1].current_line_index == 0
    assert updates[1].position_ms == 1250


def test_seek_immediately_selects_exact_lyric_line_when_moving_back():
    detector = FakeDetector()
    engine = SyncEngine(detector)
    lyrics = LRCParser.parse(
        "[00:00.00]First line\n"
        "[00:10.00]Second line\n"
        "[00:20.00]Third line"
    )
    engine.set_lyrics(lyrics, duration_ms=30000)
    updates = []
    engine.on_sync_update(updates.append)

    detector.seek(21000)
    detector.seek(11000)

    assert updates[-1].position_ms == 11000
    assert updates[-1].current_line_index == 1
    assert updates[-1].current_line.text == "Second line"


def test_new_lyrics_reset_offset_when_track_has_no_saved_adjustment():
    detector = FakeDetector()
    engine = SyncEngine(detector)
    adjusted = LRCParser.parse("[offset:1500]\n[00:01.00]Adjusted")
    default = LRCParser.parse("[00:01.00]Default")

    engine.set_lyrics(adjusted)
    assert engine.offset_ms == 1500

    engine.set_lyrics(default)

    assert engine.offset_ms == 0

