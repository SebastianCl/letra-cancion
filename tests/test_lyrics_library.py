import asyncio
import json

import pytest

from src.lrc_parser import LyricLine, LyricsData
from src.lyrics_library import (
    LIBRARY_SCHEMA_VERSION,
    UserLyricsEntry,
    UserLyricsLibrary,
    make_track_key,
)
from src.lyrics_service import LyricsService


def make_entry(is_synced: bool = True) -> UserLyricsEntry:
    return UserLyricsEntry(
        artist="Beyoncé",
        title="Halo",
        album="I Am... Sasha Fierce",
        duration_ms=261000,
        source="manual",
        lyrics_data=LyricsData(
            lines=[
                LyricLine(1200, "Remember those walls I built"),
                LyricLine(5400, "Well, baby, they're tumbling down"),
            ],
            artist="Beyoncé",
            title="Halo",
            album="I Am... Sasha Fierce",
            is_synced=is_synced,
        ),
    )


@pytest.mark.parametrize("is_synced", [True, False])
def test_library_round_trip_preserves_sync_state(tmp_path, is_synced):
    library = UserLyricsLibrary(tmp_path / "library")
    saved = library.save(make_entry(is_synced))

    loaded = library.get("Beyonce", "Halo")

    assert saved.key == make_track_key("Beyoncé", "Halo")
    assert loaded is not None
    assert loaded.artist == "Beyoncé"
    assert loaded.lyrics_data.is_synced is is_synced
    assert [line.timestamp_ms for line in loaded.lyrics_data.lines] == [
        1200,
        5400,
    ]
    assert not list((tmp_path / "library").glob("*.tmp"))


def test_library_ignores_corrupt_or_unknown_entries(tmp_path):
    library_dir = tmp_path / "library"
    library = UserLyricsLibrary(library_dir)
    (library_dir / "broken.json").write_text("{", encoding="utf-8")
    (library_dir / "future.json").write_text(
        json.dumps(
            {
                "schema_version": LIBRARY_SCHEMA_VERSION + 1,
                "artist": "Artist",
                "title": "Song",
                "lyrics": {"lines": []},
            }
        ),
        encoding="utf-8",
    )

    assert library.all_entries() == []


def test_library_rejects_non_canonical_types_in_untrusted_json(tmp_path):
    library = UserLyricsLibrary(tmp_path)
    path = library._path_for("Artist", "Song")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artist": "Artist",
                "title": "Song",
                "duration_ms": "123000",
                "lyrics": {
                    "is_synced": "yes",
                    "offset_ms": "0",
                    "lines": [{"timestamp_ms": "1000", "text": "Line"}],
                },
            }
        ),
        encoding="utf-8",
    )

    assert library.get("Artist", "Song") is None


def test_library_metadata_cannot_escape_hashed_storage_path(tmp_path):
    library = UserLyricsLibrary(tmp_path)

    path = library._path_for("..\\outside", r"C:\escape")

    assert path.parent == tmp_path
    assert path.suffix == ".json"


def test_library_finds_small_metadata_variants(tmp_path):
    library = UserLyricsLibrary(tmp_path / "library")
    library.save(make_entry())

    loaded = library.get("Beyonce", "Halo (Remastered)")

    assert loaded is not None
    assert loaded.title == "Halo"


def test_library_deletes_only_exact_local_entry(tmp_path):
    library = UserLyricsLibrary(tmp_path / "library")
    library.save(make_entry())

    assert library.delete("Beyonce", "Halo (Remastered)") is False
    assert library.get("Beyoncé", "Halo") is not None
    assert library.delete("Beyoncé", "Halo") is True
    assert library.get("Beyoncé", "Halo") is None
    assert library.delete("Beyoncé", "Halo") is False


def test_local_library_survives_service_restart(tmp_path):
    service = LyricsService(tmp_path)
    entry = make_entry()
    service.save_user_lyrics(
        artist=entry.artist,
        title=entry.title,
        album=entry.album,
        duration_ms=entry.duration_ms,
        lyrics_data=entry.lyrics_data,
    )
    restarted = LyricsService(tmp_path)

    assert restarted.library.get(entry.artist, entry.title) is not None


def test_service_deletes_local_entry(tmp_path):
    service = LyricsService(tmp_path)
    entry = make_entry()
    service.save_user_lyrics(
        artist=entry.artist,
        title=entry.title,
        album=entry.album,
        duration_ms=entry.duration_ms,
        lyrics_data=entry.lyrics_data,
    )
    assert service.delete_user_lyrics(entry.artist, entry.title) is True
    assert service.library.get(entry.artist, entry.title) is None


def test_automatic_search_prioritizes_local_library(tmp_path):
    service = LyricsService(tmp_path)
    entry = make_entry()
    service.save_user_lyrics(
        artist=entry.artist,
        title=entry.title,
        album=entry.album,
        duration_ms=entry.duration_ms,
        lyrics_data=entry.lyrics_data,
    )

    result = asyncio.run(service.search("Beyonce", "Halo"))

    assert result is not None
    assert result.provider == "Biblioteca local"
    assert result.local is True
    assert result.lyrics_data.lines[0].text == "Remember those walls I built"


def test_service_lists_personal_and_downloaded_lyrics(tmp_path):
    service = LyricsService(tmp_path)
    entry = make_entry()
    service.save_user_lyrics(
        artist=entry.artist,
        title=entry.title,
        album=entry.album,
        duration_ms=entry.duration_ms,
        lyrics_data=entry.lyrics_data,
    )
    service.save_user_lyrics(
        "Radiohead",
        "Creep",
        LyricsData(
            lines=[LyricLine(1000, "Where were you?")],
            artist="Radiohead",
            title="Creep",
            is_synced=True,
        ),
        source="LRCLIB",
    )

    candidates = service.list_local_candidates()

    assert {(candidate.artist, candidate.title) for candidate in candidates} == {
        ("Beyoncé", "Halo"),
        ("Radiohead", "Creep"),
    }
    assert all(candidate.lyrics_data is not None for candidate in candidates)
