import pytest

from src.lrc_parser import LRCParser


def test_one_digit_fraction_represents_tenths_of_a_second():
    lyrics = LRCParser.parse("[00:01.5]Half second")

    assert lyrics.lines[0].timestamp_ms == 1500


def test_timestamp_rejects_seconds_outside_valid_range():
    lyrics = LRCParser.parse(
        "[00:60.00]Invalid timestamp\n[01:00.00]Valid timestamp"
    )

    assert [line.text for line in lyrics.lines] == ["Valid timestamp"]


def test_parser_rejects_excessively_large_untrusted_content():
    with pytest.raises(ValueError, match="demasiado grande"):
        LRCParser.parse("x" * (LRCParser.MAX_CONTENT_CHARS + 1))
