"""
System Tray para la aplicación de letras.

Proporciona un icono en la bandeja del sistema con menú
para controlar la aplicación.
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import pyqtSignal, QObject

from .brand import create_brand_icon
from .settings import SettingsDialog, HelpDialog
from ..settings import AppSettings

logger = logging.getLogger(__name__)


class TrayIcon(QObject):
    """
    Icono de bandeja del sistema con menú contextual.

    Signals:
        show_overlay: Solicita mostrar el overlay
        hide_overlay: Solicita ocultar el overlay
        offset_reset: Solicita resetear el offset
        offset_increase: Solicita aumentar offset
        offset_decrease: Solicita disminuir offset
        quit_app: Solicita cerrar la aplicación
    """

    # Signals
    show_overlay = pyqtSignal()
    hide_overlay = pyqtSignal()
    toggle_overlay = pyqtSignal()
    toggle_translation = pyqtSignal()
    toggle_always_on_top = pyqtSignal()
    offset_reset = pyqtSignal()
    offset_increase = pyqtSignal()
    offset_decrease = pyqtSignal()
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()

    def __init__(self, settings: Optional[AppSettings] = None, parent=None):
        super().__init__(parent)

        self._settings = settings
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._overlay_visible: bool = True
        self._translation_enabled: bool = True
        self._always_on_top: bool = bool(settings.always_on_top) if settings else False

        # Info actual de la canción
        self._current_track: str = "Sin reproducción"

        self._setup_tray()

    def _create_icon(self) -> QIcon:
        """Crea el icono vectorial compartido con la ventana."""
        return create_brand_icon()

    def _setup_tray(self) -> None:
        """Configura el icono del tray y el menú."""
        # Crear icono
        self._tray = QSystemTrayIcon(self._create_icon())

        # Crear menú
        self._menu = QMenu()
        self._menu.setStyleSheet(
            """
            QMenu {
                background:#0b1028; color:#ececff;
                border:1px solid rgba(139,92,246,0.28);
                border-radius:8px; padding:6px;
            }
            QMenu::item { padding:7px 22px 7px 10px; border-radius:5px; }
            QMenu::item:selected { background:rgba(139,92,246,0.24); }
            QMenu::separator { height:1px; background:#242b50; margin:5px 8px; }
            """
        )

        # --- Acciones del menú ---

        # Info del track actual
        self._track_action = QAction("🎵 Sin reproducción")
        self._track_action.setEnabled(False)
        self._menu.addAction(self._track_action)

        self._menu.addSeparator()

        # Toggle overlay
        self._toggle_action = QAction("Ocultar ventana")
        self._toggle_action.triggered.connect(self._on_toggle_clicked)
        self._menu.addAction(self._toggle_action)

        # Toggle traducción (H6: hacer visible, antes solo Ctrl+T invisible)
        self._translation_action = QAction("Traducción: activada")
        self._translation_action.triggered.connect(self._on_translation_toggled)
        self._menu.addAction(self._translation_action)

        self._always_on_top_action = QAction()
        self._always_on_top_action.triggered.connect(
            lambda: self.toggle_always_on_top.emit()
        )
        self._menu.addAction(self._always_on_top_action)
        self.set_always_on_top(self._always_on_top)

        # Submenú de sincronización (H2: lenguaje natural)
        sync_menu = self._menu.addMenu("Sincronización")

        offset_up_action = QAction("⏩ Letras van adelantadas (+500ms)")
        offset_up_action.triggered.connect(lambda: self.offset_increase.emit())
        sync_menu.addAction(offset_up_action)

        offset_down_action = QAction("⏪ Letras van atrasadas (-500ms)")
        offset_down_action.triggered.connect(lambda: self.offset_decrease.emit())
        sync_menu.addAction(offset_down_action)

        sync_menu.addSeparator()

        reset_action = QAction("🔄 Resetear sincronización")
        reset_action.triggered.connect(lambda: self.offset_reset.emit())
        sync_menu.addAction(reset_action)

        self._menu.addSeparator()

        # Configuración (H7)
        settings_action = QAction("Configuración")
        settings_action.triggered.connect(self._show_settings)
        self._menu.addAction(settings_action)

        # Ayuda (H10)
        help_action = QAction("Ayuda")
        help_action.triggered.connect(self._show_help)
        self._menu.addAction(help_action)

        self._menu.addSeparator()

        # Salir
        quit_action = QAction("Salir de Letra Canción")
        quit_action.triggered.connect(lambda: self.quit_app.emit())
        self._menu.addAction(quit_action)

        # Asignar menú
        self._tray.setContextMenu(self._menu)

        # Tooltip
        self._tray.setToolTip("Letra Canción\nClic derecho para opciones")

        # Conectar click en el icono
        self._tray.activated.connect(self._on_tray_activated)

    def _on_toggle_clicked(self) -> None:
        """Maneja el click en toggle overlay."""
        self.toggle_overlay.emit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Maneja la activación del icono del tray."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # Doble click: toggle overlay
            self.toggle_overlay.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Click simple: también toggle
            self.toggle_overlay.emit()

    def _on_translation_toggled(self) -> None:
        """Maneja el click en toggle traducción."""
        self.toggle_translation.emit()

    def _show_settings(self) -> None:
        """Abre el diálogo de configuración (H7)."""
        if self._settings is None:
            return
        dialog = SettingsDialog(self._settings)
        dialog.settings_changed.connect(lambda: self.open_settings.emit())
        dialog.exec()

    def _show_help(self) -> None:
        """Abre el diálogo de ayuda (H10)."""
        dialog = HelpDialog()
        dialog.exec()

    def _show_hotkeys_info(self) -> None:
        """Muestra información de los hotkeys disponibles."""
        self._tray.showMessage(
            "Atajos de teclado",
            "Ctrl+Shift+L: Mostrar/ocultar letras\n"
            "Ctrl+T: Activar/desactivar traducción\n"
            "Ctrl+Alt+↑/↓: Ajustar sincronización\n"
            "Ctrl+Alt+R: Resetear sincronización\n"
            "Ctrl+Shift+Q: Salir",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    # --- API Pública ---

    def show(self) -> None:
        """Muestra el icono en el tray."""
        if self._tray:
            self._tray.show()
            logger.info("Tray icon mostrado")

    def hide(self) -> None:
        """Oculta el icono del tray."""
        if self._tray:
            self._tray.hide()

    def update_track_info(self, artist: str, title: str) -> None:
        """
        Actualiza la información del track actual.

        Args:
            artist: Nombre del artista
            title: Título de la canción
        """
        self._current_track = f"{artist} - {title}"

        if self._track_action:
            display_text = self._current_track
            if len(display_text) > 40:
                display_text = display_text[:37] + "..."
            self._track_action.setText(f"🎵 {display_text}")

        if self._tray:
            self._tray.setToolTip(f"Letra Canción\n{self._current_track}")

    def clear_track_info(self) -> None:
        """Limpia la información del track."""
        self._current_track = "Sin reproducción"

        if self._track_action:
            self._track_action.setText("🎵 Sin reproducción")

        if self._tray:
            self._tray.setToolTip("Letra Canción\nClic derecho para opciones")

    def set_overlay_visible(self, visible: bool) -> None:
        """
        Actualiza el estado del toggle en el menú.

        Args:
            visible: True si el overlay está visible
        """
        self._overlay_visible = visible
        if self._toggle_action:
            if visible:
                self._toggle_action.setText("Ocultar ventana")
            else:
                self._toggle_action.setText("Mostrar ventana")

    def set_translation_enabled(self, enabled: bool) -> None:
        """Actualiza el estado de traducción en el menú (H6)."""
        self._translation_enabled = enabled
        if self._translation_action:
            if enabled:
                self._translation_action.setText("Traducción: activada")
            else:
                self._translation_action.setText("Traducción: desactivada")

    def set_always_on_top(self, enabled: bool) -> None:
        """Sincroniza la preferencia de ventana flotante en el menú."""
        self._always_on_top = enabled
        if hasattr(self, "_always_on_top_action"):
            self._always_on_top_action.setText(
                "Siempre encima: activado" if enabled else "Siempre encima: desactivado"
            )

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 3000,
    ) -> None:
        """
        Muestra una notificación desde el tray.

        Args:
            title: Título de la notificación
            message: Mensaje
            icon: Tipo de icono
            duration_ms: Duración en milisegundos
        """
        if self._tray:
            self._tray.showMessage(title, message, icon, duration_ms)

    def show_lyrics_found(self, provider: str) -> None:
        """Muestra notificación de letras encontradas."""
        self.show_notification(
            "Letras encontradas",
            f"Fuente: {provider}",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def show_lyrics_not_found(self) -> None:
        """Muestra notificación de letras no encontradas."""
        self.show_notification(
            "Sin letras",
            "No se encontraron letras para esta canción",
            QSystemTrayIcon.MessageIcon.Warning,
            2000,
        )

    def show_error(self, message: str) -> None:
        """Muestra notificación de error."""
        self.show_notification(
            "Error", message, QSystemTrayIcon.MessageIcon.Critical, 3000
        )


# --- Demo standalone ---
def main():
    """Demo del tray icon."""
    import sys

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # No cerrar al cerrar ventanas

    tray = TrayIcon()

    # Conectar signals para demo
    def on_toggle():
        print("Toggle overlay requested")
        tray.set_overlay_visible(not tray._overlay_visible)

    def on_quit():
        print("Quit requested")
        app.quit()

    tray.toggle_overlay.connect(on_toggle)
    tray.quit_app.connect(on_quit)

    tray.show()

    # Simular track
    tray.update_track_info("Coldplay", "Yellow")

    # Mostrar notificación
    tray.show_notification(
        "Letra Canción",
        "Aplicación iniciada.\nClic derecho para opciones.",
        QSystemTrayIcon.MessageIcon.Information,
        5000,
    )

    print("Tray icon activo. Clic derecho para ver menú.")
    print("Usa el menú 'Salir' para cerrar.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
