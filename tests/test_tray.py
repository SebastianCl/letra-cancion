import gc

from src.ui.tray import TrayIcon


def _action_texts(menu):
    texts = []
    for action in menu.actions():
        texts.append(action.text())
        if action.menu() is not None:
            texts.extend(_action_texts(action.menu()))
    return texts


def test_tray_actions_survive_garbage_collection(qtbot):
    tray = TrayIcon()

    gc.collect()
    texts = _action_texts(tray._menu)

    assert "Gestionar letras" in texts
    assert "Configuración" in texts
    assert "Ayuda" in texts
    assert "Salir de Letra Canción" in texts
    assert "🔄 Resetear sincronización" in texts

    tray.hide()
    tray._menu.close()
    tray.deleteLater()
