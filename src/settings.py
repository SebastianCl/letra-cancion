"""
Gestor de configuración persistente.

Carga y guarda configuración del usuario en JSON.
Provee valores por defecto y validación.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ruta por defecto del archivo de configuración
DEFAULT_SETTINGS_PATH = Path.home() / ".lyrics-cache" / "settings.json"
CURRENT_DESIGN_VERSION = 2


@dataclass
class AppSettings:
    """Configuración completa de la aplicación."""

    # --- Versión de interfaz ---
    design_version: int = CURRENT_DESIGN_VERSION

    # --- Apariencia ---
    opacity: float = 1.0
    font_size: int = 24
    highlight_font_size: int = 48
    translation_font_size: int = 18
    font_family: str = "Segoe UI Variable, Segoe UI"
    bg_color: str = "#080b1d"
    text_color: str = "#ffffff"
    highlight_color: str = "#ffffff"
    dim_color: str = "#3f4762"
    translation_color: str = "#8b5cf6"

    # --- Tamaño y posición de la ventana ---
    # 0 = calcular automáticamente a partir de la pantalla disponible.
    overlay_width: int = 0
    overlay_height: int = 0
    overlay_x: int = -1  # -1 = centrado automático
    overlay_y: int = -1  # -1 = centrado automático
    window_maximized: bool = False
    always_on_top: bool = False

    # --- Comportamiento ---
    translation_enabled: bool = True
    manual_scroll_timeout_s: int = 5
    offset_step_ms: int = 500

    # --- Onboarding ---
    first_run: bool = True
    onboarding_shown: bool = False

    def validate(self) -> None:
        """Valida y corrige valores fuera de rango."""
        self.design_version = CURRENT_DESIGN_VERSION
        self.opacity = max(0.65, min(1.0, self.opacity))
        self.font_size = max(16, min(32, self.font_size))
        self.highlight_font_size = max(32, min(64, self.highlight_font_size))
        self.translation_font_size = max(12, min(28, self.translation_font_size))
        if self.overlay_width != 0:
            self.overlay_width = max(900, min(1920, self.overlay_width))
        if self.overlay_height != 0:
            self.overlay_height = max(600, min(1200, self.overlay_height))
        self.manual_scroll_timeout_s = max(2, min(30, self.manual_scroll_timeout_s))
        self.offset_step_ms = max(100, min(2000, self.offset_step_ms))


class SettingsManager:
    """
    Carga, guarda y provee acceso a la configuración de la app.

    Persiste en ~/.lyrics-cache/settings.json
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_SETTINGS_PATH
        self._settings = AppSettings()
        self.load()

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def load(self) -> None:
        """Carga la configuración desde disco. Si no existe, usa defaults."""
        if not self._path.exists():
            logger.info("No se encontró archivo de configuración, usando valores por defecto")
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("La configuración debe ser un objeto JSON")
            try:
                design_version = int(data.get("design_version", 1))
            except (TypeError, ValueError):
                design_version = 1
            if design_version < CURRENT_DESIGN_VERSION:
                data = self._migrate_legacy_settings(data)
            # Aplicar solo los campos conocidos
            defaults = AppSettings()
            for key, value in data.items():
                if not hasattr(defaults, key):
                    continue
                default_value = getattr(defaults, key)
                if isinstance(default_value, bool):
                    valid = isinstance(value, bool)
                elif isinstance(default_value, int):
                    valid = isinstance(value, int) and not isinstance(value, bool)
                elif isinstance(default_value, float):
                    valid = (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                    )
                    if valid:
                        value = float(value)
                else:
                    valid = isinstance(value, type(default_value))
                if valid:
                    setattr(self._settings, key, value)
                else:
                    logger.warning(
                        "Valor inválido para %s; se conserva el valor por defecto",
                        key,
                    )
            self._settings.validate()
            logger.info(f"Configuración cargada desde {self._path}")
        except Exception as e:
            logger.warning(f"Error cargando configuración: {e}. Usando valores por defecto.")
            self._settings = AppSettings()

    @staticmethod
    def _migrate_legacy_settings(data: dict) -> dict:
        """
        Migra la interfaz compacta anterior al diseño inmersivo.

        Se conservan preferencias de comportamiento y onboarding, pero se
        reinician geometría y apariencia para que valores antiguos no rompan
        el nuevo layout.
        """
        migrated = asdict(AppSettings())
        for key in (
            "translation_enabled",
            "manual_scroll_timeout_s",
            "offset_step_ms",
            "first_run",
            "onboarding_shown",
        ):
            if key in data:
                migrated[key] = data[key]
        migrated["design_version"] = CURRENT_DESIGN_VERSION
        logger.info("Configuración visual migrada al diseño v2")
        return migrated

    def save(self) -> None:
        """Guarda la configuración actual en disco."""
        try:
            self._settings.validate()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(self._settings)
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug(f"Configuración guardada en {self._path}")
        except Exception as e:
            logger.warning(f"Error guardando configuración: {e}")

    def reset(self) -> None:
        """Restaura valores por defecto y guarda."""
        self._settings = AppSettings()
        self.save()
        logger.info("Configuración restaurada a valores por defecto")
