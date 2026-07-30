import json
import threading

from src.lrc_parser import LyricLine, LyricsData
from src.translation_service import TranslationCache, TranslationService


class FailingTranslator:
    source = "en"
    target = "es"

    def translate_batch(self, texts):
        raise RuntimeError("network unavailable")

    def translate(self, text):
        raise RuntimeError("network unavailable")


def test_progressive_translation_does_not_cache_original_text_as_success(
    tmp_path,
):
    service = TranslationService(tmp_path)
    service._translator = FailingTranslator()
    lyrics = LyricsData(
        lines=[LyricLine(1000, "Hello world")],
        artist="Artist",
        title="Song",
    )
    callbacks = []

    result = service.translate_lyrics_progressive(
        lyrics,
        lambda *args: callbacks.append(args),
        threading.Event(),
        target_lang="es",
    )

    assert result == {}
    assert callbacks == []
    assert list(tmp_path.glob("*.json")) == []


def test_translation_cache_rejects_malformed_translation_values(tmp_path):
    cache = TranslationCache(tmp_path)
    path = cache._get_cache_path("Artist", "Song", "es")
    path.write_text(
        json.dumps({"translations": {"1000": 42}}),
        encoding="utf-8",
    )

    assert cache.get("Artist", "Song", "es") is None


def test_translation_cache_rejects_unsafe_target_language_filename(tmp_path):
    cache = TranslationCache(tmp_path)

    with __import__("pytest").raises(ValueError, match="Idioma destino"):
        cache._get_cache_path("Artist", "Song", "..\\outside")
