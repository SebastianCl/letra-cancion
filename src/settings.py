"""
Gestor de configuración persistente.

Carga y guarda configuración del usuario en JSON.
Provee valores por defecto y validación.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ruta por defecto del archivo de configuración
DEFAULT_SETTINGS_PATH = Path.home() / ".lyrics-cache" / "settings.json"


@dataclass
class AppSettings:
    """Configuración completa de la aplicación."""

    # --- Apariencia ---
    opacity: float = 0.85
    font_size: int = 18
    highlight_font_size: int = 20
    translation_font_size: int = 14
    font_family: str = "Segoe UI"
    bg_color: str = "#1a1a2e"
    text_color: str = "#ffffff"
    highlight_color: str = "#00d4ff"
    dim_color: str = "#666666"
    translation_color: str = "#aaaaaa"

    # --- Tamaño y posición del overlay ---
    overlay_width: int = 600
    overlay_height: int = 280
    overlay_x: int = -1  # -1 = centrado automático
    overlay_y: int = -1  # -1 = inferior automático

    # --- Comportamiento ---
    translation_enabled: bool = True
    manual_scroll_timeout_s: int = 5
    offset_step_ms: int = 500

    # --- Onboarding ---
    first_run: bool = True
    onboarding_shown: bool = False

    def validate(self) -> None:
        """Valida y corrige valores fuera de rango."""
        self.opacity = max(0.3, min(1.0, self.opacity))
        self.font_size = max(10, min(32, self.font_size))
        self.highlight_font_size = max(12, min(36, self.highlight_font_size))
        self.translation_font_size = max(8, min(24, self.translation_font_size))
        self.overlay_width = max(300, min(1600, self.overlay_width))
        self.overlay_height = max(100, min(900, self.overlay_height))
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
            # Aplicar solo los campos conocidos
            for key, value in data.items():
                if hasattr(self._settings, key):
                    setattr(self._settings, key, value)
            self._settings.validate()
            logger.info(f"Configuración cargada desde {self._path}")
        except Exception as e:
            logger.warning(f"Error cargando configuración: {e}. Usando valores por defecto.")
            self._settings = AppSettings()

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
