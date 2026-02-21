"""
Overlay transparente para mostrar letras sincronizadas.

Ventana sin bordes, siempre visible, con fondo semitransparente
que muestra las letras con la línea actual resaltada.
"""

import logging
from typing import Optional
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QProgressBar,
    QSizeGrip,
    QDialog,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import (
    Qt,
    QPropertyAnimation,
    QEasingCurve,
    QPoint,
    QTimer,
    pyqtSignal,
    QSize,
)
from PyQt6.QtGui import (
    QFont,
    QColor,
    QPalette,
    QMouseEvent,
    QPainter,
    QBrush,
    QPaintEvent,
    QFontMetrics,
    QWheelEvent,
)

from ..lrc_parser import LyricLine, LyricsData
from ..sync_engine import SyncState, SyncMode

logger = logging.getLogger(__name__)


@dataclass
class OverlayConfig:
    """Configuración del overlay."""

    width: int = 800
    height: int = 500  # Más altura para el nuevo diseño de footer
    # Opacidad del fondo del contenedor (0.0-1.0).
    opacity: float = 1.0
    font_size: int = 24
    font_family: str = "Inter, Segoe UI, sans-serif"
    bg_color: str = "#0a0a0f"  # Oscuro profundo
    text_color: str = "#ffffff"
    highlight_color: str = "#ffffff"
    dim_color: str = "#888888"
    lines_before: int = 1  # Valor inicial, se recalcula dinámicamente
    lines_after: int = 1  # Valor inicial, se recalcula dinámicamente
    show_progress: bool = True
    show_sync_mode: bool = True
    # Opciones de traducción
    translation_enabled: bool = True
    translation_font_size: int = 14
    translation_color: str = "#aaaaaa"
    # Configuración para cálculo dinámico de líneas
    line_height_without_translation: int = 42
    line_height_with_translation: int = 64
    min_visible_lines: int = 3  # Mínimo de líneas visibles
    header_footer_height: int = 80  # Espacio reservado para header y footer
    # Timeout de scroll manual en segundos (desde settings)
    manual_scroll_timeout_s: int = 5


class LyricLabel(QWidget):
    """Widget personalizado para una línea de letra con traducción opcional."""

    # Señal emitida cuando se hace clic en la línea (índice real, timestamp_ms)
    line_clicked = pyqtSignal(int, int)

    def __init__(
        self, config: OverlayConfig, parent=None, is_dual_column: bool = False
    ):
        super().__init__(parent)
        self._config = config
        self._is_current = False
        self._opacity = 1.0
        self._translation_visible = config.translation_enabled
        self._real_line_index: int = -1  # Índice real en la lista de líneas
        self._timestamp_ms: int = 0  # Timestamp de la línea
        self._is_dual_column = is_dual_column
        self._has_translation_data = False

        # Habilitar hover
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Usar siempre QHBoxLayout para mantener consistencia de layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(20)

        # Label para texto original (Columna izquierda)
        self._original_label = QLabel()
        self._original_label.setWordWrap(True)
        self._original_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        layout.addWidget(self._original_label, stretch=1)

        # Label para traducción (Columna derecha)
        self._translation_label = QLabel()
        self._translation_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._translation_label.setWordWrap(True)
        self._translation_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        layout.addWidget(self._translation_label, stretch=1)

        self.set_dual_column_mode(self._is_dual_column)
        self._update_style()

    def set_dual_column_mode(self, dual: bool) -> None:
        """Actualiza el modo del label (1 columna o 2 columnas)"""
        self._is_dual_column = dual

        if dual:
            self._original_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        else:
            self._original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._update_translation_visibility()

    def setText(self, text: str) -> None:
        """Establece el texto original."""
        self._original_label.setText(text)

    def setTranslation(self, translation: str) -> None:
        """Establece la traducción o su estado de carga para prevalecer el espacio."""
        if translation:
            self._has_translation_data = True
            self._translation_label.setText(translation)
        else:
            self._has_translation_data = False
            self._translation_label.setText(
                "Traduciendo..." if self._is_current else ""
            )

        self._update_translation_visibility()
        self._update_style()

    def _update_translation_visibility(self) -> None:
        """Evalúa si el label derecho debe verse (depende del layout y settings)."""
        if self._translation_visible and self._is_dual_column:
            self._translation_label.show()
        else:
            self._translation_label.hide()

    def text(self) -> str:
        """Retorna el texto original."""
        return self._original_label.text()

    def set_current(self, is_current: bool) -> None:
        """Marca esta línea como actual o no."""
        self._is_current = is_current

        if not self._has_translation_data:
            self._translation_label.setText(
                "Traduciendo..." if self._is_current else ""
            )

        self._update_style()

    def set_dim(self, is_dim: bool) -> None:
        """Atenúa la línea."""
        # Evitar que las líneas de contexto queden demasiado transparentes.
        self._opacity = 0.7 if is_dim else 1.0
        self._update_style()

    def set_translation_visible(self, visible: bool) -> None:
        """Muestra u oculta la traducción (global)."""
        self._translation_visible = visible
        self._update_translation_visibility()

    def set_line_info(self, index: int, timestamp_ms: int) -> None:
        """Establece la información de la línea para sincronización."""
        self._real_line_index = index
        self._timestamp_ms = timestamp_ms

    def clear_line_info(self) -> None:
        """Limpia la información de la línea."""
        self._real_line_index = -1
        self._timestamp_ms = 0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Maneja el clic del mouse para sincronizar."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._real_line_index >= 0 and self.text():
                self.line_clicked.emit(self._real_line_index, self._timestamp_ms)
                event.accept()
                return
        # Propagar el evento al padre
        event.ignore()

    def enterEvent(self, event) -> None:
        """Resalta la línea al pasar el mouse."""
        if self.text() and self._real_line_index >= 0:
            self._original_label.setStyleSheet(
                self._original_label.styleSheet()
                + "background-color: rgba(255, 255, 255, 0.1); border-radius: 8px;"
            )
            self._original_label.setGraphicsEffect(None)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Quita el resaltado al salir el mouse."""
        self._update_style()
        super().leaveEvent(event)

    def _update_style(self) -> None:
        """Actualiza el estilo visual."""
        if self._is_current:
            self._original_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self._config.highlight_color};
                    font-weight: 700;
                    font-size: {self._config.font_size + 8}px;
                }}
            """
            )
            self._original_label.setGraphicsEffect(None)

            # Traducción más visible cuando es línea actual
            if self._translation_visible and self._is_dual_column:
                self._translation_label.setGraphicsEffect(None)
                color = (
                    "rgba(255, 255, 255, 0.9)"
                    if self._has_translation_data
                    else "rgba(255, 255, 255, 0.4)"
                )
                style = "normal" if self._has_translation_data else "italic"
                self._translation_label.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {color};
                        font-size: {self._config.translation_font_size + 4}px;
                        font-weight: 500;
                        font-style: {style};
                    }}
                """
                )
        else:
            self._original_label.setStyleSheet(
                f"""
                QLabel {{
                    color: rgba(255, 255, 255, {self._opacity * 0.4});
                    font-weight: 400;
                    font-size: {self._config.font_size}px;
                }}
            """
            )
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(1.5)
            self._original_label.setGraphicsEffect(blur)

            # Traducción atenuada para líneas de contexto
            if self._translation_visible and self._is_dual_column:
                t_blur = QGraphicsBlurEffect()
                t_blur.setBlurRadius(1.5)
                self._translation_label.setGraphicsEffect(t_blur)

                color = (
                    "rgba(255, 255, 255, 0.3)"
                    if self._has_translation_data
                    else "rgba(255, 255, 255, 0.15)"
                )
                style = "normal" if self._has_translation_data else "italic"
                self._translation_label.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {color};
                        font-size: {self._config.translation_font_size}px;
                        font-weight: 400;
                        font-style: {style};
                    }}
                """
                )


class SyncTimeDialog(QDialog):
    """Diálogo para establecer el tiempo de sincronización manualmente."""

    def __init__(self, parent=None, current_position_ms: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Sincronizar Letra")
        self.setFixedSize(280, 150)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)

        # Estilo oscuro
        self.setStyleSheet(
            """
            QDialog {
                background-color: #1a1a2e;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #2a2a4e;
                color: white;
                border: 1px solid #00d4ff;
                border-radius: 5px;
                padding: 8px;
                font-size: 18px;
                font-family: monospace;
            }
            QLineEdit:focus {
                border: 2px solid #00d4ff;
            }
            QPushButton {
                background-color: #00d4ff;
                color: #1a1a2e;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00a8cc;
            }
            QPushButton:pressed {
                background-color: #008899;
            }
            QPushButton#cancelBtn {
                background-color: #444;
                color: white;
            }
            QPushButton#cancelBtn:hover {
                background-color: #555;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Instrucción
        label = QLabel("Ingresa el tiempo actual de la canción:")
        layout.addWidget(label)

        # Sub-label de ayuda contextual (H2)
        help_label = QLabel("Formato mm:ss — sirve para sincronizar las letras")
        help_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(help_label)

        # Campo de tiempo
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("mm:ss")
        self.time_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Mostrar tiempo actual como valor inicial
        current_min = current_position_ms // 60000
        current_sec = (current_position_ms % 60000) // 1000
        self.time_input.setText(f"{current_min:02d}:{current_sec:02d}")
        self.time_input.selectAll()

        layout.addWidget(self.time_input)

        # Botones
        button_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)

        self._ok_btn = QPushButton("Sincronizar")
        self._ok_btn.clicked.connect(self.accept)
        self._ok_btn.setDefault(True)

        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self._ok_btn)
        layout.addLayout(button_layout)

        # Enter para aceptar
        self.time_input.returnPressed.connect(self.accept)

        # Validación en tiempo real (H5)
        self.time_input.textChanged.connect(self._validate_input)
        self._validate_input(self.time_input.text())

    def _validate_input(self, text: str) -> None:
        """Valida el formato mm:ss y actualiza visual del campo."""
        valid = self._is_valid_time(text)
        self._ok_btn.setEnabled(valid)
        border_color = "#00d4ff" if valid else "#ff4444"
        self.time_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: #2a2a4e;
                color: white;
                border: 2px solid {border_color};
                border-radius: 5px;
                padding: 8px;
                font-size: 18px;
                font-family: monospace;
            }}
        """
        )

    @staticmethod
    def _is_valid_time(text: str) -> bool:
        """Devuelve True si el texto es un tiempo válido (mm:ss o ss)."""
        import re

        text = text.strip()
        if re.match(r"^\d{1,3}:\d{2}$", text):
            parts = text.split(":")
            return 0 <= int(parts[1]) < 60
        if re.match(r"^\d{1,5}$", text):
            return True
        return False

    def get_time_ms(self) -> Optional[int]:
        """
        Parsea el tiempo ingresado y lo retorna en milisegundos.

        Returns:
            Tiempo en ms o None si el formato es inválido.
        """
        text = self.time_input.text().strip()

        # Soportar formatos: mm:ss, m:ss, ss
        try:
            if ":" in text:
                parts = text.split(":")
                if len(parts) == 2:
                    minutes = int(parts[0])
                    seconds = int(parts[1])
                    return (minutes * 60 + seconds) * 1000
            else:
                # Solo segundos
                seconds = int(text)
                return seconds * 1000
        except ValueError:
            return None

        return None


class LyricsOverlay(QWidget):
    """
    Overlay transparente para mostrar letras sincronizadas.

    Signals:
        closed: Emitido cuando se cierra el overlay
        move_requested: Emitido cuando se solicita mover
        sync_time_changed: Emitido cuando el usuario establece un nuevo tiempo (ms)
    """

    closed = pyqtSignal()
    move_requested = pyqtSignal()
    sync_time_changed = pyqtSignal(int)  # Tiempo en milisegundos
    quit_requested = pyqtSignal()  # Solicitud de cerrar la aplicación

    def __init__(self, config: Optional[OverlayConfig] = None):
        super().__init__()

        self.config = config or OverlayConfig()
        self._lyrics: Optional[LyricsData] = None
        self._current_line_index: int = -1
        self._current_position_ms: int = 0  # Para mostrar en el diálogo
        self._drag_position: Optional[QPoint] = None
        self._resize_edge: Optional[str] = None  # Para redimensionar desde esquinas
        self._resize_start_rect: Optional[tuple] = None

        # Estado de scroll manual
        self._manual_scroll_mode: bool = False
        self._manual_line_index: int = 0

        # Estado de maximización
        self._is_maximized: bool = False
        self._normal_size: Optional[QSize] = None  # Tamaño normal antes de maximizar
        self._max_width: int = 1000  # Ancho máximo
        self._max_height: int = 600  # Alto máximo
        self._is_dual_column: bool = False

        # Control de líneas dinámicas
        self._last_calculated_lines: int = 0  # Último número de líneas calculado
        self._pending_sync_state: Optional[SyncState] = (
            None  # Estado pendiente de aplicar
        )

        self._setup_window()
        self._setup_ui()

        # Timer para ocultar indicadores temporales
        self._indicator_timer = QTimer()
        self._indicator_timer.timeout.connect(self._hide_indicator)
        self._indicator_timer.setSingleShot(True)

        # Timer para volver al modo sincronizado automáticamente
        self._manual_scroll_timer = QTimer()
        self._manual_scroll_timer.timeout.connect(self._exit_manual_scroll_mode)
        self._manual_scroll_timer.setSingleShot(True)

        # Habilitar tracking del mouse para cambiar cursor en bordes
        self.setMouseTracking(True)

        # Calcular líneas iniciales basado en el tamaño de la ventana
        self._recalculate_visible_lines()

    def _setup_window(self) -> None:
        """Configura las propiedades de la ventana."""
        # Flags de ventana - importante: WindowDoesNotAcceptFocus evita que tome el foco
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # No aparece en taskbar
            | Qt.WindowType.WindowDoesNotAcceptFocus  # No tomar foco al interactuar
        )

        # Fondo transparente
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # No tomar foco al mostrar (importante para no interrumpir la app de música)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Deshabilitar el escalado automático de DPI para mantener tamaño físico
        if hasattr(Qt.WidgetAttribute, "WA_ForceDisabledDpiScaling"):
            self.setAttribute(Qt.WidgetAttribute.WA_ForceDisabledDpiScaling)
        # Tamaño - usar resize en lugar de setFixedSize para evitar conflictos con Windows
        self.resize(self.config.width, self.config.height)

        # Posición inicial (centrado en la parte inferior)
        screen = self.screen()
        if screen:
            screen_rect = screen.availableGeometry()
            x = (screen_rect.width() - self.config.width) // 2
            y = screen_rect.height() - self.config.height - 100  # 100px desde abajo
            self.move(x, y)

    def _setup_ui(self) -> None:
        """Configura la interfaz de usuario."""
        # Layout principal
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Container con fondo
        self.container = QFrame()
        self.container.setObjectName("container")
        self.container.setStyleSheet(
            f"""
            QFrame#container {{
                background-color: {self.config.bg_color};
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }}
        """
        )

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(
            20, 5, 5, 15
        )  # Menos margen arriba y derecha para el botón
        container_layout.setSpacing(8)

        # Botón de cerrar en esquina superior derecha
        close_btn_layout = QHBoxLayout()
        close_btn_layout.setContentsMargins(0, 0, 0, 0)
        close_btn_layout.addStretch()  # Empuja el botón a la derecha

        # Botón de minimizar
        self.min_btn = QPushButton("–")
        self.min_btn.setFixedSize(24, 24)
        self.min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 0.5);
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(100, 200, 255, 0.2);
                color: #00d4ff;
            }
        """
        )
        self.min_btn.clicked.connect(self.toggle_visibility)
        close_btn_layout.addWidget(self.min_btn)

        # Botón de maximizar
        self.max_btn = QPushButton("⬜")
        self.max_btn.setFixedSize(24, 24)
        self.max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 0.5);
                border: none;
                font-size: 12px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(100, 255, 100, 0.2);
                color: #00ff00;
            }
        """
        )
        self.max_btn.clicked.connect(self._on_maximize_clicked)
        close_btn_layout.addWidget(self.max_btn)

        # Botón de cerrar
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 0.5);
                border: none;
                font-size: 14px;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 100, 100, 0.3);
                color: #ff6666;
            }
        """
        )
        self.close_btn.clicked.connect(self._on_close_clicked)
        close_btn_layout.addWidget(self.close_btn)

        container_layout.addLayout(close_btn_layout)

        # Header con info de canción (separado del botón) — arrastrable con click izq. (H4)
        self.header = QLabel()
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header.setStyleSheet(
            """
            QLabel {
                color: rgba(255, 255, 255, 0.6);
                font-size: 11px;
                padding: 2px;
            }
            QLabel:hover {
                color: rgba(255, 255, 255, 0.9);
                background-color: rgba(255,255,255,0.04);
                border-radius: 4px;
            }
        """
        )
        self.header.setCursor(Qt.CursorShape.OpenHandCursor)
        self.header.hide()
        container_layout.addWidget(self.header)

        # Área de letras con QScrollArea incrustada para evitar cortes (H8 modificado)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        self.lyrics_container = QWidget()
        self.lyrics_container.setStyleSheet("QWidget { background: transparent; }")
        self.lyrics_layout = QVBoxLayout(self.lyrics_container)
        self.lyrics_layout.setContentsMargins(0, 0, 0, 0)
        self.lyrics_layout.setSpacing(4)

        self.scroll_area.setWidget(self.lyrics_container)

        # Lista de labels para las líneas (se crean dinámicamente)
        self.line_labels: list[LyricLabel] = []

        # Crear labels iniciales
        self._create_line_labels()

        container_layout.addWidget(
            self.scroll_area, 1
        )  # stretch=1 para que ocupe espacio disponible

        # Footer premium (H8: remodelado)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(10, 10, 10, 0)
        footer_layout.setSpacing(15)

        # Cover art placeholder / icon
        self.cover_icon = QLabel("🎵")
        self.cover_icon.setFixedSize(48, 48)
        self.cover_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_icon.setStyleSheet(
            """
            QLabel {
                background-color: #1ed760;
                color: #000000;
                border-radius: 8px;
                font-size: 24px;
            }
        """
        )
        footer_layout.addWidget(self.cover_icon)

        # Track Info (Title + Artist stacked)
        track_info_layout = QVBoxLayout()
        track_info_layout.setSpacing(2)
        track_info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.track_title_label = QLabel("Esperando música...")
        self.track_title_label.setStyleSheet(
            "color: white; font-weight: bold; font-size: 16px;"
        )
        track_info_layout.addWidget(self.track_title_label)

        self.track_artist_label = QLabel("-")
        self.track_artist_label.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        track_info_layout.addWidget(self.track_artist_label)

        footer_layout.addLayout(track_info_layout)

        # Progress Block (Time + Scroll + Time)
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(10)
        progress_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.time_label = QLabel("00:00")
        self.time_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; font-variant-numeric: tabular-nums;"
        )
        progress_layout.addWidget(self.time_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #ffffff;
                border-radius: 2px;
            }
        """
        )
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(100)
        progress_layout.addWidget(self.progress_bar, 1)

        self.duration_label = QLabel("00:00")
        self.duration_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; font-variant-numeric: tabular-nums;"
        )
        progress_layout.addWidget(self.duration_label)

        footer_layout.addLayout(progress_layout, 1)  # stretch 1

        # Right controls layout
        right_controls = QHBoxLayout()
        right_controls.setSpacing(8)
        right_controls.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )

        # Botón "↩ Auto"
        self._back_to_auto_btn = QPushButton("↩ Auto")
        self._back_to_auto_btn.setFixedHeight(24)
        self._back_to_auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_to_auto_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
                border: none;
                border-radius: 12px;
                font-size: 11px;
                padding: 0 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
        """
        )
        self._back_to_auto_btn.clicked.connect(self._exit_manual_scroll_mode)
        self._back_to_auto_btn.hide()
        right_controls.addWidget(self._back_to_auto_btn)

        # Indicador temporal de offset / traducción
        self.offset_indicator = QLabel()
        self.offset_indicator.setContentsMargins(10, 4, 10, 4)
        self.offset_indicator.setStyleSheet(
            """
            QLabel {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
                border-radius: 12px;
                font-size: 11px;
                font-weight: bold;
            }
        """
        )
        self.offset_indicator.hide()
        right_controls.addWidget(self.offset_indicator)

        # Indicador de modo sync
        self.sync_indicator = QLabel()
        self.sync_indicator.setContentsMargins(10, 4, 10, 4)
        self.sync_indicator.setStyleSheet(
            """
            QLabel {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
                border-radius: 12px;
                font-size: 11px;
            }
        """
        )
        self.sync_indicator.hide()
        right_controls.addWidget(self.sync_indicator)

        self.progress_label = QLabel()
        self.progress_label.hide()
        right_controls.addWidget(self.progress_label)

        footer_layout.addLayout(right_controls)

        container_layout.addLayout(footer_layout)

        main_layout.addWidget(self.container)

        # Mensaje inicial
        self._show_message("🎵 Esperando música...")

    def _calculate_visible_lines(self) -> int:
        """
        Calcula el número de líneas visibles sugeridas. En ScrollArea se pueden
        acumular más pero esto define la ventana simétrica original.
        """
        available_height = self.height() - self.config.header_footer_height

        # Valor estricto más grande si es pantalla maximizada
        if self._is_maximized:
            base_height = self.config.line_height_with_translation
        else:
            base_height = self.config.line_height_without_translation

        # Calcular cuántas líneas caben mínimo
        num_lines = max(self.config.min_visible_lines, available_height // base_height)

        # Asegurar número impar para tener una línea central
        if num_lines % 2 == 0:
            num_lines -= 1

        return max(self.config.min_visible_lines, num_lines)

    def _recalculate_visible_lines(self) -> None:
        """
        Recalcula y actualiza el número de líneas visibles según el tamaño de la ventana.
        Recrea los labels si es necesario.
        """
        new_total_lines = self._calculate_visible_lines()

        if new_total_lines != self._last_calculated_lines:
            self._last_calculated_lines = new_total_lines

            # Calcular lines_before y lines_after (distribución simétrica)
            context_lines = (new_total_lines - 1) // 2
            self.config.lines_before = context_lines
            self.config.lines_after = context_lines

            logger.debug(
                f"Recalculando líneas visibles: {new_total_lines} total "
                f"({context_lines} antes, 1 actual, {context_lines} después)"
            )

            # Recrear los labels
            self._create_line_labels()

            # Re-aplicar estado si tenemos letras cargadas
            if self._lyrics is not None:
                if self._manual_scroll_mode:
                    self._update_manual_display()
                elif self._pending_sync_state is not None:
                    self._apply_sync_state(self._pending_sync_state)
                elif self._current_line_index >= 0:
                    # Crear un estado temporal para refrescar
                    self._refresh_current_display()

    def _create_line_labels(self) -> None:
        """
        Crea o recrea los labels de líneas según la configuración actual.
        """
        self._last_rendered_line_idx = -1  # Invalidar caché de redibujo

        # Limpiar labels existentes
        for label in self.line_labels:
            label.line_clicked.disconnect(self._on_line_clicked)
            self.lyrics_layout.removeWidget(label)
            label.deleteLater()
        self.line_labels.clear()

        # Crear nuevos labels
        total_lines = self.config.lines_before + 1 + self.config.lines_after

        for i in range(total_lines):
            label = LyricLabel(self.config, is_dual_column=self._is_dual_column)
            label.line_clicked.connect(self._on_line_clicked)
            self.line_labels.append(label)
            self.lyrics_layout.addWidget(label)

        logger.debug(f"Creados {total_lines} labels de línea")

    def _refresh_current_display(self) -> None:
        """
        Refresca la visualización actual sin estado de sincronización.
        """
        if self._lyrics is None or self._current_line_index < 0:
            return

        context = self._lyrics.get_context_lines(
            self._current_line_index,
            before=self.config.lines_before,
            after=self.config.lines_after,
        )

        # Limpiar todas las líneas
        for label in self.line_labels:
            label.setText("")
            label.setTranslation("")
            label.set_current(False)
            label.set_dim(False)
            label.clear_line_info()

        center_idx = self.config.lines_before

        for relative_idx, line in context:
            label_idx = center_idx + relative_idx

            if 0 <= label_idx < len(self.line_labels):
                label = self.line_labels[label_idx]
                label.setText(line.text)
                real_index = self._current_line_index + relative_idx
                label.set_line_info(real_index, line.timestamp_ms)
                if hasattr(line, "translation") and line.translation:
                    label.setTranslation(line.translation)
                label.set_current(relative_idx == 0)
                label.set_dim(relative_idx != 0)

    def _show_message(self, message: str) -> None:
        """Muestra un mensaje centrado."""
        # Ocultar todas las líneas excepto la central
        center_idx = self.config.lines_before

        for i, label in enumerate(self.line_labels):
            if i == center_idx:
                label.setText(message)
                label.setStyleSheet(
                    """
                    QLabel {
                        color: rgba(255, 255, 255, 0.7);
                        font-size: 16px;
                    }
                """
                )
                label.show()
            else:
                label.setText("")
                label.hide()

        self.progress_label.setText("")
        self.sync_indicator.setText("")

    def set_lyrics(self, lyrics: Optional[LyricsData]) -> None:
        """
        Establece las letras a mostrar y actualiza la vista inmediatamente.
        Elimina cualquier mensaje de estado y muestra la letra aunque la canción esté en introducción instrumental.
        Args:
            lyrics: Datos de letras o None para limpiar.
        """
        self._lyrics = lyrics
        self._current_line_index = -1
        self._last_rendered_line_idx = -1  # Forzar renderizado profundo la próxima vez

        # Si no hay letras, mostrar mensaje de espera
        if lyrics is None or not lyrics.lines:
            self._show_message("🎵 Esperando música...")
            return

        # Mostrar todas las líneas
        for label in self.line_labels:
            label.show()

        # Actualizar footer con info de la canción
        if lyrics.title and lyrics.artist:
            self.track_title_label.setText(lyrics.title)
            self.track_artist_label.setText(lyrics.artist)
            self.header.hide()
        else:
            self.track_title_label.setText("Desconocido")
            self.track_artist_label.setText("-")
            self.header.hide()

        # Calcular duración total si hay líneas
        if lyrics.lines:
            last_line = lyrics.lines[-1]
            total_time_ms = last_line.timestamp_ms + 5000  # 5 segs extra
            minutes = total_time_ms // 60000
            seconds = (total_time_ms % 60000) // 1000
            self.duration_label.setText(f"{minutes:02d}:{seconds:02d}")
            self.progress_bar.setRange(0, total_time_ms)

        # Eliminar cualquier mensaje de estado (como 'Buscando letra')
        self.progress_label.setText("")
        self.sync_indicator.setText("")

        # Refrescar la visualización para mostrar la letra desde el inicio
        self._current_line_index = 0
        self._refresh_current_display()

        logger.info(f"Letras cargadas: {len(lyrics.lines)} líneas")

    def update_sync(self, state: SyncState) -> None:
        """
        Actualiza la visualización según el estado de sincronización.

        Args:
            state: Estado actual de sincronización.
        """
        if self._lyrics is None or not self._lyrics.lines:
            return

        self._current_line_index = state.current_line_index
        self._current_position_ms = state.position_ms  # Guardar posición actual
        self._pending_sync_state = state  # Guardar para posible re-aplicación

        # Si estamos en modo scroll manual, no actualizar automáticamente
        if self._manual_scroll_mode:
            return

        self._apply_sync_state(state)

    def _apply_sync_state(self, state: SyncState) -> None:
        """
        Aplica el estado de sincronización a la visualización.

        Args:
            state: Estado de sincronización a aplicar.
        """
        if self._lyrics is None or not self._lyrics.lines:
            return

        # Solo reconstruir el layout de letras si el índice cambió o no hay caché
        needs_layout_update = (
            getattr(self, "_last_rendered_line_idx", -1) != state.current_line_index
        )

        if needs_layout_update:
            self._last_rendered_line_idx = state.current_line_index

            # Obtener líneas de contexto
            context = self._lyrics.get_context_lines(
                state.current_line_index,
                before=self.config.lines_before,
                after=self.config.lines_after,
            )

            # Limpiar todas las líneas
            for label in self.line_labels:
                label.setText("")
                label.setTranslation("")
                label.set_current(False)
                label.set_dim(False)
                label.clear_line_info()

            # Mapear contexto a labels
            center_idx = self.config.lines_before

            for relative_idx, line in context:
                label_idx = center_idx + relative_idx

                if 0 <= label_idx < len(self.line_labels):
                    label = self.line_labels[label_idx]
                    label.setText(line.text)
                    # Establecer información de la línea para sincronización por clic
                    real_index = state.current_line_index + relative_idx
                    label.set_line_info(real_index, line.timestamp_ms)
                    # Pasar traducción si existe
                    if hasattr(line, "translation") and line.translation:
                        label.setTranslation(line.translation)
                    label.set_current(relative_idx == 0)
                    label.set_dim(relative_idx != 0)

            # Trigger layout update prior to scrolling logic (H4 scrolling adjustment)
            self.lyrics_container.adjustSize()
            self._ensure_center_visible(center_idx)

        # Actualizar indicadores — formato compacto (H8)
        if self.config.show_progress:
            current, total = state.current_line_index + 1, len(self._lyrics.lines)
            self.progress_label.setText(f"{current}/{total}")

        # Actualizar tiempo actual en la parte inferior derecha
        minutes = state.position_ms // 60000
        seconds = (state.position_ms % 60000) // 1000
        self.time_label.setText(f"{minutes:02d}:{seconds:02d}")

        if hasattr(self, "progress_bar") and self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(
                min(state.position_ms, self.progress_bar.maximum())
            )

        # Sync mode: solo mostrar temporalmente cuando cambia (H8)
        if self.config.show_sync_mode:
            mode_text = "⏱ Sync" if state.mode == SyncMode.SYNCED else "📜 Estimado"
            if self.config.translation_enabled:
                mode_text += " 🌐"
            new_mode = mode_text
            if (
                not hasattr(self, "_last_sync_mode_text")
                or self._last_sync_mode_text != new_mode
            ):
                self._last_sync_mode_text = new_mode
                self.sync_indicator.setText(new_mode)
                # Ocultar después de 3 s
                if not hasattr(self, "_sync_mode_timer"):
                    self._sync_mode_timer = QTimer()
                    self._sync_mode_timer.setSingleShot(True)
                    self._sync_mode_timer.timeout.connect(
                        lambda: self.sync_indicator.setText("")
                    )
                self._sync_mode_timer.start(3000)

        # Ocultar botón "Auto" fuera de modo manual
        self._back_to_auto_btn.hide()

    def _ensure_center_visible(self, center_idx: int) -> None:
        """Ajusta dinámicamente el QScrollArea vertical para mantener la línea activa en el centro"""
        if 0 <= center_idx < len(self.line_labels):
            target_widget = self.line_labels[center_idx]
            # Usar QTimer simple shot para permitir al layout calcular dimensiones reales primero
            QTimer.singleShot(10, lambda: self._scroll_to_center(target_widget))

    def _scroll_to_center(self, target_widget: QWidget) -> None:
        """Aplica el valor del slider vertical para centrar el widget activo"""
        scroll_bar = self.scroll_area.verticalScrollBar()
        widget_y = target_widget.geometry().y()
        widget_h = target_widget.geometry().height()
        view_h = self.scroll_area.viewport().height()

        target_scroll = widget_y - (view_h // 2) + (widget_h // 2)
        scroll_bar.setValue(max(0, min(target_scroll, scroll_bar.maximum())))

    def show_offset_indicator(self, offset_ms: int) -> None:
        """Muestra temporalmente el indicador de offset."""
        sign = "+" if offset_ms >= 0 else ""
        self.offset_indicator.setText(f"Offset: {sign}{offset_ms}ms")
        self.offset_indicator.show()

        # Ocultar después de 2 segundos
        self._indicator_timer.start(2000)

    def _hide_indicator(self) -> None:
        """Oculta el indicador de offset."""
        self.offset_indicator.hide()

    def _on_close_clicked(self) -> None:
        """Maneja el click en el botón de cerrar."""
        logger.info("Botón cerrar presionado")
        self.quit_requested.emit()

    def _on_maximize_clicked(self) -> None:
        """Maneja el click en el botón de maximizar."""
        if not hasattr(self, "geom_anim"):
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QRect

            self.geom_anim = QPropertyAnimation(self, b"geometry")
            self.geom_anim.setDuration(400)
            self.geom_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self.geom_anim.setStartValue(self.geometry())

        if self._is_maximized:
            # Restaurar tamaño normal
            target_rect = getattr(self, "_normal_geom_rect", self.geometry())
            self.geom_anim.setEndValue(target_rect)
            self._is_maximized = False
            self.max_btn.setText("⬜")

            # Restaurar tamaños de fuente compactos
            self.config.font_size = 24
            self.config.translation_font_size = 14
            self.config.line_height_without_translation = 42
            self.config.line_height_with_translation = 64
            logger.info("Overlay restaurado a tamaño normal")
        else:
            # Maximizar a tamaño expandido (pantalla completa o casi)
            self._normal_geom_rect = self.geometry()
            screen = self.screen().availableGeometry()
            # Dejar 40px de margen en lugar de fullscreen total (comportamiento inmersivo)
            target_rect = screen.adjusted(40, 40, -40, -40)
            self.geom_anim.setEndValue(target_rect)
            self._is_maximized = True
            self.max_btn.setText("🗗")  # Icono de restaurar

            # Aumentar tamaño de fuentes
            self.config.font_size = 42
            self.config.translation_font_size = 22
            self.config.line_height_without_translation = 70
            self.config.line_height_with_translation = 100
            logger.info("Overlay maximizado a modo expandido")

        # Actualizar fuentes y layout de los labels
        for label in self.line_labels:
            label.set_dual_column_mode(self._is_maximized)
            label._update_style()

        self.geom_anim.start()

    def _show_sync_dialog(self) -> None:
        """Muestra el diálogo para establecer el tiempo de sincronización."""
        dialog = SyncTimeDialog(self, self._current_position_ms)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            time_ms = dialog.get_time_ms()
            if time_ms is not None:
                logger.info(f"Usuario estableció tiempo de sincronización: {time_ms}ms")
                self.sync_time_changed.emit(time_ms)

                # Mostrar confirmación
                minutes = time_ms // 60000
                seconds = (time_ms % 60000) // 1000
                self.offset_indicator.setText(
                    f"⏱ Sincronizado a {minutes:02d}:{seconds:02d}"
                )
                self.offset_indicator.show()
                self._indicator_timer.start(2000)

    # --- Detección de bordes para redimensionar ---

    def _get_edge_at_pos(self, pos: QPoint) -> Optional[str]:
        """
        Detecta si el cursor está en un borde/esquina para redimensionar.

        Returns:
            String indicando el borde ('right', 'bottom', 'corner') o None
        """
        margin = 12  # Píxeles de margen para detectar el borde
        rect = self.rect()

        at_right = pos.x() >= rect.width() - margin
        at_bottom = pos.y() >= rect.height() - margin
        at_left = pos.x() <= margin
        at_top = pos.y() <= margin

        # Esquinas tienen prioridad
        if at_right and at_bottom:
            return "corner_br"
        if at_left and at_bottom:
            return "corner_bl"
        if at_right and at_top:
            return "corner_tr"
        if at_left and at_top:
            return "corner_tl"

        # Luego bordes
        if at_right:
            return "right"
        if at_bottom:
            return "bottom"
        if at_left:
            return "left"
        if at_top:
            return "top"

        return None

    def _update_cursor_for_edge(self, edge: Optional[str]) -> None:
        """Actualiza el cursor según el borde."""
        if edge in ("corner_br", "corner_tl"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in ("corner_bl", "corner_tr"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edge in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in ("top", "bottom"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._drag_position is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()

    # --- Eventos de mouse para arrastrar y redimensionar ---

    def _is_in_header_area(self, pos: QPoint) -> bool:
        """Detecta si el cursor está sobre la zona del header (arrastrable)."""
        if not self.header.isVisible():
            # Si no hay header visible, la zona de arrastre es la franja superior (40px)
            return pos.y() <= 40
        header_geo = self.header.geometry()
        # Incluir un poco de margen alrededor del header
        return pos.y() <= header_geo.bottom() + 5

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Maneja el click del mouse."""
        # Click izquierdo: arrastrar desde header o redimensionar desde bordes (H4)
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            edge = self._get_edge_at_pos(pos)

            if edge:
                # Iniciar redimensionamiento
                self._resize_edge = edge
                self._resize_start_rect = (
                    self.geometry().x(),
                    self.geometry().y(),
                    self.geometry().width(),
                    self.geometry().height(),
                    event.globalPosition().toPoint(),
                )
                event.accept()
            elif self._is_in_header_area(pos):
                # Arrastrar ventana desde el header
                self._drag_position = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                self.header.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
            else:
                # Propagar para que LyricLabel reciba el click
                super().mousePressEvent(event)

        elif event.button() == Qt.MouseButton.MiddleButton:
            pos = event.position().toPoint()
            edge = self._get_edge_at_pos(pos)

            if edge:
                self._resize_edge = edge
                self._resize_start_rect = (
                    self.geometry().x(),
                    self.geometry().y(),
                    self.geometry().width(),
                    self.geometry().height(),
                    event.globalPosition().toPoint(),
                )
            else:
                self._drag_position = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()

        elif event.button() == Qt.MouseButton.RightButton:
            # Click derecho: mostrar diálogo de sincronización
            self._show_sync_dialog()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Maneja el movimiento del mouse."""
        active_buttons = event.buttons()
        is_dragging = active_buttons in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        )

        if is_dragging:
            if self._resize_edge and self._resize_start_rect:
                self._do_resize(event.globalPosition().toPoint())
                event.accept()
            elif self._drag_position is not None:
                self.move(event.globalPosition().toPoint() - self._drag_position)
                event.accept()
        else:
            # Sin botón presionado: actualizar cursor según posición
            edge = self._get_edge_at_pos(event.position().toPoint())
            self._update_cursor_for_edge(edge)

    def _do_resize(self, global_pos: QPoint) -> None:
        """Ejecuta el redimensionamiento."""
        if not self._resize_start_rect:
            return

        x, y, w, h, start_pos = self._resize_start_rect
        dx = global_pos.x() - start_pos.x()
        dy = global_pos.y() - start_pos.y()

        min_w, min_h = 300, 100  # Tamaño mínimo
        max_w, max_h = 1200, 600  # Tamaño máximo

        new_x, new_y, new_w, new_h = x, y, w, h

        edge = self._resize_edge

        # Calcular nuevas dimensiones según el borde
        if edge in ("right", "corner_br", "corner_tr"):
            new_w = max(min_w, min(max_w, w + dx))
        if edge in ("left", "corner_bl", "corner_tl"):
            new_w = max(min_w, min(max_w, w - dx))
            new_x = x + w - new_w
        if edge in ("bottom", "corner_br", "corner_bl"):
            new_h = max(min_h, min(max_h, h + dy))
        if edge in ("top", "corner_tr", "corner_tl"):
            new_h = max(min_h, min(max_h, h - dy))
            new_y = y + h - new_h

        self.setGeometry(new_x, new_y, new_w, new_h)

        # Recalcular líneas visibles después de redimensionar
        self._recalculate_visible_lines()

    def resizeEvent(self, event) -> None:
        """
        Maneja el evento de redimensionamiento de la ventana.
        Recalcula el número de líneas visibles dinámicamente.
        """
        super().resizeEvent(event)

        # Actualizar layout/columnas solo si el estado cambió
        new_is_dual_column = self._is_maximized
        if new_is_dual_column != self._is_dual_column:
            self._is_dual_column = new_is_dual_column
            self._last_calculated_lines = 0
            for label in self.line_labels:
                label.set_dual_column_mode(self._is_dual_column)

        # Recalcular líneas visibles cuando cambia el tamaño
        self._recalculate_visible_lines()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Maneja cuando se suelta el mouse."""
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._drag_position = None
            self._resize_edge = None
            self._resize_start_rect = None

            # Restaurar cursor del header
            if self.header.isVisible():
                self.header.setCursor(Qt.CursorShape.OpenHandCursor)

            # Actualizar cursor según posición actual
            edge = self._get_edge_at_pos(event.position().toPoint())
            self._update_cursor_for_edge(edge)
            event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Maneja el scroll de la rueda del mouse para navegar por las letras."""
        if self._lyrics is None or not self._lyrics.lines:
            event.ignore()
            return

        # Determinar dirección del scroll
        delta = event.angleDelta().y()

        if delta == 0:
            event.ignore()
            return

        # Activar modo scroll manual
        if not self._manual_scroll_mode:
            self._manual_scroll_mode = True
            self._manual_line_index = self._current_line_index

        # Navegar entre líneas
        if delta > 0:
            # Scroll arriba = línea anterior
            self._manual_line_index = max(0, self._manual_line_index - 1)
        else:
            # Scroll abajo = línea siguiente
            self._manual_line_index = min(
                len(self._lyrics.lines) - 1, self._manual_line_index + 1
            )

        # Actualizar visualización con la línea manual
        self._update_manual_display()

        # Reiniciar timer para volver a modo sincronizado
        self._manual_scroll_timer.start(self.config.manual_scroll_timeout_s * 1000)

        event.accept()

    def _update_manual_display(self) -> None:
        """Actualiza la visualización en modo scroll manual."""
        if self._lyrics is None:
            return

        # Obtener líneas de contexto para la línea manual
        context = self._lyrics.get_context_lines(
            self._manual_line_index,
            before=self.config.lines_before,
            after=self.config.lines_after,
        )

        # Limpiar todas las líneas
        for label in self.line_labels:
            label.setText("")
            label.setTranslation("")
            label.set_current(False)
            label.set_dim(False)
            label.clear_line_info()

        # Mapear contexto a labels
        center_idx = self.config.lines_before

        for relative_idx, line in context:
            label_idx = center_idx + relative_idx

            if 0 <= label_idx < len(self.line_labels):
                label = self.line_labels[label_idx]
                label.setText(line.text)
                # Establecer información de la línea para sincronización por clic
                real_index = self._manual_line_index + relative_idx
                label.set_line_info(real_index, line.timestamp_ms)
                if hasattr(line, "translation") and line.translation:
                    label.setTranslation(line.translation)
                label.set_current(relative_idx == 0)
                label.set_dim(relative_idx != 0)

        # Mostrar indicador de modo manual + botón "Auto" (H3)
        current = self._manual_line_index + 1
        total = len(self._lyrics.lines)
        self.progress_label.setText(f"{current}/{total}")
        self.sync_indicator.setText("📜 Manual")
        self._back_to_auto_btn.show()

        # Mostrar tiempo de la línea actual en el label de tiempo
        current_line = self._lyrics.lines[self._manual_line_index]
        time_sec = current_line.timestamp_ms // 1000
        minutes = time_sec // 60
        seconds = time_sec % 60
        self.time_label.setText(f"{minutes:02d}:{seconds:02d}")
        self.offset_indicator.setText(f"⏱ {minutes:02d}:{seconds:02d}")
        self.offset_indicator.show()

    def _exit_manual_scroll_mode(self) -> None:
        """Sale del modo scroll manual y vuelve a sincronización automática."""
        self._manual_scroll_mode = False
        self._manual_scroll_timer.stop()
        self.offset_indicator.hide()
        self._back_to_auto_btn.hide()
        self.sync_indicator.setText("")
        logger.info("Volviendo a modo sincronizado automáticamente")

    def _on_line_clicked(self, line_index: int, timestamp_ms: int) -> None:
        """
        Maneja el clic en una línea para sincronizar la reproducción.

        Args:
            line_index: Índice de la línea en la lista de letras.
            timestamp_ms: Timestamp de la línea en milisegundos.
        """
        if self._lyrics is None:
            return

        # Salir del modo scroll manual si estamos en él
        self._manual_scroll_mode = False
        self._manual_scroll_timer.stop()

        # Emitir señal para sincronizar la reproducción
        logger.info(f"Clic en línea {line_index}: sincronizando a {timestamp_ms}ms")
        self.sync_time_changed.emit(timestamp_ms)

        # Mostrar confirmación visual
        minutes = timestamp_ms // 60000
        seconds = (timestamp_ms % 60000) // 1000
        self.offset_indicator.setText(f"🎯 Sincronizado a {minutes:02d}:{seconds:02d}")
        self.offset_indicator.show()
        self._indicator_timer.start(2000)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Dibuja el fondo transparente."""
        # El fondo se maneja via stylesheet del container
        pass

    # --- API pública adicional ---

    def toggle_visibility(self) -> bool:
        """
        Alterna la visibilidad del overlay.

        Returns:
            True si ahora es visible, False si está oculto.
        """
        if self.isVisible():
            self.hide()
            return False
        else:
            self.show()
            return True

    def toggle_translation(self) -> bool:
        """
        Alterna la visibilidad de las traducciones.

        Returns:
            True si las traducciones están visibles, False si están ocultas.
        """
        self.config.translation_enabled = not self.config.translation_enabled

        # Actualizar todos los labels
        for label in self.line_labels:
            label.set_translation_visible(self.config.translation_enabled)

        # Recalcular líneas visibles (cambia la altura por línea)
        self._recalculate_visible_lines()

        # Mostrar indicador temporal
        status = (
            "🌐 Traducción ON"
            if self.config.translation_enabled
            else "🌐 Traducción OFF"
        )
        self.offset_indicator.setText(status)
        self.offset_indicator.show()
        self._indicator_timer.start(2000)

        logger.info(
            f"Traducción {'habilitada' if self.config.translation_enabled else 'deshabilitada'}"
        )
        return self.config.translation_enabled

    def set_no_lyrics_available(self, artist: str = "", title: str = "") -> None:
        """Muestra mensaje de que no hay letras disponibles con sugerencia (H9)."""
        msg = "📝 Letra no disponible"
        if artist and title:
            msg = f"📝 Letra no disponible para {artist} - {title}"
        self._show_message(msg)
        # Sugerencia en sync_indicator
        self.sync_indicator.setText("Click derecho para sincronizar manualmente")

    def set_searching_lyrics(self, source: str = "") -> None:
        """Muestra mensaje de búsqueda en progreso (H1)."""
        if source:
            self._show_message(f"🔍 Buscando en {source}...")
        else:
            self._show_message("🔍 Buscando letra...")

    def set_translating(self) -> None:
        """Muestra indicador temporal de traducción en progreso (H1)."""
        self.offset_indicator.setText("🌐 Traduciendo...")
        self.offset_indicator.show()

    def set_translation_done(self) -> None:
        """Oculta el indicador de traducción en progreso."""
        self.offset_indicator.setText("🌐 Traducción lista")
        self.offset_indicator.show()
        self._indicator_timer.start(2000)

    def set_track_info(self, artist: str, title: str) -> None:
        """
        Actualiza la info del track en el footer.

        Args:
            artist: Nombre del artista
            title: Título de la canción
        """
        self.track_title_label.setText(title)
        self.track_artist_label.setText(artist)
        self.header.hide()


# --- Demo standalone ---
def main():
    """Demo del overlay."""
    import sys
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer

    app = QApplication(sys.argv)

    # Crear overlay
    overlay = LyricsOverlay()
    overlay.show()

    # Simular letras
    from ..lrc_parser import LRCParser

    sample_lrc = """
[00:00.00]♪ Intro instrumental ♪
[00:12.00]This is the first line of the song
[00:17.20]And here comes the second line
[00:22.50]The melody continues to flow
[00:28.00]With words that touch the soul
[00:33.45]Building up to the chorus now
[00:38.90]Here we go, let's sing along
[00:44.00]The rhythm takes control tonight
[00:50.00]Dancing under starry lights
    """

    lyrics = LRCParser.parse(sample_lrc)
    lyrics.title = "Demo Song"
    lyrics.artist = "Demo Artist"

    # Timer para simular reproducción
    current_line = [0]

    def simulate_playback():
        if current_line[0] < len(lyrics.lines):
            from ..sync_engine import SyncState, SyncMode

            state = SyncState(
                mode=SyncMode.SYNCED,
                current_line_index=current_line[0],
                current_line=lyrics.lines[current_line[0]],
                position_ms=lyrics.lines[current_line[0]].timestamp_ms,
                is_playing=True,
                offset_ms=0,
            )

            overlay.update_sync(state)
            current_line[0] += 1

    # Esperar un poco y luego cargar letras
    QTimer.singleShot(1000, lambda: overlay.set_lyrics(lyrics))

    # Timer para simular avance de letras
    timer = QTimer()
    timer.timeout.connect(simulate_playback)
    QTimer.singleShot(1500, lambda: timer.start(3000))  # Una línea cada 3 segundos

    # Mostrar indicador de offset después de un rato
    QTimer.singleShot(5000, lambda: overlay.show_offset_indicator(500))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
