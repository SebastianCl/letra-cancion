"""
System Tray para la aplicación de letras.

Proporciona un icono en la bandeja del sistema con menú
para controlar la aplicación.
"""

import logging
from typing import Callable, Optional
from pathlib import Path

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtCore import pyqtSignal, QObject

logger = logging.getLogger(__name__)


class TrayIcon(QObject):
    """
    Icono de bandeja del sistema con menú contextual.
    
    Signals:
        show_overlay: Solicita mostrar el overlay
        hide_overlay: Solicita ocultar el overlay
        offset_reset: Solicita resetear el offset
        quit_app: Solicita cerrar la aplicación
    """
    
    # Signals
    show_overlay = pyqtSignal()
    hide_overlay = pyqtSignal()
    toggle_overlay = pyqtSignal()
    offset_reset = pyqtSignal()
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._overlay_visible: bool = True
        
        # Info actual de la canción
        self._current_track: str = "Sin reproducción"
        
        self._setup_tray()
    
    def _create_icon(self) -> QIcon:
        """
        Crea el icono para el tray.
        
        Genera un icono simple con el símbolo ♪
        """
        # Crear pixmap
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparente
        
        # Dibujar
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Círculo de fondo
        painter.setBrush(QColor(0, 212, 255))  # Cyan
        painter.setPen(QColor(0, 0, 0, 0))
        painter.drawEllipse(4, 4, size - 8, size - 8)
        
        # Símbolo de música
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI", 28, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), 0x0084, "♪")  # AlignCenter
        
        painter.end()
        
        return QIcon(pixmap)
    
    def _setup_tray(self) -> None:
        """Configura el icono del tray y el menú."""
        # Crear icono
        self._tray = QSystemTrayIcon(self._create_icon())
        
        # Crear menú
        self._menu = QMenu()
        
        # --- Acciones del menú ---
        
        # Info del track actual
        self._track_action = QAction("🎵 Sin reproducción")
        self._track_action.setEnabled(False)
        self._menu.addAction(self._track_action)
        
        self._menu.addSeparator()
        
        # Toggle overlay
        self._toggle_action = QAction("👁 Ocultar letras")
        self._toggle_action.triggered.connect(self._on_toggle_clicked)
        self._menu.addAction(self._toggle_action)
        
        # Resetear offset
        reset_action = QAction("🔄 Resetear sincronización")
        reset_action.triggered.connect(lambda: self.offset_reset.emit())
        self._menu.addAction(reset_action)
        
        self._menu.addSeparator()
        
        # Info de hotkeys
        hotkeys_action = QAction("⌨ Atajos de teclado")
        hotkeys_action.triggered.connect(self._show_hotkeys_info)
        self._menu.addAction(hotkeys_action)
        
        self._menu.addSeparator()
        
        # Salir
        quit_action = QAction("❌ Salir")
        quit_action.triggered.connect(lambda: self.quit_app.emit())
        self._menu.addAction(quit_action)
        
        # Asignar menú
        self._tray.setContextMenu(self._menu)
        
        # Tooltip
        self._tray.setToolTip("Letras Sincronizadas\nClic derecho para opciones")
        
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
    
    def _show_hotkeys_info(self) -> None:
        """Muestra información de los hotkeys disponibles."""
        self._tray.showMessage(
            "Atajos de teclado",
            "Ctrl+Shift+L: Mostrar/ocultar letras\n"
            "Ctrl+Alt+↑/↓: Ajustar sincronización\n"
            "Ctrl+Alt+R: Resetear sincronización\n"
            "Ctrl+Shift+M: Mover overlay\n"
            "Ctrl+Shift+Q: Salir",
            QSystemTrayIcon.MessageIcon.Information,
            5000
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
            self._tray.setToolTip(f"Letras Sincronizadas\n{self._current_track}")
    
    def clear_track_info(self) -> None:
        """Limpia la información del track."""
        self._current_track = "Sin reproducción"
        
        if self._track_action:
            self._track_action.setText("🎵 Sin reproducción")
        
        if self._tray:
            self._tray.setToolTip("Letras Sincronizadas\nClic derecho para opciones")
    
    def set_overlay_visible(self, visible: bool) -> None:
        """
        Actualiza el estado del toggle en el menú.
        
        Args:
            visible: True si el overlay está visible
        """
        self._overlay_visible = visible
        
        if self._toggle_action:
            if visible:
                self._toggle_action.setText("👁 Ocultar letras")
            else:
                self._toggle_action.setText("👁 Mostrar letras")
    
    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 3000
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
            2000
        )
    
    def show_lyrics_not_found(self) -> None:
        """Muestra notificación de letras no encontradas."""
        self.show_notification(
            "Sin letras",
            "No se encontraron letras para esta canción",
            QSystemTrayIcon.MessageIcon.Warning,
            2000
        )
    
    def show_error(self, message: str) -> None:
        """Muestra notificación de error."""
        self.show_notification(
            "Error",
            message,
            QSystemTrayIcon.MessageIcon.Critical,
            3000
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
        "Letras Sincronizadas",
        "Aplicación iniciada.\nClic derecho para opciones.",
        QSystemTrayIcon.MessageIcon.Information,
        5000
    )
    
    print("Tray icon activo. Clic derecho para ver menú.")
    print("Usa el menú 'Salir' para cerrar.")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
