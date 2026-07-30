import asyncio
import unittest
from unittest.mock import sentinel

from src.lyrics_service import (
    LRCLIBProvider,
    LyricsCache,
    LyricsService,
    NetEaseProvider,
    _metadata_matches,
    _track_matches,
)
from src.lrc_parser import LRCParser


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.json_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, **kwargs):
        self.json_calls.append(kwargs)
        return self.payload


class FakeSession:
    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_response


class FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class StreamingResponse(FakeResponse):
    def __init__(self, chunks):
        super().__init__(payload=None)
        self.headers = {}
        self.content = FakeContent(chunks)


class LyricsProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_lrclib_uses_explicit_verified_ssl_context(self):
        response = FakeResponse(
            {
                "trackName": "Stairway to Heaven",
                "artistName": "Led Zeppelin",
                "albumName": "Led Zeppelin IV",
                "duration": 482,
                "syncedLyrics": "[00:52.00]There's a lady who's sure",
                "plainLyrics": "There's a lady who's sure",
            }
        )
        session = FakeSession(get_response=response)
        provider = LRCLIBProvider(session, ssl_context=sentinel.ssl_context)

        lyrics = await provider.search(
            artist="Led Zeppelin",
            title="Stairway to Heaven",
            album="Led Zeppelin IV",
            duration_seconds=482,
        )

        self.assertTrue(lyrics.is_synced)
        self.assertEqual(session.get_calls[0][1]["ssl"], sentinel.ssl_context)

    async def test_netease_accepts_json_with_text_plain_content_type(self):
        search_response = FakeResponse(
            {
                "result": {
                    "songs": [
                        {
                            "id": 123,
                            "name": "Stairway to Heaven (Remaster)",
                            "artists": [{"name": "Led Zeppelin"}],
                        }
                    ]
                }
            }
        )
        lyrics_response = FakeResponse(
            {
                "lrc": {
                    "lyric": "[00:52.00]There's a lady who's sure\n"
                    "[00:58.00]All that glitters is gold"
                }
            }
        )
        session = FakeSession(
            get_response=lyrics_response,
            post_response=search_response,
        )
        provider = NetEaseProvider(session)

        lyrics = await provider.search(
            artist="Led Zeppelin",
            title="Stairway to Heaven (Remaster)",
        )

        self.assertTrue(lyrics.is_synced)
        self.assertEqual(len(lyrics.lines), 2)
        self.assertEqual(search_response.json_calls, [{"content_type": None}])
        self.assertEqual(lyrics_response.json_calls, [{"content_type": None}])

    async def test_netease_rejects_unrelated_first_result(self):
        search_response = FakeResponse(
            {
                "result": {
                    "songs": [
                        {
                            "id": 456,
                            "name": "晴天",
                            "artists": [{"name": "周杰伦"}],
                        }
                    ]
                }
            }
        )
        session = FakeSession(post_response=search_response)
        provider = NetEaseProvider(session)

        lyrics = await provider.search(artist="Radiohead", title="Creep")

        self.assertIsNone(lyrics)
        self.assertEqual(session.get_calls, [])

    async def test_lrclib_lists_candidates_for_manual_search(self):
        response = FakeResponse(
            [
                {
                    "id": 42,
                    "trackName": "Creep",
                    "artistName": "Radiohead",
                    "albumName": "Pablo Honey",
                    "duration": 238,
                    "syncedLyrics": "[00:01.00]When you were here before",
                    "plainLyrics": "When you were here before",
                }
            ]
        )
        session = FakeSession(get_response=response)
        provider = LRCLIBProvider(
            session, ssl_context=sentinel.ssl_context
        )

        candidates = await provider.search_candidates("Radiohead", "Creep")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider_id, "42")
        self.assertEqual(candidates[0].duration_ms, 238000)
        self.assertTrue(candidates[0].is_synced)
        self.assertEqual(
            session.get_calls[0][1]["ssl"], sentinel.ssl_context
        )

    async def test_netease_lists_candidates_without_fetching_each_lyric(self):
        response = FakeResponse(
            {
                "result": {
                    "songs": [
                        {
                            "id": 123,
                            "name": "Creep",
                            "artists": [{"name": "Radiohead"}],
                            "album": {"name": "Pablo Honey"},
                            "duration": 238000,
                        }
                    ]
                }
            }
        )
        session = FakeSession(post_response=response)
        provider = NetEaseProvider(session)

        candidates = await provider.search_candidates("Radiohead", "Creep")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider_id, "123")
        self.assertIsNone(candidates[0].is_synced)
        self.assertEqual(session.get_calls, [])

    async def test_candidate_search_ignores_incomplete_api_payloads(self):
        lrclib = LRCLIBProvider(
            FakeSession(get_response=FakeResponse({"unexpected": "object"})),
            ssl_context=sentinel.ssl_context,
        )
        netease = NetEaseProvider(
            FakeSession(post_response=FakeResponse(["unexpected", "list"]))
        )

        self.assertEqual(
            await lrclib.search_candidates("Radiohead", "Creep"), []
        )
        self.assertEqual(
            await netease.search_candidates("Radiohead", "Creep"), []
        )

    async def test_provider_rejects_response_with_excessive_declared_size(self):
        response = FakeResponse([])
        response.headers = {"Content-Length": str(2 * 1024 * 1024 + 1)}
        provider = LRCLIBProvider(
            FakeSession(get_response=response), ssl_context=sentinel.ssl_context
        )

        candidates = await provider.search_candidates("Radiohead", "Creep")

        self.assertEqual(candidates, [])
        self.assertEqual(response.json_calls, [])

    async def test_provider_stops_streaming_response_over_size_limit(self):
        response = StreamingResponse([b"[" + b" " * (2 * 1024 * 1024)])
        provider = LRCLIBProvider(
            FakeSession(get_response=response), ssl_context=sentinel.ssl_context
        )

        candidates = await provider.search_candidates("Radiohead", "Creep")

        self.assertEqual(candidates, [])
        self.assertEqual(response.json_calls, [])


class MetadataMatchingTests(unittest.TestCase):
    def test_track_matches_normalized_metadata(self):
        self.assertTrue(
            _track_matches("Beyoncé", "Halo", "Beyonce", "Halo (Remastered)")
        )

    def test_track_rejects_unrelated_result(self):
        self.assertFalse(
            _track_matches("Radiohead", "Creep", "周杰伦", "晴天")
        )

    def test_metadata_rejects_missing_values(self):
        self.assertFalse(_metadata_matches("Creep", None))
        self.assertFalse(_metadata_matches("", "Creep"))


class LyricsCacheTests(unittest.TestCase):
    def test_plain_lyrics_remain_unsynced_after_cache_round_trip(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            cache = LyricsCache(Path(directory))
            lyrics = LRCParser.parse_plain_lyrics(
                "First line\nSecond line", duration_ms=20000
            )

            cache.save("Artist", "Song", lyrics)
            restored = cache.get("Artist", "Song")

        self.assertIsNotNone(restored)
        self.assertFalse(restored.is_synced)

    def test_save_completes_missing_metadata_for_offline_validation(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            cache = LyricsCache(Path(directory))
            lyrics = LRCParser.parse_plain_lyrics("First line", duration_ms=0)

            cache.save("Artist", "Song", lyrics)
            restored = cache.get("Artist", "Song")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.artist, "Artist")
        self.assertEqual(restored.title, "Song")

    def test_service_uses_local_library_when_providers_fail(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        class OfflineProvider:
            async def search(self, **kwargs):
                raise OSError("sin conexión")

        with TemporaryDirectory() as directory:
            service = LyricsService(Path(directory))
            lyrics = LRCParser.parse_plain_lyrics(
                "First line\nSecond line", duration_ms=20000
            )
            service.save_user_lyrics(
                "Artist", "Song", lyrics, source="LRCLIB"
            )
            service._providers = [("offline", OfflineProvider())]

            result = asyncio.run(service.search("Artist", "Song"))

        self.assertIsNotNone(result)
        self.assertFalse(result.cached)
        self.assertEqual(result.provider, "Biblioteca local")
        self.assertEqual(result.lyrics_data.lines[0].text, "First line")

    def test_metadata_cannot_escape_hashed_cache_directory(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            cache = LyricsCache(Path(directory))
            path = cache._get_cache_path("..\\outside", r"C:\escape", True)

        self.assertEqual(path.parent, cache.synced_dir)
        self.assertEqual(path.suffix, ".lrc")

    def test_lists_downloaded_lyrics_for_offline_library(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            cache = LyricsCache(Path(directory))
            lyrics = LRCParser.parse(
                "[ti:Song]\n[ar:Artist]\n[00:01.00]First line"
            )
            cache.save("Artist", "Song", lyrics)

            entries = cache.all_lyrics()

        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].artist, entries[0].title), ("Artist", "Song"))


if __name__ == "__main__":
    unittest.main()
