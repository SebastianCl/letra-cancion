from types import SimpleNamespace

from src import hotkeys
from src.hotkeys import HotkeyAction, HotkeyManager


def test_hotkey_registration_reports_only_failed_combinations(monkeypatch):
    registered = []

    def add_hotkey(keys, handler, **kwargs):
        if keys == "ctrl+t":
            raise RuntimeError("combination already in use")
        registered.append(keys)
        return f"hook:{keys}"

    fake_keyboard = SimpleNamespace(
        add_hotkey=add_hotkey,
        unhook_all_hotkeys=lambda: None,
    )
    monkeypatch.setattr(hotkeys, "KEYBOARD_AVAILABLE", True)
    monkeypatch.setattr(hotkeys, "keyboard", fake_keyboard, raising=False)
    manager = HotkeyManager()

    failed = manager.start()

    assert [item.action for item in failed] == [
        HotkeyAction.TOGGLE_TRANSLATION
    ]
    assert "ctrl+shift+l" in registered
    assert "ctrl+shift+q" in registered
    assert len(manager._registered_hooks) == (
        len(manager.DEFAULT_HOTKEYS) - 1
    )
    manager.stop()
