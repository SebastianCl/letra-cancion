from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from src.lrc_parser import LRCParser
from src.models import PlaybackInfo, PlayerState
from src.sync_engine import SyncMode, SyncState
from src.ui import overlay as overlay_module
from src.ui.overlay import LyricsOverlay, OverlayConfig


def make_lyrics():
    lyrics = LRCParser.parse(
        "\n".join(
            (
                "[00:05.00]Wait a minute, honey",
                "[00:09.00]I don't think your joke's too funny, no",
                "[00:14.00]I stayed up all night",
                "[00:19.00]Checking out the doctor's guide",
                "[00:24.00]Wait a minute, honey",
            )
        )
    )
    translations = (
        "Espera un minuto, cariño",
        "No creo que tu broma sea muy divertida, no.",
        "Me quedé despierto toda la noche",
        "Revisando la guía del doctor",
        "Espera un minuto, cariño",
    )
    for line, translation in zip(lyrics.lines, translations):
        line.translation = translation
    return lyrics


def test_responsive_context_and_stacked_translation(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    qtbot.wait(1)
    lyrics = make_lyrics()
    window.set_lyrics(lyrics, duration_ms=160000)
    window.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=2,
            current_line=lyrics.lines[2],
            position_ms=84000,
            is_playing=True,
            offset_ms=0,
        )
    )
    qtbot.wait(1)

    assert len(window.line_labels) == 5
    active = window.line_labels[2]
    assert active.text() == "I stayed up all night"
    assert active._translation_label.text() == "Me quedé despierto toda la noche"
    assert active._translation_label.isVisibleTo(active)
    assert active._focus_rule._active is True

    window.resize(1000, 650)
    qtbot.wait(1)
    assert len(window.line_labels) == 3
    assert window.line_labels[1].text() == "I stayed up all night"


def test_multiline_current_lyric_gets_enough_height(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.resize(1000, 650)
    window.show()

    lyrics = LRCParser.parse(
        "[00:05.00]Welcome to the world of the Plastic Beach"
    )
    lyrics.lines[0].translation = "Bienvenido al mundo de Plastic Beach"
    window.set_lyrics(lyrics, duration_ms=160000)
    window.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=0,
            current_line=lyrics.lines[0],
            position_ms=5000,
            is_playing=True,
            offset_ms=0,
        )
    )
    qtbot.wait(1)

    active = window.line_labels[1]
    original_height = active._original_label.heightForWidth(
        active._original_label.width()
    )
    translation_height = active._translation_label.heightForWidth(
        active._translation_label.width()
    )

    assert active.height() >= original_height + translation_height + 18


def test_progress_uses_playback_duration_and_is_not_seekable(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.set_lyrics(make_lyrics())
    window.update_playback(
        PlaybackInfo(
            state=PlayerState.PLAYING,
            position_ms=42000,
            duration_ms=180000,
        )
    )

    assert window.progress_bar.position_ms == 42000
    assert window.progress_bar.duration_ms == 180000
    assert window.progress_bar.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )


def test_close_hides_to_tray_and_force_close_exits(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)
    with qtbot.waitSignal(window.closed, timeout=1000):
        window._on_close_clicked()
    assert window.isHidden()

    window.force_close()


def test_translation_toggle_and_line_click_signal(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    lyrics = make_lyrics()
    window.set_lyrics(lyrics, 160000)
    window.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=2,
            current_line=lyrics.lines[2],
            position_ms=14000,
            is_playing=False,
            offset_ms=0,
        )
    )
    window.show()
    qtbot.wait(1)

    assert window.toggle_translation() is False
    assert all(not label._translation_visible for label in window.line_labels)

    active = window.line_labels[2]
    with qtbot.waitSignal(window.sync_time_changed, timeout=1000) as signal:
        qtbot.mouseClick(active, Qt.MouseButton.LeftButton)
    assert signal.args == [14000]


def test_set_translation_enabled_updates_icon_and_lines(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.set_lyrics(make_lyrics(), 160000)

    window.set_translation_enabled(False)

    assert window.config.translation_enabled is False
    assert window.title_bar.translation_button._enabled_state is False
    assert all(not label._translation_label.isVisible() for label in window.line_labels)

    window.set_translation_enabled(True)

    assert window.title_bar.translation_button._enabled_state is True
    assert all(label._translation_visible for label in window.line_labels)


def test_translation_control_is_keyboard_accessible(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)
    button = window.title_bar.translation_button

    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    with qtbot.waitSignal(window.translation_toggle_requested, timeout=1000):
        qtbot.keyClick(button, Qt.Key.Key_Space)


def test_always_on_top_and_geometry_validation(qtbot):
    window = LyricsOverlay(OverlayConfig(always_on_top=False))
    qtbot.addWidget(window)
    window.set_always_on_top(True)

    assert window.config.always_on_top is True
    assert bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    window.show_always_on_top_indicator(True)
    assert window.offset_indicator.text() == (
        "Ventana siempre encima activada"
    )
    assert window.restore_window_state(50000, 50000, 1200, 760) is False


def test_statuses_and_manual_scroll_return_to_current_line(qtbot):
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.set_searching_lyrics()
    assert window.line_labels[2].text() == "Buscando letra"

    window.set_no_lyrics_available("Faces", "Silicone Grown")
    assert window.line_labels[2].text() == "Letra no disponible"

    lyrics = make_lyrics()
    window.set_lyrics(lyrics, 160000)
    window.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=2,
            current_line=lyrics.lines[2],
            position_ms=14000,
            is_playing=True,
            offset_ms=0,
        )
    )
    wheel = QWheelEvent(
        QPointF(100, 100),
        QPointF(100, 100),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(window, wheel)

    assert window._manual_scroll_mode is True
    assert window._manual_line_index == 3
    assert window.line_labels[2].text() == "Checking out the doctor's guide"
    assert window._back_to_auto_btn.isVisibleTo(window)

    window._exit_manual_scroll_mode()
    assert window._manual_scroll_mode is False
    assert window.line_labels[2].text() == "I stayed up all night"


def test_lyric_line_is_keyboard_accessible_and_respects_reduced_motion(
    qtbot, monkeypatch
):
    monkeypatch.setattr(
        overlay_module, "_system_animations_enabled", lambda: False
    )
    window = LyricsOverlay()
    qtbot.addWidget(window)
    window.resize(1200, 800)
    lyrics = make_lyrics()
    window.set_lyrics(lyrics, 160000)
    window.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=2,
            current_line=lyrics.lines[2],
            position_ms=14000,
            is_playing=True,
            offset_ms=0,
        )
    )
    window.show()
    qtbot.wait(1)

    active = window.line_labels[2]
    assert active.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert active.accessibleName() == "Línea actual: I stayed up all night"
    assert "Traducción:" in active.accessibleDescription()
    assert "Entrar o Espacio" in active.accessibleDescription()
    assert active._animation is None

    active.setFocus()
    qtbot.wait(1)
    assert "border: 2px solid" in active.styleSheet()
    with qtbot.waitSignal(window.sync_time_changed, timeout=1000) as signal:
        qtbot.keyClick(active, Qt.Key.Key_Return)
    assert signal.args == [14000]

    assert window.title_bar.close_button.accessibleName() == (
        "Ocultar en la bandeja"
    )
    assert "Posición 00:14" in window.progress_bar.accessibleDescription()
