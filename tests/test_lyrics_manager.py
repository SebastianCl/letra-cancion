import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from src.lrc_parser import LyricLine, LyricsData
from src.lyrics_library import LyricsCandidate
from src.models import TrackInfo
from src.ui.lyrics_manager import (
    LyricsManagerDialog,
    format_timestamp,
    parse_timestamp,
)


def make_candidate(is_local=False):
    lyrics = LyricsData(
        lines=[
            LyricLine(5000, "First line"),
            LyricLine(9000, "Second line"),
        ],
        artist="Radiohead",
        title="Creep",
        album="Pablo Honey",
        is_synced=True,
    )
    return LyricsCandidate(
        provider="LRCLIB",
        provider_id="123",
        artist="Radiohead",
        title="Creep",
        album="Pablo Honey",
        duration_ms=238000,
        is_synced=True,
        is_local=is_local,
        lyrics_data=lyrics,
    )


def test_timestamp_format_and_parse():
    assert format_timestamp(75430) == "01:15.43"
    assert parse_timestamp("01:15.43") == 75430
    assert parse_timestamp("1:15.4") == 75400
    assert parse_timestamp("01:61.00") is None
    assert parse_timestamp("invalid") is None


def test_search_preview_and_apply_are_gated_by_current_track(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    match = make_candidate()

    with qtbot.waitSignal(dialog.preview_requested, timeout=1000):
        dialog.set_search_results([match])
    dialog.set_preview(match, match.lyrics_data)

    assert dialog.preview_text.toPlainText().startswith("[ti:Creep]")
    assert dialog.apply_button.isEnabled() is False

    dialog.set_current_track(TrackInfo(title="Creep", artist="Radiohead"))

    assert dialog.apply_button.isEnabled() is True
    with qtbot.waitSignal(dialog.apply_requested, timeout=1000) as signal:
        qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert signal.args[0] is match


def test_editor_sections_can_be_resized_vertically(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tabs.setCurrentIndex(1)
    splitter = dialog.editor_sections_splitter

    qtbot.waitUntil(lambda: splitter.height() > 0)

    assert splitter.orientation() == Qt.Orientation.Vertical
    assert splitter.count() == 3
    assert splitter.widget(0) is dialog.editor_metadata_group
    assert splitter.widget(1) is dialog.editor_import_group
    assert splitter.widget(2) is dialog.editor_time_section
    assert all(splitter.isCollapsible(index) for index in range(3))
    assert dialog.editor_time_section.isAncestorOf(dialog.lines_table)
    assert dialog.editor_time_section.isAncestorOf(dialog.add_row_button)
    assert dialog.editor_time_section.isAncestorOf(dialog.save_editor_button)

    before = splitter.sizes()
    splitter.setSizes([before[0], before[1] + 30, max(1, before[2] - 30)])
    after = splitter.sizes()

    assert after[1] > before[1]
    assert after[2] < before[2]

    splitter.setSizes([0, after[1], after[2]])
    assert splitter.sizes()[0] == 0

    splitter.setSizes(before)
    assert splitter.sizes()[0] > 0


def test_process_plain_text_and_capture_advances_row(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.set_current_track(TrackInfo(title="Halo", artist="Beyoncé"))
    dialog.start_new_entry()
    dialog.raw_lyrics_edit.setPlainText("First line\nSecond line\nThird line")

    qtbot.mouseClick(
        dialog.process_text_button, Qt.MouseButton.LeftButton
    )

    assert dialog.lines_table.rowCount() == 3
    assert dialog.synced_check.isChecked() is False
    assert dialog.capture_button.isEnabled() is True

    dialog.lines_table.selectRow(0)
    with qtbot.waitSignal(dialog.capture_requested, timeout=1000) as signal:
        qtbot.mouseClick(dialog.capture_button, Qt.MouseButton.LeftButton)
    assert signal.args == [0]

    dialog.set_captured_timestamp(0, 12340)
    assert dialog.lines_table.item(0, 0).text() == "00:12.34"
    assert dialog.lines_table.currentRow() == 1
    assert dialog.synced_check.isChecked() is True


def test_lrc_import_path_populates_editor_and_builds_request(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.editor_artist_edit.setText("Queen")
    dialog.editor_title_edit.setText("Somebody to Love")
    dialog.raw_lyrics_edit.setPlainText(
        "[00:03.00]Can anybody find me\n"
        "[00:08.50]Somebody to love"
    )

    dialog._process_raw_text()
    request = dialog._build_save_request()

    assert request.artist == "Queen"
    assert request.lyrics_data.is_synced is True
    assert [line.timestamp_ms for line in request.lyrics_data.lines] == [
        3000,
        8500,
    ]


def test_synced_editor_requires_strictly_increasing_times(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.load_editor(
        LyricsData(
            lines=[
                LyricLine(5000, "First"),
                LyricLine(5000, "Second"),
            ],
            artist="Artist",
            title="Song",
            is_synced=True,
        )
    )

    with pytest.raises(ValueError, match="estrictamente crecientes"):
        dialog._build_save_request()


def test_delete_is_available_only_for_local_candidate(qtbot, monkeypatch):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    remote = make_candidate()
    dialog.set_search_results([remote])
    dialog.set_preview(remote, remote.lyrics_data)

    assert dialog.delete_button.isEnabled() is False

    local = make_candidate(is_local=True)
    dialog.set_search_results([local])
    dialog.set_preview(local, local.lyrics_data)
    monkeypatch.setattr(
        "src.ui.lyrics_manager.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    with qtbot.waitSignal(dialog.delete_requested, timeout=1000) as signal:
        qtbot.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)
    assert signal.args[0] is local

    dialog.remove_candidate(local)
    assert dialog.results_list.count() == 0
    assert dialog.delete_button.isEnabled() is False


def test_unsaved_editor_is_not_replaced_without_confirmation(
    qtbot, monkeypatch
):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.load_editor(
        LyricsData(
            lines=[LyricLine(1000, "Draft line")],
            artist="Draft artist",
            title="Draft title",
        )
    )
    dialog.editor_artist_edit.setFocus()
    dialog.editor_artist_edit.selectAll()
    qtbot.keyClicks(dialog.editor_artist_edit, "Changed artist")

    assert dialog._editor_dirty is True
    monkeypatch.setattr(
        "src.ui.lyrics_manager.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    replaced = dialog.load_editor(
        LyricsData(
            lines=[LyricLine(2000, "Replacement")],
            artist="Other artist",
            title="Other title",
        )
    )

    assert replaced is False
    assert dialog.editor_artist_edit.text() == "Changed artist"
    assert dialog.lines_table.item(0, 1).text() == "Draft line"

    monkeypatch.setattr(
        "src.ui.lyrics_manager.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    replaced = dialog.load_editor(
        LyricsData(
            lines=[LyricLine(2000, "Replacement")],
            artist="Other artist",
            title="Other title",
        )
    )

    assert replaced is True
    assert dialog.editor_artist_edit.text() == "Other artist"
    assert dialog._editor_dirty is False


def test_search_controls_expose_accessible_context_and_focus_errors(qtbot):
    dialog = LyricsManagerDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    qtbot.mouseClick(dialog.search_button, Qt.MouseButton.LeftButton)

    assert dialog.search_status_label.text() == (
        "El artista y el título son obligatorios."
    )
    assert dialog.focusWidget() is dialog.search_artist_edit
    assert dialog.results_list.accessibleName() == "Resultados de búsqueda"
    assert dialog.lines_table.accessibleName() == "Líneas de la letra"
    assert dialog.close_button.accessibleDescription() == (
        "Oculta el gestor y conserva el borrador actual."
    )
