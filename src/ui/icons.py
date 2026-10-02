
from __future__ import annotations

from math import cos, sin, pi

from PySide6.QtCore import Qt, QPointF, QRectF, QByteArray, QEvent, QObject, QSize
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import (
    QIconEngine,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

# dark テーマの色。描画時に map_color() が現在テーマの色へ置き換えるので、
# 意味役割の名前に書き換えないこと。
_COLOR_SECONDARY = "#aeb6c5"
_COLOR_TEXT = "#f1f3f7"
_COLOR_DANGER = "#e66464"
_COLOR_ACCENT_SOFT = "#9fb4d8"
_COLOR_TEXT_SECONDARY = "#c5d0e6"
_COLOR_TEXT_MUTED = "#5c6474"


def _theme_color(color: str) -> str:
    try:
        from src.ui.theme import map_color
        return map_color(color)
    except Exception:
        return color

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
        QColor(_theme_color(color)),
        _stroke_w(size, weight),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )

def make_settings_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    pm, p = _blank(size)
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

def make_reset_widths_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    pm, p = _blank(size)
    pen = _pen(color, size, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
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

# --- 線アイコン（24 グリッドの SVG を現在テーマ色で描く） -------------------------
# 太さ・端・角をすべて共通にして、ボタンごとの見た目の揃いを保つ。
# 設定（歯車）と幅リセット（循環矢印）は上の手描き実装をそのまま使う。

_SVG_ICONS: dict[str, tuple[str, bool]] = {
    # name: (SVG の中身, 塗りつぶしか)
    "close": ('<path d="M6 6 18 18M18 6 6 18"/>', False),
    "plus": ('<path d="M12 5.5v13M5.5 12h13"/>', False),
    "minimize": ('<path d="M6 16.5h12"/>', False),
    "maximize": ('<rect x="5.5" y="5.5" width="13" height="13" rx="2.5"/>', False),
    "restore": (
        '<rect x="5" y="9.5" width="9.5" height="9.5" rx="2.2"/>'
        '<path d="M9.5 9.5V7.7A2.2 2.2 0 0 1 11.7 5.5h4.6A2.2 2.2 0 0 1 18.5 7.7v4.6a2.2 2.2 0 0 1-2.2 2.2H14.5"/>',
        False,
    ),
    "chevron_down": ('<path d="m5.5 8.5 6.5 7 6.5-7"/>', False),
    "chevron_left": ('<path d="m15.5 5.5-6.5 6.5 6.5 6.5"/>', False),
    "chevron_right": ('<path d="m8.5 5.5 6.5 6.5-6.5 6.5"/>', False),
    "back": ('<path d="M19 12H5.5M11 6.5 5.5 12l5.5 5.5"/>', False),
    "forward": ('<path d="M5 12h13.5M13 6.5l5.5 5.5-5.5 5.5"/>', False),
    "expand_h": ('<path d="M3.5 12h17M7.5 8 3.5 12l4 4M16.5 8l4 4-4 4"/>', False),
    "home": (
        '<path d="m4 11.2 8-6.7 8 6.7"/>'
        '<path d="M6.5 9.8V18a1.5 1.5 0 0 0 1.5 1.5h8a1.5 1.5 0 0 0 1.5-1.5V9.8"/>'
        '<path d="M10 19.5v-4.2a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4.2"/>',
        False,
    ),
    "download": ('<path d="M12 4.5v10M7.5 10.5l4.5 4.5 4.5-4.5M5 19.5h14"/>', False),
    "file_open": (
        '<path d="M10.5 6.5H7A1.8 1.8 0 0 0 5.2 8.3v8.7A1.8 1.8 0 0 0 7 18.8h8.7a1.8 1.8 0 0 0 1.8-1.8v-3.5"/>'
        '<path d="M14 5h5v5M19 5l-8 8"/>',
        False,
    ),
    "folder": (
        '<path d="M4 8.2A2.2 2.2 0 0 1 6.2 6h3.2l2 2.4h6.4A2.2 2.2 0 0 1 20 10.6v6.2a2.2 2.2 0 0 1-2.2 2.2H6.2A2.2 2.2 0 0 1 4 16.8z"/>',
        False,
    ),
    "trash": (
        '<path d="M4.8 7h14.4M9.5 7V5.4a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>'
        '<path d="M6.5 7l.8 10.6A1.8 1.8 0 0 0 9.1 19.3h5.8a1.8 1.8 0 0 0 1.8-1.7L17.5 7"/>'
        '<path d="M10.2 10.8v5M13.8 10.8v5"/>',
        False,
    ),
    "edit": (
        '<path d="M4.8 19.2 5.6 15 15.9 4.7a1.9 1.9 0 0 1 2.7 0l.7.7a1.9 1.9 0 0 1 0 2.7L9 18.4z"/>'
        '<path d="m14 6.6 3.4 3.4"/>',
        False,
    ),
    "mic": (
        '<rect x="9" y="3.8" width="6" height="10.4" rx="3"/>'
        '<path d="M6 11.5a6 6 0 0 0 12 0M12 17.5v3M9 20.5h6"/>',
        False,
    ),
    "stop": ('<rect x="6" y="6" width="12" height="12" rx="2.6"/>', True),
    "edge_dock": (
        '<rect x="4" y="5" width="16" height="14" rx="2.6"/><path d="M9.5 5v14"/>',
        False,
    ),
}

_GRIP_DOTS = "".join(
    f'<circle cx="{x}" cy="{y}" r="1.35"/>' for x in (9.3, 14.7) for y in (7, 12, 17)
)
_SVG_ICONS["column_grip"] = (_GRIP_DOTS, True)


def _svg_icon(name: str, color: str, size: int, weight: float = 1.0) -> QIcon:
    inner, filled = _SVG_ICONS[name]
    c = _theme_color(color)
    px = max(1.25, size * 0.092) * weight
    sw = px * 20.0 / max(1, size)
    if filled:
        attrs = f'fill="{c}" stroke="{c}" stroke-width="{sw * 0.4:.3f}"'
    else:
        attrs = f'fill="none" stroke="{c}" stroke-width="{sw:.3f}"'
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 20 20">'
        f'<g {attrs} stroke-linecap="round" stroke-linejoin="round">{inner}</g></svg>'
    )
    dpr = 3
    pm = QPixmap(max(1, size) * dpr, max(1, size) * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def make_close_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("close", color, size)

def make_plus_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("plus", color, size)

def make_minimize_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("minimize", color, size)

def make_maximize_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("maximize", color, size)

def make_restore_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("restore", color, size)

def make_chevron_down_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("chevron_down", color, size)

def make_chevron_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("chevron_left", color, size)

# 収納/展開は「端へ寄せる・端から戻す」向きが分かる山形で示す
def make_stow_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("chevron_left", color, size)

def make_stow_right_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("chevron_right", color, size)

def make_expand_left_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("chevron_left", color, size)

def make_back_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("back", color, size)

def make_forward_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("forward", color, size)

def make_expand_h_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("expand_h", color, size)

def make_home_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("home", color, size)

def make_download_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    return _svg_icon("download", color, size)

def make_file_open_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("file_open", color, size)

def make_folder_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("folder", color, size)

def make_trash_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("trash", color, size)

def make_edit_icon(color: str = _COLOR_SECONDARY, size: int = 12) -> QIcon:
    return _svg_icon("edit", color, size)

def make_mic_icon(color: str = _COLOR_DANGER, size: int = 16) -> QIcon:
    return _svg_icon("mic", color, size)

def make_stop_icon(color: str = _COLOR_TEXT, size: int = 16) -> QIcon:
    return _svg_icon("stop", color, size)

def make_edge_dock_icon(color: str = _COLOR_SECONDARY, size: int = 16) -> QIcon:
    return _svg_icon("edge_dock", color, size)

def make_column_grip_icon(color: str = _COLOR_SECONDARY, size: int = 14) -> QIcon:
    return _svg_icon("column_grip", color, size)


class _HoverIconFilter(QObject):
    """ボタンのホバー中だけアイコンを差し替える（QSS の color はアイコンに効かないため）。"""

    def __init__(self, button, normal, hover) -> None:
        super().__init__(button)
        self._button = button
        self._normal = normal
        self._hover = hover
        button.setIcon(normal())
        button.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.Enter:
            self._button.setIcon(self._hover())
        elif t in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._button.setIcon(self._normal())
        return False


def install_close_icon(button, size: int = 12) -> None:
    """×の文字ではなく線アイコンの閉じるボタンにする。ホバー時は危険色。"""
    button.setText("")
    button.setIconSize(QSize(size, size))
    _HoverIconFilter(
        button,
        lambda: make_close_icon(_COLOR_SECONDARY, size),
        lambda: make_close_icon(_COLOR_DANGER, size),
    )


class _ThemedIconEngine(QIconEngine):
    """アイコンを要求のたびに現在テーマで描き直す。

    QIcon にピクセルを固定すると、テーマ切替後も旧テーマ色のまま残る。
    各 make_*_icon をこのエンジンで包み、個別の refresh_theme を不要にする。
    """

    def __init__(self, builder, args: tuple, kwargs: dict) -> None:
        super().__init__()
        self._builder = builder
        self._args = args
        self._kwargs = kwargs

    def _raw(self) -> QIcon:
        return self._builder(*self._args, **self._kwargs)

    def pixmap(self, size, mode, state) -> QPixmap:
        pm = self._raw().pixmap(size, QIcon.Mode.Normal, state)
        if mode == QIcon.Mode.Disabled and not pm.isNull():
            # 無効時は薄くする（QSS の color はアイコンに効かないため）
            faded = QPixmap(pm.size())
            faded.setDevicePixelRatio(pm.devicePixelRatio())
            faded.fill(Qt.GlobalColor.transparent)
            p = QPainter(faded)
            p.setOpacity(0.4)
            p.drawPixmap(0, 0, pm)
            p.end()
            return faded
        return pm

    def paint(self, painter, rect, mode, state) -> None:
        pm = self.pixmap(rect.size(), mode, state)
        painter.drawPixmap(rect.topLeft(), pm)

    def clone(self):
        return _ThemedIconEngine(self._builder, self._args, self._kwargs)


def _themed(builder):
    def make(*args, **kwargs) -> QIcon:
        return QIcon(_ThemedIconEngine(builder, args, kwargs))
    make.__name__ = builder.__name__
    make.__doc__ = builder.__doc__
    return make


for _name in [n for n in list(globals()) if n.startswith("make_") and n.endswith("_icon")]:
    globals()[_name] = _themed(globals()[_name])

