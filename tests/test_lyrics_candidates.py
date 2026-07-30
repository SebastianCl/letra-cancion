import asyncio

from src.lrc_parser import LyricLine, LyricsData
from src.lyrics_library import LyricsCandidate
from src.lyrics_service import LyricsService


class CandidateProvider:
    def __init__(self, candidates=None, error=None):
        self.candidates = candidates or []
        self.error = error

    async def search_candidates(self, artist, title, limit=10):
        if self.error:
            raise self.error
        return self.candidates[:limit]

    async def load_candidate(self, candidate):
        return candidate.lyrics_data


def candidate(provider, artist, title, synced=True):
    return LyricsCandidate(
        provider=provider,
        provider_id=f"{provider}:{artist}:{title}",
        artist=artist,
        title=title,
        album="Album",
        duration_ms=180000,
        is_synced=synced,
        lyrics_data=LyricsData(
            lines=[LyricLine(1000, "First line")],
            artist=artist,
            title=title,
            album="Album",
            is_synced=synced,
        ),
    )


def test_candidate_search_deduplicates_and_survives_partial_failure(tmp_path):
    service = LyricsService(tmp_path)
    lrclib = candidate("LRCLIB", "Radiohead", "Creep")
    duplicate = candidate("NetEase", "Radiohead", "Creep")
    service._providers = [
        ("LRCLIB", CandidateProvider([lrclib, duplicate])),
        ("NetEase", CandidateProvider(error=RuntimeError("offline"))),
    ]

    results = asyncio.run(service.search_candidates("Radiohead", "Creep"))

    assert len(results) == 1
    assert results[0].provider == "LRCLIB"


def test_local_candidate_is_ranked_before_remote_duplicate(tmp_path):
    service = LyricsService(tmp_path)
    lyrics = LyricsData(
        lines=[LyricLine(1500, "Local line")],
        artist="Queen",
        title="Somebody to Love",
        is_synced=True,
    )
    service.save_user_lyrics(
        "Queen", "Somebody to Love", lyrics, source="manual"
    )
    service._providers = [
        (
            "LRCLIB",
            CandidateProvider(
                [candidate("LRCLIB", "Queen", "Somebody to Love")]
            ),
        )
    ]

    results = asyncio.run(
        service.search_candidates("Queen", "Somebody to Love")
    )

    assert len(results) == 1
    assert results[0].is_local is True
    assert results[0].lyrics_data.lines[0].text == "Local line"


def test_load_candidate_returns_independent_copy(tmp_path):
    service = LyricsService(tmp_path)
    match = candidate("LRCLIB", "Artist", "Song")

    loaded = asyncio.run(service.load_candidate(match))
    loaded.lines[0].text = "Changed"

    assert match.lyrics_data.lines[0].text == "First line"
