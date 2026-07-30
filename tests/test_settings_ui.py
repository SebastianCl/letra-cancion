from PyQt6.QtCore import Qt

from src.settings import AppSettings
from src.ui.settings import SettingsDialog


def test_settings_controls_have_accessible_names_and_focus_order(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog._opacity_slider.accessibleName() == (
        "Opacidad del fondo"
    )
    assert dialog._font_slider.accessibleName() == (
        "Tamaño del texto de contexto"
    )
    assert dialog._highlight_slider.accessibleName() == (
        "Tamaño de la línea activa"
    )
    assert dialog._offset_combo.accessibleName() == (
        "Paso de sincronización"
    )
    dialog._opacity_slider.setFocus()
    qtbot.keyClick(dialog._opacity_slider, Qt.Key.Key_Tab)
    assert dialog.focusWidget() is dialog._font_slider
    assert dialog._cancel_btn.accessibleDescription() == (
        "Cierra la configuración sin aplicar los cambios."
    )


def test_settings_can_be_changed_and_saved_with_keyboard(qtbot):
    settings = AppSettings()
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._opacity_slider.setFocus()

    qtbot.keyClick(dialog._opacity_slider, Qt.Key.Key_Home)
    assert dialog._opacity_slider.value() == 65

    with qtbot.waitSignal(dialog.settings_changed, timeout=1000):
        qtbot.keyClick(dialog._save_btn, Qt.Key.Key_Return)

    assert settings.opacity == 0.65
