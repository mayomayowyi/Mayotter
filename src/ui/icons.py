
from __future__ import annotations

from math import cos, sin, pi

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

_COLOR_SECONDARY = "#aeb6c5"
_COLOR_TEXT = "#f1f3f7"
_COLOR_ACCENT = "#4a7ec7"

def _blank(size: int, dpr: int = 2) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(max(1, size) * dpr, max(1, size) * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    return pm, p

def _stroke_w(size: float, weight: float = 1.0) -> float:
    base = max(1.15, size * 0.105)
    if size <= 12:
        base = max(1.25, size * 0.12)
    return base * weight

def _pen(color: str, size: float, weight: float = 1.0) -> QPen:
    return QPen(
        QColor(color),
        _stroke_w(size, weight),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )

def _margin(size: float) -> float:
    return size * 0.18

def make_settings_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    pm, p = _blank(size)
    c = QColor(color)
    cx = cy = size / 2.0
    outer = size * 0.38
    mid = size * 0.28
    hub = size * 0.11
    teeth = 6
    path = QPainterPath()
    for i in range(teeth):
        a0 = (i / teeth) * 2 * pi
        a1 = a0 + (0.22 / teeth) * 2 * pi
        a2 = a0 + (0.38 / teeth) * 2 * pi
        a3 = a0 + (0.62 / teeth) * 2 * pi
        a4 = a0 + (0.78 / teeth) * 2 * pi
        a5 = a0 + (1.0 / teeth) * 2 * pi
        pts = [
            (a0, mid), (a1, outer), (a2, outer),
            (a3, mid), (a4, mid), (a5, mid),
        ]
        for j, (a, r) in enumerate(pts):
            x, y = cx + r * cos(a - pi / 2), cy + r * sin(a - pi / 2)
            if i == 0 and j == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    p.setPen(_pen(color, size, 0.95))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.drawEllipse(QPointF(cx, cy), hub, hub)
    p.end()
    return QIcon(pm)

def make_close_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.05))
    m = _margin(size) * 1.05
    p.drawLine(QPointF(m, m), QPointF(size - m, size - m))
    p.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    p.end()
    return QIcon(pm)

def make_edit_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    m = _margin(size)
    p.drawLine(QPointF(m + size * 0.08, size - m - size * 0.08), QPointF(size - m - size * 0.18, m + size * 0.18))
    tip = QPainterPath()
    tip.moveTo(size - m, m)
    tip.lineTo(size - m - size * 0.16, m + size * 0.04)
    tip.lineTo(size - m - size * 0.04, m + size * 0.16)
    tip.closeSubpath()
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(tip)
    p.end()
    return QIcon(pm)

def make_download_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = size / 2.0
    m = _margin(size)
    top = m + size * 0.06
    mid_y = size * 0.52
    bot = size - m - size * 0.08
    p.drawLine(QPointF(cx, top), QPointF(cx, mid_y + size * 0.06))
    ah = size * 0.18
    path = QPainterPath()
    path.moveTo(cx - ah, mid_y - size * 0.02)
    path.lineTo(cx, mid_y + ah * 0.55)
    path.lineTo(cx + ah, mid_y - size * 0.02)
    p.drawPath(path)
    tw = size * 0.28
    p.drawLine(QPointF(cx - tw, bot), QPointF(cx + tw, bot))
    p.drawLine(QPointF(cx - tw, bot - size * 0.12), QPointF(cx - tw, bot))
    p.drawLine(QPointF(cx + tw, bot - size * 0.12), QPointF(cx + tw, bot))
    p.end()
    return QIcon(pm)

def make_home_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    w = float(size)
    path = QPainterPath()
    path.moveTo(w * 0.50, m * 0.9)
    path.lineTo(w - m * 0.85, w * 0.42)
    path.lineTo(m * 0.85, w * 0.42)
    path.closeSubpath()
    p.drawPath(path)
    body = QPainterPath()
    body.moveTo(w * 0.30, w * 0.42)
    body.lineTo(w * 0.30, w - m)
    body.lineTo(w * 0.70, w - m)
    body.lineTo(w * 0.70, w * 0.42)
    p.drawPath(body)
    p.drawLine(QPointF(w * 0.50, w - m), QPointF(w * 0.50, w * 0.58))
    p.end()
    return QIcon(pm)

def make_back_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.05))
    m = _margin(size)
    cx, cy = size / 2.0, size / 2.0
    path = QPainterPath()
    path.moveTo(cx + size * 0.14, m * 1.05)
    path.lineTo(m * 1.15, cy)
    path.lineTo(cx + size * 0.14, size - m * 1.05)
    p.drawPath(path)
    p.end()
    return QIcon(pm)

def make_forward_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.05))
    m = _margin(size)
    cx, cy = size / 2.0, size / 2.0
    path = QPainterPath()
    path.moveTo(cx - size * 0.14, m * 1.05)
    path.lineTo(size - m * 1.15, cy)
    path.lineTo(cx - size * 0.14, size - m * 1.05)
    p.drawPath(path)
    p.end()
    return QIcon(pm)

def make_plus_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.05))
    m = _margin(size) * 1.1
    cx = cy = size / 2.0
    p.drawLine(QPointF(m, cy), QPointF(size - m, cy))
    p.drawLine(QPointF(cx, m), QPointF(cx, size - m))
    p.end()
    return QIcon(pm)

def make_edge_dock_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    p.drawRoundedRect(QRectF(m + size * 0.12, m, size - 2 * m - size * 0.12, size - 2 * m), size * 0.08, size * 0.08)
    p.drawLine(QPointF(m * 0.9, m + size * 0.08), QPointF(m * 0.9, size - m - size * 0.08))
    p.end()
    return QIcon(pm)

def make_column_grip_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    c = QColor(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    cx = size / 2.0
    r = max(1.1, size * 0.07)
    gap_x = size * 0.22
    gap_y = size * 0.20
    for row in range(3):
        for col in range(2):
            x = cx + (col - 0.5) * gap_x
            y = size * 0.28 + row * gap_y
            p.drawEllipse(QPointF(x, y), r, r)
    p.end()
    return QIcon(pm)

def make_mic_icon(color: str = "#e66464", size: int = 16) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = size / 2.0
    m = _margin(size)
    cap = QRectF(cx - size * 0.14, m * 0.95, size * 0.28, size * 0.42)
    p.drawRoundedRect(cap, size * 0.14, size * 0.14)
    p.drawArc(QRectF(cx - size * 0.26, size * 0.28, size * 0.52, size * 0.42), 0, -180 * 16)
    p.drawLine(QPointF(cx, size * 0.68), QPointF(cx, size - m * 1.05))
    p.drawLine(QPointF(cx - size * 0.16, size - m * 1.05), QPointF(cx + size * 0.16, size - m * 1.05))
    p.end()
    return QIcon(pm)

def make_stop_icon(color: str = _COLOR_TEXT, size: int = 16) -> QIcon:
    pm, p = _blank(size)
    c = QColor(color)
    m = _margin(size) * 1.15
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.08, size * 0.08)
    p.end()
    return QIcon(pm)

def make_minimize_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.1))
    m = _margin(size)
    y = size * 0.62
    p.drawLine(QPointF(m * 1.1, y), QPointF(size - m * 1.1, y))
    p.end()
    return QIcon(pm)

def make_maximize_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size) * 1.05
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.06, size * 0.06)
    p.end()
    return QIcon(pm)

def make_restore_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    p.drawRoundedRect(QRectF(m + size * 0.12, m * 0.85, size * 0.52, size * 0.52), 1.2, 1.2)
    p.drawRoundedRect(QRectF(m * 0.95, m + size * 0.18, size * 0.52, size * 0.52), 1.2, 1.2)
    p.end()
    return QIcon(pm)

def make_folder_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    p.setPen(_pen(color, size, 0.95))
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    path = QPainterPath()
    path.moveTo(m, size * 0.38)
    path.lineTo(m, size - m)
    path.lineTo(size - m, size - m)
    path.lineTo(size - m, size * 0.38)
    path.lineTo(size * 0.48, size * 0.38)
    path.lineTo(size * 0.40, m * 1.15)
    path.lineTo(m, m * 1.15)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pm)

def make_trash_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    p.drawLine(QPointF(m * 0.95, m * 1.35), QPointF(size - m * 0.95, m * 1.35))
    p.drawLine(QPointF(size * 0.36, m * 0.95), QPointF(size * 0.64, m * 0.95))
    path = QPainterPath()
    path.moveTo(m * 1.2, m * 1.35)
    path.lineTo(m * 1.45, size - m)
    path.lineTo(size - m * 1.45, size - m)
    path.lineTo(size - m * 1.2, m * 1.35)
    p.drawPath(path)
    p.drawLine(QPointF(size * 0.40, m * 1.7), QPointF(size * 0.40, size - m * 1.25))
    p.drawLine(QPointF(size * 0.60, m * 1.7), QPointF(size * 0.60, size - m * 1.25))
    p.end()
    return QIcon(pm)

def make_file_open_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 0.95)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    path = QPainterPath()
    path.moveTo(m * 1.1, size * 0.42)
    path.lineTo(m * 1.1, size - m)
    path.lineTo(size - m, size - m)
    path.lineTo(size - m, m * 1.1)
    path.lineTo(size * 0.48, m * 1.1)
    p.drawPath(path)
    p.drawLine(QPointF(size * 0.52, size * 0.48), QPointF(size - m * 0.85, m * 1.0))
    p.drawLine(QPointF(size - m * 0.85, m * 1.0), QPointF(size - m * 0.85, m * 1.55))
    p.drawLine(QPointF(size - m * 0.85, m * 1.0), QPointF(size - m * 1.45, m * 1.0))
    p.end()
    return QIcon(pm)

def make_chevron_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return make_back_icon(color, size)

def make_stow_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return make_back_icon(color, size)

def make_stow_right_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return make_forward_icon(color, size)

def make_reset_widths_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = _margin(size)
    r = size * 0.32
    cx = cy = size / 2.0
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    p.drawArc(rect, int(40 * 16), int(250 * 16))
    ang = 40 + 250
    from math import radians
    a = radians(ang)
    x = cx + r * cos(a)
    y = cy - r * sin(a)
    path = QPainterPath()
    path.moveTo(x - size * 0.12, y - size * 0.02)
    path.lineTo(x, y)
    path.lineTo(x - size * 0.04, y + size * 0.12)
    p.drawPath(path)
    p.end()
    return QIcon(pm)

def make_expand_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return make_back_icon(color, size)

