from pathlib import Path

import pytest

from src.storage import atomic_write_text, read_text_limited


def test_atomic_write_preserves_existing_file_when_replace_fails(
    tmp_path, monkeypatch
):
    target = tmp_path / "settings.json"
    target.write_text("previous", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr("src.storage.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob("*.tmp")) == []


def test_limited_reader_rejects_oversized_file_before_loading(tmp_path):
    path = tmp_path / "lyrics.lrc"
    path.write_text("x" * 1025, encoding="utf-8")

    with pytest.raises(ValueError, match="demasiado grande"):
        read_text_limited(path, max_bytes=1024)


def test_limited_reader_rejects_reparse_points(tmp_path, monkeypatch):
    path = tmp_path / "lyrics.lrc"
    path.write_text("safe", encoding="utf-8")
    monkeypatch.setattr("src.storage._is_reparse_point", lambda candidate: True)

    with pytest.raises(ValueError, match="enlace"):
        read_text_limited(path, max_bytes=1024)
