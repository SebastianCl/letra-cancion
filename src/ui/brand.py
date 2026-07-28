"""Recursos vectoriales compartidos de la identidad de Letra Canción."""

from PyQt6.QtCore import QLineF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap


ACCENT_PURPLE = QColor("#8b5cf6")
ACCENT_BLUE = QColor("#5b7cfa")


def draw_brand_mark(painter: QPainter, rect: QRectF) -> None:
    """Dibuja el ecualizador violeta/azul usado como marca de la aplicación."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
    gradient.setColorAt(0.0, ACCENT_PURPLE)
    gradient.setColorAt(1.0, ACCENT_BLUE)

    heights = (0.36, 0.64, 0.92, 0.68, 0.43)
    gap = rect.width() / 7.0
    line_width = max(2.0, rect.width() * 0.09)
    pen = QPen(gradient, line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    center_y = rect.center().y()
    start_x = rect.left() + gap * 1.5
    for index, height_ratio in enumerate(heights):
        x = start_x + gap * index
        half_height = rect.height() * height_ratio / 2.0
        painter.drawLine(QLineF(x, center_y - half_height, x, center_y + half_height))

    painter.restore()


def create_brand_icon(size: int = 64) -> QIcon:
    """Crea un icono DPI-aware sin depender de un bitmap externo."""
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#090d22"))
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    painter.setPen(QPen(QColor(102, 115, 164, 90), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 2.5, size - 5, size - 5), size * 0.22, size * 0.22)
    draw_brand_mark(
        painter,
        QRectF(size * 0.17, size * 0.2, size * 0.66, size * 0.6),
    )
    painter.end()
    return QIcon(pixmap)
