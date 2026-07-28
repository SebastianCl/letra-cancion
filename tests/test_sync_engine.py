from src.lrc_parser import LRCParser
from src.sync_engine import SyncEngine


class FakeDetector:
    def __init__(self):
        self.position_ms = 1000
        self.is_playing = True

    def get_interpolated_position_ms(self):
        return self.position_ms


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

