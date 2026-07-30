"""Ventana inmersiva para letras sincronizadas de Qobuz."""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QLineF,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..lrc_parser import LyricsData
from ..models import PlaybackInfo, PlayerState
from ..sync_engine import SyncMode, SyncState
from .brand import ACCENT_BLUE, ACCENT_PURPLE, create_brand_icon, draw_brand_mark

logger = logging.getLogger(__name__)


def _system_animations_enabled() -> bool:
    """Consulta la preferencia de animaciones del área cliente en Windows."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        enabled = wintypes.BOOL()
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x1042,  # SPI_GETCLIENTAREAANIMATION
            0,
            ctypes.byref(enabled),
            0,
        )
        return bool(enabled.value) if success else True
    except (AttributeError, OSError):
        return True


@dataclass
class OverlayConfig:
    """Configuración visual y de comportamiento de la ventana."""

    width: int = 0
    height: int = 0
    opacity: float = 1.0
    font_size: int = 24
    highlight_font_size: int = 48
    font_family: str = "Segoe UI Variable, Segoe UI"
    bg_color: str = "#080b1d"
    text_color: str = "#ffffff"
    highlight_color: str = "#ffffff"
    dim_color: str = "#aeb5cf"
    translation_enabled: bool = True
    translation_font_size: int = 18
    translation_color: str = "#8b5cf6"
    lines_before: int = 2
    lines_after: int = 2
    show_progress: bool = True
    show_sync_mode: bool = True
    manual_scroll_timeout_s: int = 5
    always_on_top: bool = False
    window_maximized: bool = False


def _format_time(milliseconds: int, unknown: str = "00:00") -> str:
    if milliseconds <= 0:
        return unknown
    total_seconds = milliseconds // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


class BrandMark(QWidget):
    """Marca vectorial del titlebar."""

    def sizeHint(self) -> QSize:
        return QSize(32, 32)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        draw_brand_mark(painter, QRectF(self.rect()).adjusted(2, 3, -2, -3))


class AmbientSurface(QFrame):
    """Superficie redondeada con fondo azul-negro y halos ambientales."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._background_opacity = 1.0
        self.setObjectName("ambientSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_background_opacity(self, opacity: float) -> None:
        self._background_opacity = max(0.65, min(1.0, opacity))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 14.0 if not self.window().isMaximized() else 0.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        opacity = self._background_opacity
        base.setColorAt(0.0, QColor(8, 11, 27, int(255 * opacity)))
        base.setColorAt(0.48, QColor(11, 16, 40, int(255 * opacity)))
        base.setColorAt(1.0, QColor(7, 10, 24, int(255 * opacity)))
        painter.fillPath(path, base)

        left_glow = QRadialGradient(
            rect.left() + rect.width() * 0.22,
            rect.top() + rect.height() * 0.52,
            rect.width() * 0.42,
        )
        left_glow.setColorAt(0.0, QColor(76, 73, 190, 32))
        left_glow.setColorAt(0.55, QColor(37, 53, 128, 18))
        left_glow.setColorAt(1.0, QColor(5, 8, 20, 0))
        painter.fillRect(rect, left_glow)

        center_glow = QRadialGradient(
            rect.center().x(),
            rect.top() + rect.height() * 0.53,
            rect.width() * 0.35,
        )
        center_glow.setColorAt(0.0, QColor(106, 77, 255, 28))
        center_glow.setColorAt(0.5, QColor(64, 84, 210, 12))
        center_glow.setColorAt(1.0, QColor(5, 8, 20, 0))
        painter.fillRect(rect, center_glow)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(91, 104, 154, 76), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)


class WaveformWidget(QWidget):
    """Ecualizador decorativo que pulsa suavemente durante la reproducción."""

    def __init__(self, mirrored: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mirrored = mirrored
        self._active = False
        self._playing = False
        self._phase = 0.0
        self.setFixedHeight(80)
        self.setMinimumWidth(90)
        self.setMaximumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._timer = QTimer(self)
        self._timer.setInterval(75)
        self._timer.timeout.connect(self._advance)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._update_timer()
        self.update()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self._update_timer()
        self.update()

    def _update_timer(self) -> None:
        if self._active and self._playing:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.24) % (math.pi * 2)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        heights = (0.18, 0.34, 0.58, 0.88, 0.53, 0.29, 0.16)
        if self._mirrored:
            heights = tuple(reversed(heights))

        usable_width = min(self.width() - 12, 150)
        start_x = (self.width() - usable_width) / 2
        gap = usable_width / max(1, len(heights) - 1)
        center_y = self.height() / 2
        gradient = QLinearGradient(start_x, 0, start_x + usable_width, 0)
        gradient.setColorAt(0.0, QColor(91, 68, 196, 120))
        gradient.setColorAt(0.5, ACCENT_PURPLE)
        gradient.setColorAt(1.0, ACCENT_BLUE)
        painter.setPen(
            QPen(
                gradient,
                max(2.0, self.width() / 75),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )

        for index, base_height in enumerate(heights):
            pulse = 1.0
            if self._playing:
                pulse += 0.12 * math.sin(self._phase + index * 0.72)
            half_height = self.height() * base_height * pulse / 2
            x = start_x + index * gap
            painter.drawLine(QLineF(x, center_y - half_height, x, center_y + half_height))


class FocusRule(QWidget):
    """Línea degradada y punto luminoso bajo la traducción activa."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._active = False
        self.setFixedHeight(22)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        margin = max(10, self.width() * 0.1)
        gradient = QLinearGradient(margin, 0, self.width() - margin, 0)
        gradient.setColorAt(0.0, QColor(91, 70, 210, 0))
        gradient.setColorAt(0.35, QColor(110, 79, 255, 190))
        gradient.setColorAt(0.5, QColor(139, 92, 246, 255))
        gradient.setColorAt(0.65, QColor(85, 105, 239, 180))
        gradient.setColorAt(1.0, QColor(85, 105, 239, 0))
        painter.setPen(QPen(gradient, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QLineF(margin, y, self.width() - margin, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(113, 76, 255, 55))
        painter.drawEllipse(QPoint(int(self.width() / 2), int(y)), 9, 9)
        painter.setBrush(QColor("#7c4dff"))
        painter.drawEllipse(QPoint(int(self.width() / 2), int(y)), 5, 5)


class LyricLabel(QWidget):
    """Fila responsive con original, traducción, foco y visualizadores laterales."""

    line_clicked = pyqtSignal(int, int)

    def __init__(self, config: OverlayConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._config = config
        self._real_line_index = -1
        self._timestamp_ms = 0
        self._current = False
        self._distance = 1
        self._translation_visible = config.translation_enabled
        self._translation_pending = False
        self._base_original_size = config.font_size
        self._base_active_size = config.highlight_font_size
        self._base_translation_size = config.translation_font_size
        self._animation: Optional[QPropertyAnimation] = None
        self._hovered = False
        self._keyboard_focused = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(18)

        self._left_wave = WaveformWidget(parent=self)
        outer.addWidget(self._left_wave, 2)

        text_host = QWidget(self)
        text_host.setMinimumWidth(320)
        text_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(2, 2, 2, 0)
        text_layout.setSpacing(7)

        self._original_label = QLabel()
        self._original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._original_label.setWordWrap(True)
        self._original_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(self._original_label)

        self._translation_label = QLabel(" ")
        self._translation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._translation_label.setWordWrap(True)
        self._translation_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(self._translation_label)

        self._focus_rule = FocusRule()
        text_layout.addWidget(self._focus_rule)
        outer.addWidget(text_host, 6)

        self._right_wave = WaveformWidget(mirrored=True, parent=self)
        outer.addWidget(self._right_wave, 2)
        self._apply_style()
        self._update_accessible_text()

    def _update_height_hint(self) -> None:
        """Asegura espacio suficiente para texto envuelto y su traducción."""
        if self._original_label.width() <= 0:
            return

        required_height = self._original_label.heightForWidth(
            self._original_label.width()
        )
        if self._translation_label.isVisible():
            required_height += self._translation_label.heightForWidth(
                self._translation_label.width()
            )
        required_height += 7  # separación entre original y traducción
        if self._focus_rule.isVisible():
            required_height += self._focus_rule.sizeHint().height() + 7

        base_height = 142 if self._current else 88
        self.setMinimumHeight(max(base_height, required_height + 4))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_height_hint()

    def set_responsive_sizes(
        self,
        original_size: int,
        active_size: int,
        translation_size: int,
    ) -> None:
        self._base_original_size = original_size
        self._base_active_size = active_size
        self._base_translation_size = translation_size
        self._apply_style()

    def setText(self, text: str) -> None:
        self._original_label.setText(text)
        self._apply_style()
        self._update_accessible_text()

    def text(self) -> str:
        return self._original_label.text()

    def setTranslation(self, translation: str, pending: bool = False) -> None:
        self._translation_pending = pending
        if translation:
            self._translation_label.setText(translation)
        elif pending and self._current:
            self._translation_label.setText("Traduciendo…")
        else:
            self._translation_label.setText(" ")
        self._apply_style()
        self._update_accessible_text()

    def set_current(self, current: bool) -> None:
        became_current = current and not self._current
        self._current = current
        self._left_wave.set_active(current)
        self._right_wave.set_active(current)
        self._focus_rule.set_active(current)
        if self._translation_pending and not self._translation_label.text().strip():
            self._translation_label.setText("Traduciendo…")
        self._apply_style()
        self._update_accessible_text()
        if became_current:
            self.animate_in()

    def set_dim(self, is_dim: bool, distance: int = 1) -> None:
        self._distance = max(1, distance) if is_dim else 0
        self._apply_style()

    def set_playing(self, playing: bool) -> None:
        self._left_wave.set_playing(playing)
        self._right_wave.set_playing(playing)

    def set_translation_visible(self, visible: bool) -> None:
        self._translation_visible = visible
        self._translation_label.setVisible(visible)
        self._focus_rule.setVisible(self._current and visible)
        self._apply_style()
        self._update_accessible_text()

    def set_line_info(self, index: int, timestamp_ms: int) -> None:
        self._real_line_index = index
        self._timestamp_ms = timestamp_ms
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._update_accessible_text()

    def clear_line_info(self) -> None:
        self._real_line_index = -1
        self._timestamp_ms = 0
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._update_accessible_text()

    def animate_in(self) -> None:
        if not _system_animations_enabled():
            self.setGraphicsEffect(None)
            self._animation = None
            return
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(210)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setGraphicsEffect(None))
        self._animation = animation
        animation.start()

    def _scaled_for_text(self, base_size: int) -> int:
        length = len(self.text())
        if length > 90:
            return max(16, int(base_size * 0.72))
        if length > 64:
            return max(18, int(base_size * 0.84))
        return base_size

    def _apply_style(self) -> None:
        family = self._config.font_family.split(",")[0].strip()
        if self._current:
            original_size = self._scaled_for_text(self._base_active_size)
            original_color = self._config.highlight_color
            weight = 700
            translation_color = self._config.translation_color
            translation_weight = 650
            translation_opacity = 1.0
        else:
            original_size = self._scaled_for_text(self._base_original_size)
            alpha = 0.72 if self._distance <= 1 else 0.65
            original_color = QColor(self._config.dim_color)
            original_color.setAlphaF(alpha)
            original_color = original_color.name(QColor.NameFormat.HexArgb)
            weight = 600
            translation_color_value = QColor(self._config.dim_color)
            translation_color_value.setAlphaF(alpha)
            translation_color = translation_color_value.name(QColor.NameFormat.HexArgb)
            translation_weight = 450
            translation_opacity = alpha

        self._original_label.setStyleSheet(
            f"""
            QLabel {{
                color: {original_color};
                background: transparent;
                font-family: "{family}";
                font-size: {original_size}px;
                font-weight: {weight};
            }}
            """
        )
        translation_size = (
            self._base_translation_size + 3
            if self._current
            else self._base_translation_size
        )
        pending_style = "italic" if self._translation_pending else "normal"
        self._translation_label.setStyleSheet(
            f"""
            QLabel {{
                color: {translation_color};
                background: transparent;
                font-family: "{family}";
                font-size: {translation_size}px;
                font-weight: {translation_weight};
                font-style: {pending_style};
            }}
            """
        )
        self._translation_label.setVisible(self._translation_visible)
        self._focus_rule.setVisible(self._current and self._translation_visible)
        self.setMinimumHeight(142 if self._current else 88)
        self._update_height_hint()
        self.setToolTip(
            "Haz clic para sincronizar con esta línea"
            if self._real_line_index >= 0
            else ""
        )

    def _update_accessible_text(self) -> None:
        text = self.text().strip()
        if not text:
            self.setAccessibleName("Línea de letra vacía")
            self.setAccessibleDescription("")
            return
        role = "Línea actual" if self._current else "Línea de contexto"
        self.setAccessibleName(f"{role}: {text}")
        details = []
        translation = self._translation_label.text().strip()
        if self._translation_visible and translation:
            details.append(f"Traducción: {translation}")
        if self._real_line_index >= 0:
            details.append(
                "Pulsa Entrar o Espacio para sincronizar con esta línea."
            )
        self.setAccessibleDescription(" ".join(details))

    def _update_interaction_style(self) -> None:
        if self._keyboard_focused:
            self.setStyleSheet(
                "LyricLabel {"
                " background: rgba(139,92,246,0.10);"
                " border: 2px solid rgba(196,181,253,0.90);"
                " border-radius: 12px;"
                " }"
            )
        elif self._hovered and not self._current:
            self.setStyleSheet(
                "LyricLabel {"
                " background: rgba(255,255,255,0.025);"
                " border: 2px solid transparent;"
                " border-radius: 12px;"
                " }"
            )
        else:
            self.setStyleSheet("")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key()
            in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
            )
            and self._real_line_index >= 0
            and self.text()
        ):
            self.line_clicked.emit(self._real_line_index, self._timestamp_ms)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._real_line_index >= 0
            and self.text()
        ):
            self.line_clicked.emit(self._real_line_index, self._timestamp_ms)
            event.accept()
            return
        event.ignore()

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = self._real_line_index >= 0
        self._update_interaction_style()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._update_interaction_style()
        super().leaveEvent(event)

    def focusInEvent(self, event: QEvent) -> None:
        self._keyboard_focused = True
        self._update_interaction_style()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QEvent) -> None:
        self._keyboard_focused = False
        self._update_interaction_style()
        super().focusOutEvent(event)


class PlaybackProgress(QWidget):
    """Barra de reproducción estrictamente informativa."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._position_ms = 0
        self._duration_ms = 0
        self.setFixedHeight(58)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("Progreso de reproducción")
        self._update_accessible_progress()

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    def set_progress(self, position_ms: int, duration_ms: int) -> None:
        self._position_ms = max(0, position_ms)
        self._duration_ms = max(0, duration_ms)
        self._update_accessible_progress()
        self.update()

    def _update_accessible_progress(self) -> None:
        position = _format_time(self._position_ms)
        duration = _format_time(self._duration_ms, "duración desconocida")
        self.setAccessibleDescription(
            f"Posición {position}; duración {duration}."
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI Variable", 12)
        painter.setFont(font)
        painter.setPen(QColor("#aeb5cf"))

        center_y = self.height() / 2
        current_text = _format_time(self._position_ms)
        duration_text = _format_time(self._duration_ms, "--:--")
        painter.drawText(
            QRectF(0, 0, 78, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            current_text,
        )

        pill_width = 72
        pill_rect = QRectF(self.width() - pill_width, 8, pill_width, self.height() - 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(13, 18, 43, 225))
        painter.drawRoundedRect(pill_rect, 18, 18)
        painter.setPen(QColor("#aeb5cf"))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, duration_text)

        track_left = 90.0
        track_right = pill_rect.left() - 28.0
        track_width = max(1.0, track_right - track_left)
        track_y = center_y
        painter.setPen(
            QPen(
                QColor(86, 94, 132, 38),
                5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(QLineF(track_left, track_y, track_right, track_y))

        progress = 0.0
        if self._duration_ms > 0:
            progress = min(1.0, self._position_ms / self._duration_ms)
        fill_right = track_left + track_width * progress
        fill_gradient = QLinearGradient(track_left, 0, max(track_left + 1, fill_right), 0)
        fill_gradient.setColorAt(0.0, QColor(66, 49, 151))
        fill_gradient.setColorAt(0.6, ACCENT_PURPLE)
        fill_gradient.setColorAt(1.0, ACCENT_BLUE)
        painter.setPen(
            QPen(
                fill_gradient,
                5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(QLineF(track_left, track_y, fill_right, track_y))
        if progress > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(111, 83, 255, 55))
            painter.drawEllipse(QPoint(int(fill_right), int(track_y)), 10, 10)
            painter.setBrush(QColor("#6f53ff"))
            painter.drawEllipse(QPoint(int(fill_right), int(track_y)), 6, 6)


class TranslationButton(QAbstractButton):
    """Control compacto con un icono visual de traducción y su estado."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._enabled_state = True
        self.setFixedSize(36, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_translation_enabled(self, enabled: bool) -> None:
        if self._enabled_state != enabled:
            self._enabled_state = enabled
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.underMouse() or self.hasFocus():
            painter.setPen(QPen(QColor(139, 92, 246, 80), 1))
            painter.setBrush(QColor(139, 92, 246, 42))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 35, 29), 8, 8)

        active = self._enabled_state
        first_color = QColor("#5b7cfa" if active else "#59617d")
        second_color = QColor("#8b5cf6" if active else "#747b96")
        text_color = QColor("#ffffff" if active else "#aeb5cf")

        first = QPainterPath()
        first.addRoundedRect(QRectF(3, 10, 18, 14), 6, 6)
        first.moveTo(7, 22)
        first.lineTo(5, 27)
        first.lineTo(12, 23)
        painter.fillPath(first, first_color)

        second = QPainterPath()
        second.addRoundedRect(QRectF(13, 3, 18, 14), 6, 6)
        second.moveTo(25, 15)
        second.lineTo(28, 20)
        second.lineTo(21, 16)
        painter.fillPath(second, second_color)

        painter.setPen(text_color)
        painter.setFont(QFont("Segoe UI Variable", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(7, 11, 9, 10), Qt.AlignmentFlag.AlignCenter, "A")
        painter.drawText(QRectF(20, 4, 9, 10), Qt.AlignmentFlag.AlignCenter, "文")

        painter.setPen(QPen(QColor("#0b1028"), 1))
        painter.setBrush(QColor("#a3e635" if active else "#626a84"))
        painter.drawEllipse(QPoint(31, 4), 3, 3)


class WindowTitleBar(QFrame):
    """Barra personalizada con marca, metadatos y controles de Windows."""

    minimize_requested = pyqtSignal()
    maximize_requested = pyqtSignal()
    close_requested = pyqtSignal()
    manage_lyrics_requested = pyqtSignal()
    translation_toggle_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(88)
        self.setStyleSheet(
            """
            QFrame#titleBar {
                background: rgba(5, 8, 22, 178);
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
            }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(30, 0, 20, 0)
        layout.setSpacing(0)

        brand_host = QWidget()
        brand_host.setFixedWidth(300)
        brand_layout = QHBoxLayout(brand_host)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(10)
        mark = BrandMark()
        mark.setFixedSize(32, 32)
        brand_layout.addWidget(mark)
        brand_label = QLabel("Letra Canción")
        brand_label.setStyleSheet(
            'color:#f7f7ff; font-family:"Segoe UI Variable"; '
            "font-size:17px; font-weight:700;"
        )
        brand_layout.addWidget(brand_label)
        brand_layout.addStretch()
        layout.addWidget(brand_host)

        track_host = QWidget()
        track_layout = QVBoxLayout(track_host)
        track_layout.setContentsMargins(8, 10, 8, 9)
        track_layout.setSpacing(2)
        self.title_label = QLabel("Esperando música")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            'color:#f7f7ff; font-family:"Segoe UI Variable"; '
            "font-size:18px; font-weight:650;"
        )
        self.artist_label = QLabel("Abre Qobuz para comenzar")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setStyleSheet(
            'color:#8b5cf6; font-family:"Segoe UI Variable"; '
            "font-size:15px; font-weight:550;"
        )
        track_layout.addStretch()
        track_layout.addWidget(self.title_label)
        track_layout.addWidget(self.artist_label)
        track_layout.addStretch()
        layout.addWidget(track_host, 1)

        controls = QWidget()
        controls.setFixedWidth(300)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(64, 0, 0, 0)
        controls_layout.setSpacing(8)
        self.manage_button = self._make_button("♫", "Gestionar letras")
        self.translation_button = TranslationButton()
        self.translation_button.setToolTip("Mostrar/ocultar traducción")
        self.translation_button.setAccessibleName("Mostrar/ocultar traducción")
        self.translation_button.setAccessibleDescription(
            "Activa o desactiva la visibilidad de las traducciones."
        )
        self.minimize_button = self._make_button("—", "Minimizar")
        self.maximize_button = self._make_button("□", "Maximizar")
        self.close_button = self._make_button("×", "Ocultar en la bandeja", close=True)
        controls_layout.addWidget(self.manage_button)
        controls_layout.addWidget(self.translation_button)
        controls_layout.addWidget(self.minimize_button)
        controls_layout.addWidget(self.maximize_button)
        controls_layout.addWidget(self.close_button)
        layout.addWidget(controls)

        self.manage_button.clicked.connect(self.manage_lyrics_requested)
        self.translation_button.clicked.connect(self.translation_toggle_requested)
        self.minimize_button.clicked.connect(self.minimize_requested)
        self.maximize_button.clicked.connect(self.maximize_requested)
        self.close_button.clicked.connect(self.close_requested)

    @staticmethod
    def _make_button(text: str, tooltip: str, close: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(42, 34)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setAccessibleDescription(
            f"Control de ventana: {tooltip.lower()}."
        )
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hover = (
            "background:rgba(225,70,90,0.85); color:white;"
            if close
            else "background:rgba(139,92,246,0.18); color:white;"
        )
        button.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #d9dced;
                font-family: "Segoe UI Variable";
                font-size: 22px;
            }}
            QPushButton:hover {{ {hover} }}
            QPushButton:focus {{
                border: 2px solid #c4b5fd;
                background: rgba(139,92,246,0.18);
            }}
            QPushButton:pressed {{ background: rgba(91,124,250,0.28); }}
            """
        )
        return button

    def set_maximized(self, maximized: bool) -> None:
        text = "❐" if maximized else "□"
        action = "Restaurar" if maximized else "Maximizar"
        self.maximize_button.setText(text)
        self.maximize_button.setToolTip(action)
        self.maximize_button.setAccessibleName(action)

    def set_track(self, title: str, artist: str) -> None:
        self.title_label.setText(title or "Esperando música")
        self.artist_label.setText(artist or "Abre Qobuz para comenzar")

    def set_translation_enabled(self, enabled: bool) -> None:
        """Actualiza el estado accesible del control compacto de traducción."""
        state = "activada" if enabled else "desactivada"
        self.translation_button.setToolTip(
            f"Traducción {state}. Clic para cambiar"
        )
        self.translation_button.setAccessibleName(
            f"Traducción {state}. Clic para cambiar"
        )
        self.translation_button.set_translation_enabled(enabled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SyncTimeDialog(QDialog):
    """Diálogo compacto para introducir una posición mm:ss."""

    def __init__(self, parent: Optional[QWidget] = None, current_position_ms: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Ajustar sincronización")
        self.setModal(True)
        self.setFixedWidth(390)
        self.setStyleSheet(
            """
            QDialog { background:#0b1028; color:white; }
            QLabel { color:#d9dced; font-size:13px; }
            QLineEdit {
                background:#111735; color:white; border:1px solid #4f46a5;
                border-radius:8px; padding:10px; font-size:20px;
            }
            QPushButton {
                background:#6f4cf5; color:white; border:none;
                border-radius:7px; padding:8px 18px; font-weight:600;
            }
            QPushButton:hover { background:#825df8; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        input_label = QLabel("&Posición de la línea seleccionada (mm:ss)")
        self._input = QLineEdit(_format_time(current_position_ms))
        self._input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._input.setPlaceholderText("01:24")
        self._input.setAccessibleName("Posición de la línea")
        self._input.setAccessibleDescription(
            "Escribe minutos y segundos con el formato mm:ss."
        )
        input_label.setBuddy(self._input)
        layout.addWidget(input_label)
        layout.addWidget(self._input)
        self._error = QLabel("")
        self._error.setStyleSheet("color:#f87171;")
        self._error.setAccessibleName("Error de posición")
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _is_valid_time(text: str) -> bool:
        parts = text.strip().split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return False
        minutes, seconds = map(int, parts)
        return minutes >= 0 and 0 <= seconds < 60

    def _accept_if_valid(self) -> None:
        if self._is_valid_time(self._input.text()):
            self.accept()
        else:
            self._error.setText("Usa el formato mm:ss; los segundos deben ser menores a 60.")
            self._input.setFocus()
            self._input.selectAll()

    def get_time_ms(self) -> Optional[int]:
        if not self._is_valid_time(self._input.text()):
            return None
        minutes, seconds = map(int, self._input.text().strip().split(":"))
        return (minutes * 60 + seconds) * 1000


class LyricsOverlay(QWidget):
    """Ventana principal inmersiva de Letra Canción."""

    closed = pyqtSignal()
    move_requested = pyqtSignal()
    sync_time_changed = pyqtSignal(int)
    quit_requested = pyqtSignal()
    manage_lyrics_requested = pyqtSignal()
    translation_toggle_requested = pyqtSignal()

    def __init__(self, config: Optional[OverlayConfig] = None):
        super().__init__()
        self.config = config or OverlayConfig()
        self._lyrics: Optional[LyricsData] = None
        self._current_line_index = -1
        self._current_position_ms = 0
        self._duration_ms = 0
        self._is_playing = False
        self._translation_in_progress = False
        self._manual_scroll_mode = False
        self._manual_line_index = 0
        self._pending_sync_state: Optional[SyncState] = None
        self._last_rendered_line_idx = -2
        self._allow_close = False
        self._edge_margin = 8
        self._normal_geometry = QRect()

        self._indicator_timer = QTimer(self)
        self._indicator_timer.setSingleShot(True)
        self._indicator_timer.timeout.connect(self._hide_indicator)
        self._manual_scroll_timer = QTimer(self)
        self._manual_scroll_timer.setSingleShot(True)
        self._manual_scroll_timer.timeout.connect(self._exit_manual_scroll_mode)

        self._setup_window()
        self._setup_ui()
        self._apply_initial_geometry()
        self._ensure_line_labels(5)
        self._show_message("Esperando música", "Abre Qobuz para comenzar")
        if self.config.window_maximized:
            QTimer.singleShot(0, self.showMaximized)

    def _setup_window(self) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self.config.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Letra Canción")
        self.setWindowIcon(create_brand_icon())
        self.setMinimumSize(900, 600)
        self.setMouseTracking(True)

    def _setup_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(18, 18, 18, 18)
        self._root_layout.setSpacing(0)

        self.container = AmbientSurface(self)
        self.container.set_background_opacity(self.config.opacity)
        self._root_layout.addWidget(self.container)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 18)
        container_layout.setSpacing(0)

        self.title_bar = WindowTitleBar(self.container)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._on_maximize_clicked)
        self.title_bar.close_requested.connect(self._on_close_clicked)
        self.title_bar.manage_lyrics_requested.connect(
            self.manage_lyrics_requested
        )
        self.title_bar.translation_toggle_requested.connect(
            self.translation_toggle_requested
        )
        self.title_bar.set_translation_enabled(self.config.translation_enabled)
        container_layout.addWidget(self.title_bar)

        self.lyrics_host = QWidget(self.container)
        self.lyrics_layout = QVBoxLayout(self.lyrics_host)
        self.lyrics_layout.setContentsMargins(36, 14, 36, 0)
        self.lyrics_layout.setSpacing(0)
        self.lyrics_layout.addStretch(1)
        container_layout.addWidget(self.lyrics_host, 1)

        self.line_labels: list[LyricLabel] = []

        controls_host = QWidget(self.container)
        controls_layout = QHBoxLayout(controls_host)
        controls_layout.setContentsMargins(54, 0, 38, 0)
        controls_layout.setSpacing(10)
        controls_layout.addStretch()
        self._back_to_auto_btn = QPushButton("↩ Volver a sincronía")
        self._back_to_auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_to_auto_btn.setStyleSheet(
            """
            QPushButton {
                background:rgba(139,92,246,0.15); color:#dcd6ff;
                border:1px solid rgba(139,92,246,0.28); border-radius:14px;
                padding:6px 14px; font-size:12px; font-weight:600;
            }
            QPushButton:hover { background:rgba(139,92,246,0.28); }
            """
        )
        self._back_to_auto_btn.clicked.connect(self._exit_manual_scroll_mode)
        self._back_to_auto_btn.hide()
        controls_layout.addWidget(self._back_to_auto_btn)

        self.offset_indicator = QLabel()
        self.offset_indicator.setAccessibleName("Estado de sincronización")
        self.offset_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.offset_indicator.setStyleSheet(
            """
            QLabel {
                background:rgba(17,23,53,0.94); color:#ddd7ff;
                border:1px solid rgba(139,92,246,0.25); border-radius:14px;
                padding:6px 14px; font-size:12px; font-weight:600;
            }
            """
        )
        self.offset_indicator.hide()
        controls_layout.addWidget(self.offset_indicator)
        controls_layout.addStretch()
        container_layout.addWidget(controls_host)

        footer = QWidget(self.container)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(54, 0, 38, 0)
        footer_layout.setSpacing(0)
        self.progress_bar = PlaybackProgress(footer)
        footer_layout.addWidget(self.progress_bar)
        container_layout.addWidget(footer)

        # Alias conservados para integraciones anteriores.
        self.time_label = QLabel()
        self.duration_label = QLabel()
        self.progress_label = QLabel()
        self.sync_indicator = QLabel()
        self.header = self.title_bar.title_label
        self.track_title_label = self.title_bar.title_label
        self.track_artist_label = self.title_bar.artist_label

    def _apply_initial_geometry(self) -> None:
        screen = self.screen()
        if screen is None:
            self.resize(1200, 760)
            return
        available = screen.availableGeometry()
        width = self.config.width or min(1440, int(available.width() * 0.85))
        height = self.config.height or min(900, int(available.height() * 0.85))
        width = max(900, min(width, available.width()))
        height = max(600, min(height, available.height()))
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def restore_window_state(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        maximized: bool = False,
    ) -> bool:
        """Restaura una geometría únicamente si intersecta una pantalla disponible."""
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            return False
        candidate = QRect(x, y, max(900, width), max(600, height))
        screens = QApplication.screens()
        if not any(screen.availableGeometry().intersects(candidate) for screen in screens):
            return False
        self.setGeometry(candidate)
        self._normal_geometry = candidate
        if maximized:
            QTimer.singleShot(0, self.showMaximized)
        return True

    def persisted_geometry(self) -> QRect:
        if self.isMaximized() and self._normal_geometry.isValid():
            return QRect(self._normal_geometry)
        return self.geometry()

    def force_close(self) -> None:
        self._allow_close = True
        self.close()

    def set_always_on_top(self, enabled: bool) -> None:
        if self.config.always_on_top == enabled:
            return
        geometry = self.geometry()
        was_visible = self.isVisible()
        self.config.always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.setGeometry(geometry)
        if was_visible:
            self.show()
            self.raise_()

    def apply_config(self, config: OverlayConfig) -> None:
        """Aplica configuración mutable sin reconstruir la ventana."""
        previous_always_on_top = self.config.always_on_top
        self.config = config
        if previous_always_on_top != config.always_on_top:
            self.config.always_on_top = previous_always_on_top
            self.set_always_on_top(config.always_on_top)
        for label in self.line_labels:
            label._config = config
            label.set_translation_visible(config.translation_enabled)
        self._update_responsive_typography()
        self.container.set_background_opacity(config.opacity)
        self._refresh_current_display()
        self.update()

    def _target_line_count(self) -> int:
        return 3 if self.height() < 720 else 5

    def _ensure_line_labels(self, target_count: int) -> None:
        target_count = 3 if target_count <= 3 else 5
        current = len(self.line_labels)
        if current < target_count:
            if current == 0:
                # El stretch superior ya existe; insertar antes del stretch final.
                pass
            for _ in range(current, target_count):
                label = LyricLabel(self.config, self.lyrics_host)
                label.line_clicked.connect(self._on_line_clicked)
                self.line_labels.append(label)
                self.lyrics_layout.addWidget(label)
        elif current > target_count:
            for label in self.line_labels[target_count:]:
                self.lyrics_layout.removeWidget(label)
                label.deleteLater()
            self.line_labels = self.line_labels[:target_count]

        # Mantener el bloque centrado con un stretch al final.
        if self.lyrics_layout.count() == len(self.line_labels) + 1:
            self.lyrics_layout.addStretch(1)
        self.config.lines_before = (target_count - 1) // 2
        self.config.lines_after = self.config.lines_before
        self._last_rendered_line_idx = -2
        self._update_responsive_typography()

    def _update_responsive_typography(self) -> None:
        width = max(900, self.width())
        active = max(36, min(56, int(width * 0.037)))
        context = max(20, min(30, int(width * 0.019)))
        translation = max(15, min(22, int(width * 0.0145)))
        active += self.config.highlight_font_size - 48
        context += self.config.font_size - 24
        translation += self.config.translation_font_size - 18
        for label in self.line_labels:
            label.set_responsive_sizes(
                max(16, min(34, context)),
                max(32, min(64, active)),
                max(12, min(28, translation)),
            )

    def _clear_labels(self) -> None:
        for label in self.line_labels:
            label.setText("")
            label.setTranslation("")
            label.set_current(False)
            label.set_dim(False)
            label.clear_line_info()
            label.set_playing(self._is_playing)

    def _render_index(self, line_index: int, animate: bool = True) -> None:
        if self._lyrics is None or not self._lyrics.lines:
            return
        line_index = max(0, min(line_index, len(self._lyrics.lines) - 1))
        self._clear_labels()
        center = self.config.lines_before
        context = self._lyrics.get_context_lines(
            line_index,
            before=self.config.lines_before,
            after=self.config.lines_after,
        )
        for relative_idx, line in context:
            label_index = center + relative_idx
            if not 0 <= label_index < len(self.line_labels):
                continue
            label = self.line_labels[label_index]
            label.setText(line.text)
            label.set_line_info(line_index + relative_idx, line.timestamp_ms)
            label.set_current(relative_idx == 0)
            translation = getattr(line, "translation", "") or ""
            label.setTranslation(
                translation,
                pending=self._translation_in_progress and not translation,
            )
            label.set_dim(relative_idx != 0, abs(relative_idx))
            label.set_translation_visible(self.config.translation_enabled)
            label.set_playing(self._is_playing)
        self._last_rendered_line_idx = line_index

    def _refresh_current_display(self) -> None:
        if self._lyrics is None or not self._lyrics.lines:
            return
        index = self._manual_line_index if self._manual_scroll_mode else self._current_line_index
        if index < 0:
            index = 0
        self._render_index(index, animate=False)

    def _show_message(self, message: str, detail: str = "") -> None:
        self._clear_labels()
        center = min(self.config.lines_before, len(self.line_labels) - 1)
        if center < 0:
            return
        label = self.line_labels[center]
        label.setText(message)
        label.set_current(True)
        label.setTranslation(detail)
        label.set_translation_visible(bool(detail))
        label.set_playing(False)
        self._last_rendered_line_idx = -2

    def set_lyrics(self, lyrics: Optional[LyricsData], duration_ms: int = 0) -> None:
        self._lyrics = lyrics
        self._current_line_index = -1
        self._last_rendered_line_idx = -2
        self._manual_scroll_mode = False
        if lyrics is None or not lyrics.lines:
            self._duration_ms = max(0, duration_ms)
            self.progress_bar.set_progress(self._current_position_ms, self._duration_ms)
            self._show_message("Esperando música", "Abre Qobuz para comenzar")
            return

        if duration_ms > 0:
            self._duration_ms = duration_ms
        else:
            self._duration_ms = lyrics.lines[-1].timestamp_ms + 5000
        self.progress_bar.set_progress(self._current_position_ms, self._duration_ms)
        if lyrics.title or lyrics.artist:
            self.set_track_info(lyrics.artist, lyrics.title)
        self._current_line_index = 0
        self._render_index(0)
        logger.info("Letras cargadas en la ventana: %s líneas", len(lyrics.lines))

    def update_line_translation(self, line_index: int, translation: str) -> None:
        if self._lyrics is None or not 0 <= line_index < len(self._lyrics.lines):
            return
        self._lyrics.lines[line_index].translation = translation
        for label in self.line_labels:
            if label._real_line_index == line_index:
                label.setTranslation(translation)
                break

    def update_playback(self, playback: PlaybackInfo) -> None:
        self._is_playing = playback.state == PlayerState.PLAYING
        if playback.duration_ms > 0:
            self._duration_ms = playback.duration_ms
        if playback.position_ms >= 0:
            self._current_position_ms = playback.position_ms
        self.progress_bar.set_progress(self._current_position_ms, self._duration_ms)
        for label in self.line_labels:
            label.set_playing(self._is_playing)

    def update_sync(self, state: SyncState) -> None:
        if self._lyrics is None or not self._lyrics.lines:
            return
        self._current_position_ms = max(0, state.position_ms)
        self._is_playing = state.is_playing
        self._pending_sync_state = state
        self.progress_bar.set_progress(self._current_position_ms, self._duration_ms)
        for label in self.line_labels:
            label.set_playing(self._is_playing)
        if self._manual_scroll_mode:
            return
        self._current_line_index = max(0, state.current_line_index)
        if self._last_rendered_line_idx != self._current_line_index:
            self._render_index(self._current_line_index)

    def show_offset_indicator(self, offset_ms: int) -> None:
        sign = "+" if offset_ms >= 0 else ""
        self._show_indicator(f"Sincronización {sign}{offset_ms} ms")

    def show_always_on_top_indicator(self, enabled: bool) -> None:
        self._show_indicator(
            "Ventana siempre encima activada"
            if enabled
            else "Ventana siempre encima desactivada"
        )

    def _show_indicator(self, message: str, duration_ms: int = 2200) -> None:
        self.offset_indicator.setText(message)
        self.offset_indicator.show()
        self._indicator_timer.start(duration_ms)

    def _hide_indicator(self) -> None:
        self.offset_indicator.hide()

    def toggle_visibility(self) -> bool:
        if self.isVisible() and not self.isMinimized():
            self.hide()
            self.closed.emit()
            return False
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()
        return True

    def toggle_translation(self) -> bool:
        self.config.translation_enabled = not self.config.translation_enabled
        self.title_bar.set_translation_enabled(self.config.translation_enabled)
        for label in self.line_labels:
            label.set_translation_visible(self.config.translation_enabled)
        self._show_indicator(
            "Traducción activada"
            if self.config.translation_enabled
            else "Traducción desactivada"
        )
        return self.config.translation_enabled

    def set_translation_enabled(self, enabled: bool) -> None:
        """Actualiza el estado de traducción y su control visual."""
        self.config.translation_enabled = enabled
        self.title_bar.set_translation_enabled(enabled)
        for label in self.line_labels:
            label.set_translation_visible(enabled)

    def set_no_lyrics_available(self, artist: str = "", title: str = "") -> None:
        self._lyrics = None
        self._show_message(
            "Letra no disponible",
            f"{artist} — {title}" if artist and title else "No encontramos una letra para esta canción",
        )

    def set_searching_lyrics(self, source: str = "") -> None:
        self._lyrics = None
        detail = f"Consultando {source}…" if source else "Buscando la mejor versión disponible…"
        self._show_message("Buscando letra", detail)

    def set_translating(self) -> None:
        self._translation_in_progress = True
        self._refresh_current_display()
        self._show_indicator("Traduciendo letra…", 4000)

    def set_translation_done(self) -> None:
        self._translation_in_progress = False
        self._refresh_current_display()
        self._show_indicator("Traducción lista")

    def set_track_info(self, artist: str, title: str) -> None:
        self.title_bar.set_track(title, artist)

    def _on_close_clicked(self) -> None:
        """Oculta la ventana y mantiene la aplicación en la bandeja."""
        self.close()

    def _on_maximize_clicked(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.title_bar.set_maximized(False)
        else:
            self._normal_geometry = self.geometry()
            self.showMaximized()
            self.title_bar.set_maximized(True)

    def _show_sync_dialog(self) -> None:
        dialog = SyncTimeDialog(self, self._current_position_ms)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            time_ms = dialog.get_time_ms()
            if time_ms is not None:
                self.sync_time_changed.emit(time_ms)
                self._show_indicator(f"Sincronizado a {_format_time(time_ms)}")

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._lyrics is None or not self._lyrics.lines or event.angleDelta().y() == 0:
            event.ignore()
            return
        if not self._manual_scroll_mode:
            self._manual_scroll_mode = True
            self._manual_line_index = max(0, self._current_line_index)
        step = -1 if event.angleDelta().y() > 0 else 1
        self._manual_line_index = max(
            0,
            min(len(self._lyrics.lines) - 1, self._manual_line_index + step),
        )
        self._render_index(self._manual_line_index)
        self._back_to_auto_btn.show()
        line_time = self._lyrics.lines[self._manual_line_index].timestamp_ms
        self._show_indicator(f"Explorando {_format_time(line_time)}", self.config.manual_scroll_timeout_s * 1000)
        self._manual_scroll_timer.start(self.config.manual_scroll_timeout_s * 1000)
        event.accept()

    def _exit_manual_scroll_mode(self) -> None:
        self._manual_scroll_mode = False
        self._manual_scroll_timer.stop()
        self._back_to_auto_btn.hide()
        self._hide_indicator()
        if self._current_line_index >= 0:
            self._render_index(self._current_line_index)

    def _on_line_clicked(self, line_index: int, timestamp_ms: int) -> None:
        self._manual_scroll_mode = False
        self._manual_scroll_timer.stop()
        self._back_to_auto_btn.hide()
        self.sync_time_changed.emit(timestamp_ms)
        self._show_indicator(f"Sincronizado a {_format_time(timestamp_ms)}")

    def _resize_edges(self, position: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if position.x() <= self._edge_margin:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - self._edge_margin:
            edges |= Qt.Edge.RightEdge
        if position.y() <= self._edge_margin:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - self._edge_margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._show_sync_dialog()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._resize_edges(event.position().toPoint())
            handle = self.windowHandle()
            if edges and handle and handle.startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.isMaximized():
            self.unsetCursor()
            return
        edges = self._resize_edges(event.position().toPoint())
        if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edges:
            if edges in (
                Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
            ):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        target_count = self._target_line_count()
        if len(self.line_labels) != target_count:
            self._ensure_line_labels(target_count)
            if self._lyrics is not None:
                self._refresh_current_display()
        self._update_responsive_typography()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            margin = 0 if maximized else 18
            self._root_layout.setContentsMargins(margin, margin, margin, margin)
            self.title_bar.set_maximized(maximized)
            self.container.update()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.closed.emit()


def main() -> None:
    """Demo visual independiente."""
    import sys

    from ..lrc_parser import LRCParser

    app = QApplication(sys.argv)
    app.setApplicationName("Letra Canción")
    overlay = LyricsOverlay()
    overlay.set_track_info("Faces", "Silicone Grown")
    lyrics = LRCParser.parse(
        """
[00:05.00]Wait a minute, honey
[00:09.00]I don't think your joke's too funny, no
[00:14.00]I stayed up all night
[00:19.00]Checking out the doctor's guide
[00:24.00]Wait a minute, honey
"""
    )
    translations = (
        "Espera un minuto, cariño",
        "No creo que tu broma sea muy divertida, no.",
        "Me quedé despierto toda la noche",
        "Revisando la guía del doctor",
        "Espera un minuto, cariño",
    )
    for line, translation in zip(lyrics.lines, translations):
        line.translation = translation
    overlay.set_lyrics(lyrics, 160000)
    overlay.show()
    overlay.update_sync(
        SyncState(
            mode=SyncMode.SYNCED,
            current_line_index=2,
            current_line=lyrics.lines[2],
            position_ms=84000,
            is_playing=True,
            offset_ms=0,
        )
    )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
