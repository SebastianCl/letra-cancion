import unittest
from unittest.mock import sentinel

from src.lyrics_service import LRCLIBProvider, NetEaseProvider


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


if __name__ == "__main__":
    unittest.main()
