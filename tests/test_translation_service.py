import json
import threading

from src.lrc_parser import LyricLine, LyricsData
from src.translation_service import (
    TranslationCache,
    TranslationService,
    _get_translatable_lines,
    _resolve_translation_direction,
    _detect_language,
    is_translation_enabled_by_default,
)


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


def test_translation_helpers_apply_the_same_override_and_line_filtering():
    lyrics = LyricsData(
        lines=[
            LyricLine(1000, "Hello world"),
            LyricLine(2000, "[Instrumental]"),
            LyricLine(3000, "   "),
        ]
    )

    assert _resolve_translation_direction(lyrics, "es") == ("en", "es")
    assert _resolve_translation_direction(lyrics, "en") == ("es", "en")
    assert [idx for idx, _ in _get_translatable_lines(lyrics)] == [0]


def test_translation_is_enabled_by_default_only_for_english_lyrics():
    english = LyricsData(
        lines=[
            LyricLine(1000, "You are the one I want"),
            LyricLine(2000, "Come with me and stay here"),
        ]
    )
    spanish = LyricsData(
        lines=[
            LyricLine(1000, "Yo quiero estar contigo"),
            LyricLine(2000, "Ven y quédate aquí"),
        ]
    )
    italian = LyricsData(
        lines=[
            LyricLine(1000, "Il mio amore è per te"),
            LyricLine(2000, "Sono qui con il cuore"),
            LyricLine(3000, "Vivo questa notte con te"),
        ]
    )

    assert is_translation_enabled_by_default(english) is True
    assert is_translation_enabled_by_default(spanish) is False
    assert is_translation_enabled_by_default(italian) is True
    assert _detect_language("Il mio amore è per te") == ("it", "es")
    assert _detect_language("Quando sono con te, amore mio") == ("it", "es")
