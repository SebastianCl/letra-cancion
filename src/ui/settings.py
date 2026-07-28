"""
Diálogos de configuración y ayuda.

- SettingsDialog: Panel de configuración accesible desde el tray.
- HelpDialog: Referencia rápida de atajos e interacciones.
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QPushButton,
    QTabWidget,
    QWidget,
    QGroupBox,
    QFormLayout,
    QCheckBox,
    QComboBox,
    QTextBrowser,
)
from PyQt6.QtCore import Qt, pyqtSignal

from ..settings import AppSettings

logger = logging.getLogger(__name__)


# ── Estilos compartidos ────────────────────────────────────────────────────
_DARK_STYLE = """
    QDialog, QTabWidget::pane, QWidget {
        background-color: #0b1028;
        color: #ffffff;
    }
    QTabBar::tab {
        background: #111735;
        color: #aeb5cf;
        padding: 8px 18px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background: #0b1028;
        color: #a78bfa;
        font-weight: bold;
    }
    QGroupBox {
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 18px;
        color: #a78bfa;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
    }
    QLabel { color: #ddd; font-size: 13px; }
    QSlider::groove:horizontal {
        height: 6px; background: #242b50; border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #8b5cf6; width: 16px; margin: -5px 0;
        border-radius: 8px;
    }
    QSlider::sub-page:horizontal { background: #8b5cf6; border-radius: 3px; }
    QCheckBox { color: #ddd; font-size: 13px; spacing: 6px; }
    QCheckBox::indicator { width: 18px; height: 18px; }
    QCheckBox::indicator:unchecked { border: 2px solid #4b557f; border-radius: 4px; background: #111735; }
    QCheckBox::indicator:checked  { border: 2px solid #8b5cf6; border-radius: 4px; background: #8b5cf6; }
    QComboBox {
        background: #111735; color: white; border: 1px solid #4b557f;
        border-radius: 5px; padding: 4px 8px;
    }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView { background: #111735; color: white; selection-background-color: #8b5cf6; }
    QPushButton {
        background-color: #8b5cf6; color: #ffffff;
        border: none; border-radius: 6px; padding: 8px 20px;
        font-weight: bold; font-size: 13px;
    }
    QPushButton:hover { background-color: #9f7aea; }
    QPushButton:pressed { background-color: #6d4bd6; }
    QPushButton#cancelBtn, QPushButton#resetBtn {
        background-color: #444; color: white;
    }
    QPushButton#cancelBtn:hover, QPushButton#resetBtn:hover {
        background-color: #555;
    }
"""


class SettingsDialog(QDialog):
    """Panel de configuración de la aplicación."""

    settings_changed = pyqtSignal()  # Emitido al guardar

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Configuración — Letra Canción")
        self.setMinimumSize(440, 480)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(_DARK_STYLE)
        self._build_ui()
        self._load_values()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        tabs = QTabWidget()

        # ── Tab: Apariencia ──
        appearance = QWidget()
        alay = QVBoxLayout(appearance)

        # Opacidad
        g_opacity = QGroupBox("Opacidad del fondo")
        gl = QFormLayout(g_opacity)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(65, 100)
        self._opacity_label = QLabel()
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        gl.addRow(self._opacity_slider, self._opacity_label)
        alay.addWidget(g_opacity)

        # Fuente
        g_font = QGroupBox("Tamaño de fuente")
        fl = QFormLayout(g_font)

        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(16, 32)
        self._font_label = QLabel()
        self._font_slider.valueChanged.connect(
            lambda v: self._font_label.setText(f"{v}px")
        )
        fl.addRow("Texto:", self._font_slider)
        fl.addRow("", self._font_label)

        self._highlight_slider = QSlider(Qt.Orientation.Horizontal)
        self._highlight_slider.setRange(32, 64)
        self._hl_label = QLabel()
        self._highlight_slider.valueChanged.connect(
            lambda v: self._hl_label.setText(f"{v}px")
        )
        fl.addRow("Línea activa:", self._highlight_slider)
        fl.addRow("", self._hl_label)

        self._trans_font_slider = QSlider(Qt.Orientation.Horizontal)
        self._trans_font_slider.setRange(12, 28)
        self._tf_label = QLabel()
        self._trans_font_slider.valueChanged.connect(
            lambda v: self._tf_label.setText(f"{v}px")
        )
        fl.addRow("Traducción:", self._trans_font_slider)
        fl.addRow("", self._tf_label)

        alay.addWidget(g_font)
        alay.addStretch()
        tabs.addTab(appearance, "🎨 Apariencia")

        # ── Tab: Comportamiento ──
        behavior = QWidget()
        blay = QVBoxLayout(behavior)

        g_sync = QGroupBox("Sincronización")
        sl = QFormLayout(g_sync)

        self._offset_combo = QComboBox()
        for ms in (100, 250, 500, 1000):
            self._offset_combo.addItem(f"{ms} ms", ms)
        sl.addRow("Paso de offset:", self._offset_combo)

        self._scroll_slider = QSlider(Qt.Orientation.Horizontal)
        self._scroll_slider.setRange(2, 30)
        self._scroll_label = QLabel()
        self._scroll_slider.valueChanged.connect(
            lambda v: self._scroll_label.setText(f"{v}s")
        )
        sl.addRow("Timeout scroll manual:", self._scroll_slider)
        sl.addRow("", self._scroll_label)
        blay.addWidget(g_sync)

        g_trans = QGroupBox("Traducción")
        tl = QFormLayout(g_trans)
        self._trans_check = QCheckBox("Traducir letras automáticamente")
        tl.addRow(self._trans_check)
        blay.addWidget(g_trans)

        g_window = QGroupBox("Ventana")
        wl = QFormLayout(g_window)
        self._always_on_top_check = QCheckBox("Mantener Letra Canción siempre encima")
        wl.addRow(self._always_on_top_check)
        blay.addWidget(g_window)

        blay.addStretch()
        tabs.addTab(behavior, "⚙ Comportamiento")

        root.addWidget(tabs, 1)

        # ── Botones ──
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Restaurar")
        reset_btn.setObjectName("resetBtn")
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self._on_save)
        save_btn.setDefault(True)
        btn_row.addWidget(save_btn)

        root.addLayout(btn_row)

    # ── Cargar / guardar ────────────────────────────────────────────────────

    def _load_values(self) -> None:
        s = self._settings
        self._opacity_slider.setValue(int(s.opacity * 100))
        self._font_slider.setValue(s.font_size)
        self._highlight_slider.setValue(s.highlight_font_size)
        self._trans_font_slider.setValue(s.translation_font_size)

        idx = self._offset_combo.findData(s.offset_step_ms)
        if idx >= 0:
            self._offset_combo.setCurrentIndex(idx)

        self._scroll_slider.setValue(s.manual_scroll_timeout_s)
        self._trans_check.setChecked(s.translation_enabled)
        self._always_on_top_check.setChecked(s.always_on_top)

    def _on_save(self) -> None:
        s = self._settings
        s.opacity = self._opacity_slider.value() / 100.0
        s.font_size = self._font_slider.value()
        s.highlight_font_size = self._highlight_slider.value()
        s.translation_font_size = self._trans_font_slider.value()
        s.offset_step_ms = self._offset_combo.currentData()
        s.manual_scroll_timeout_s = self._scroll_slider.value()
        s.translation_enabled = self._trans_check.isChecked()
        s.always_on_top = self._always_on_top_check.isChecked()
        s.validate()
        self.settings_changed.emit()
        self.accept()

    def _on_reset(self) -> None:
        """Restaura valores por defecto en los controles."""
        defaults = AppSettings()
        self._opacity_slider.setValue(int(defaults.opacity * 100))
        self._font_slider.setValue(defaults.font_size)
        self._highlight_slider.setValue(defaults.highlight_font_size)
        self._trans_font_slider.setValue(defaults.translation_font_size)
        idx = self._offset_combo.findData(defaults.offset_step_ms)
        if idx >= 0:
            self._offset_combo.setCurrentIndex(idx)
        self._scroll_slider.setValue(defaults.manual_scroll_timeout_s)
        self._trans_check.setChecked(defaults.translation_enabled)
        self._always_on_top_check.setChecked(defaults.always_on_top)


class HelpDialog(QDialog):
    """Diálogo de ayuda con atajos e interacciones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayuda — Letra Canción")
        self.setMinimumSize(460, 420)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(_DARK_STYLE)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            "QTextBrowser { background: #0b1028; color: #ddd; border: none; font-size: 13px; }"
        )
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser, 1)

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)


_HELP_HTML = """
<h2 style="color:#a78bfa;">Atajos de teclado</h2>
<table cellpadding="6" style="width:100%;">
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+Shift+L</td>
      <td>Mostrar / ocultar la ventana</td></tr>
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+T</td>
      <td>Activar / desactivar traducción</td></tr>
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+Alt+↑</td>
      <td>Retrasar letras (si van adelantadas)</td></tr>
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+Alt+↓</td>
      <td>Adelantar letras (si van atrasadas)</td></tr>
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+Alt+R</td>
      <td>Resetear ajuste de sincronización</td></tr>
  <tr><td style="color:#a78bfa;font-family:monospace;">Ctrl+Shift+Q</td>
      <td>Salir de la aplicación</td></tr>
</table>

<h2 style="color:#a78bfa;">Interacciones del mouse</h2>
<table cellpadding="6" style="width:100%;">
  <tr><td style="color:#a78bfa;">Barra superior</td>
      <td>Arrastrar para mover; doble clic para maximizar</td></tr>
  <tr><td style="color:#a78bfa;">Click izq. en línea</td>
      <td>Sincronizar reproducción a esa línea</td></tr>
  <tr><td style="color:#a78bfa;">Click derecho</td>
      <td>Ajustar tiempo de sincronización manualmente</td></tr>
  <tr><td style="color:#a78bfa;">Scroll (rueda)</td>
      <td>Navegar por la letra manualmente</td></tr>
  <tr><td style="color:#a78bfa;">Bordes / esquinas</td>
      <td>Redimensionar la ventana</td></tr>
  <tr><td style="color:#a78bfa;">Botón cerrar</td>
      <td>Ocultar en la bandeja sin detener la aplicación</td></tr>
</table>

<p style="color:#888; margin-top:16px;">
  <b>Letra Canción</b> · Letras sincronizadas para Qobuz<br>
  Datos de letras: LRCLIB, NetEase Music
</p>
"""
