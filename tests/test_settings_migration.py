import json

from src.settings import CURRENT_DESIGN_VERSION, SettingsManager


def test_legacy_settings_keep_behavior_and_reset_visual_geometry(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "opacity": 0.4,
                "font_size": 11,
                "overlay_width": 420,
                "overlay_height": 180,
                "overlay_x": 42,
                "overlay_y": 71,
                "translation_enabled": False,
                "manual_scroll_timeout_s": 9,
                "offset_step_ms": 250,
                "first_run": False,
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(settings_path)
    settings = manager.settings

    assert settings.design_version == CURRENT_DESIGN_VERSION
    assert settings.translation_enabled is False
    assert settings.manual_scroll_timeout_s == 9
    assert settings.offset_step_ms == 250
    assert settings.first_run is False
    assert settings.opacity == 1.0
    assert settings.font_size == 24
    assert settings.overlay_width == 0
    assert settings.overlay_height == 0
    assert settings.overlay_x == -1
    assert settings.overlay_y == -1
    assert settings.always_on_top is False


def test_v2_settings_persist_window_state(tmp_path):
    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(settings_path)
    manager.settings.always_on_top = True
    manager.settings.window_maximized = True
    manager.settings.overlay_width = 1200
    manager.settings.overlay_height = 760
    manager.save()

    reloaded = SettingsManager(settings_path).settings

    assert reloaded.always_on_top is True
    assert reloaded.window_maximized is True
    assert reloaded.overlay_width == 1200
    assert reloaded.overlay_height == 760


def test_invalid_field_keeps_other_valid_v2_settings(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "design_version": CURRENT_DESIGN_VERSION,
                "opacity": "not-a-number",
                "translation_enabled": False,
                "overlay_width": 1200,
            }
        ),
        encoding="utf-8",
    )

    settings = SettingsManager(settings_path).settings

    assert settings.opacity == 1.0
    assert settings.translation_enabled is False
    assert settings.overlay_width == 1200


def test_old_low_contrast_default_is_upgraded(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "design_version": CURRENT_DESIGN_VERSION,
                "dim_color": "#3f4762",
            }
        ),
        encoding="utf-8",
    )

    settings = SettingsManager(settings_path).settings

    assert settings.dim_color == "#aeb5cf"

