from __future__ import annotations

import ctypes
import math
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget
from src.ui.theme import _DARK_THEMES, get_theme_id, map_color, color


_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWA_COLOR_NONE = 0xFFFFFFFE
_DWMWCP_DONOTROUND = 1
_DWMWCP_ROUND = 2
_DWMWCP_ROUNDSMALL = 3

_DWM_READY = False
_DWM = None


def _windows11_or_newer() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return int(sys.getwindowsversion().build) >= 22000
    except Exception:
        return False


def native_rounding_available() -> bool:
    return _windows11_or_newer()


def _dwm_api():
    global _DWM_READY, _DWM
    if _DWM_READY:
        return _DWM
    _DWM_READY = True
    if sys.platform != "win32":
        return None
    try:
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        fn = dwm.DwmSetWindowAttribute
        fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        fn.restype = ctypes.c_long
        _DWM = fn
    except Exception:
        _DWM = None
    return _DWM


def _colorref(hex_color: str) -> int:
    value = str(map_color(hex_color or "#2b3242")).lstrip("#")
    if len(value) != 6:
        value = "2b3242"
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        r, g, b = 0x2B, 0x32, 0x42
    return (b << 16) | (g << 8) | r


def _set_attr(hwnd: int, attr: int, value, ctype) -> bool:
    fn = _dwm_api()
    if fn is None or not hwnd:
        return False
    try:
        data = ctype(value)
        result = int(fn(wintypes.HWND(hwnd), attr, ctypes.byref(data), ctypes.sizeof(data)))
        return result >= 0
    except Exception:
        return False


def set_window_corner_preference(widget: QWidget, mode: str = "round") -> bool:
    if not native_rounding_available() or widget is None:
        return False
    mapping = {
        "square": _DWMWCP_DONOTROUND,
        "round": _DWMWCP_ROUND,
        "small": _DWMWCP_ROUNDSMALL,
    }
    preference = mapping.get(str(mode or "round").lower(), _DWMWCP_ROUND)
    try:
        hwnd = int(widget.winId())
    except Exception:
        return False
    return _set_attr(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, preference, ctypes.c_int)


def apply_native_window_polish(
    widget: QWidget,
    *,
    corner: str | None = "round",
    border_color: str | None = None,
) -> bool:
    """枠と角を DWM で描く（Qt の 1bit region は使わない）。

    corner=None は角設定に触れず、枠色とdark-modeだけを現在テーマへ更新する。
    """
    if not native_rounding_available() or widget is None:
        return False
    try:
        hwnd = int(widget.winId())
    except Exception:
        return False

    ok = False
    # DWMの非クライアントAA/縁取りも現在テーマへ合わせる。
    # 明色テーマでdark-modeを強制すると、角のAAピクセルだけ黒く残ることがある。
    immersive_dark = 1 if get_theme_id() in _DARK_THEMES else 0
    ok = _set_attr(
        hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, immersive_dark, wintypes.BOOL
    ) or ok
    if corner is not None:
        ok = _set_attr(
            hwnd,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            {
                "square": _DWMWCP_DONOTROUND,
                "small": _DWMWCP_ROUNDSMALL,
            }.get(str(corner).lower(), _DWMWCP_ROUND),
            ctypes.c_int,
        ) or ok
    if border_color is None:
        border_color = color("BORDER")
    border_value = _DWMWA_COLOR_NONE if border_color is None else _colorref(border_color)
    ok = _set_attr(hwnd, _DWMWA_BORDER_COLOR, border_value, wintypes.DWORD) or ok
    return ok


def set_window_border_hidden(widget: QWidget, hidden: bool) -> bool:
    """DWMの1px枠だけを消す/現在テーマのBORDER色へ戻す（transition中の本体park用）。"""
    if not native_rounding_available() or widget is None:
        return False
    try:
        hwnd = int(widget.winId())
    except Exception:
        return False
    value = _DWMWA_COLOR_NONE if hidden else _colorref(color("BORDER"))
    return _set_attr(hwnd, _DWMWA_BORDER_COLOR, value, wintypes.DWORD)


# region生成はresize/mask更新ごとに走るため、DLL解決とシグネチャ設定は
# 1回だけ行う（毎回の WinDLL 構築は ctypes の関数プロトタイプを毎回作り直す）。
_REGION_APIS: tuple | None = None


def _region_apis() -> tuple:
    global _REGION_APIS
    if _REGION_APIS is not None:
        return _REGION_APIS
    if sys.platform != "win32":
        _REGION_APIS = (None, None, None, None)
        return _REGION_APIS
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        get_rect = user32.GetWindowRect
        get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        get_rect.restype = wintypes.BOOL
        set_region = user32.SetWindowRgn
        set_region.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        set_region.restype = ctypes.c_int
        create_polygon = gdi32.CreatePolygonRgn
        create_polygon.argtypes = [
            ctypes.POINTER(wintypes.POINT), ctypes.c_int, ctypes.c_int
        ]
        create_polygon.restype = wintypes.HANDLE
        delete_object = gdi32.DeleteObject
        delete_object.argtypes = [wintypes.HANDLE]
        delete_object.restype = wintypes.BOOL
        _REGION_APIS = (get_rect, set_region, create_polygon, delete_object)
    except Exception:
        _REGION_APIS = (None, None, None, None)
    return _REGION_APIS


def apply_native_corner_region(
    widget: QWidget,
    *,
    radius: int = 12,
    top_left: bool = True,
    top_right: bool = True,
    bottom_right: bool = False,
    bottom_left: bool = False,
    border_color: str | None = None,
) -> bool:
    """Windowsの物理ピクセルregionで任意の四隅を同じ半径に揃える。"""
    if sys.platform != "win32" or widget is None:
        return False
    get_rect, set_region, create_polygon, delete_object = _region_apis()
    if get_rect is None:
        return False
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False

        rect = wintypes.RECT()
        if not get_rect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return False
        width = max(1, int(rect.right - rect.left))
        height = max(1, int(rect.bottom - rect.top))
        try:
            dpr = float(widget.devicePixelRatioF() or 1.0)
        except Exception:
            dpr = 1.0
        r = max(0, min(int(round(float(radius) * dpr)), width // 2, height // 2))
        samples = max(12, min(96, r * 4)) if r > 0 else 0

        points: list[tuple[int, int]] = []

        def arc(cx: int, cy: int, start: float, end: float) -> None:
            for i in range(samples + 1):
                a = start + (end - start) * (i / samples)
                points.append((round(cx + r * math.cos(a)), round(cy + r * math.sin(a))))

        if top_left and r > 0:
            arc(r, r, math.pi, 1.5 * math.pi)
        else:
            points.append((0, 0))
        if top_right and r > 0:
            arc(width - r, r, 1.5 * math.pi, 2.0 * math.pi)
        else:
            points.append((width, 0))
        if bottom_right and r > 0:
            arc(width - r, height - r, 0.0, 0.5 * math.pi)
        else:
            points.append((width, height))
        if bottom_left and r > 0:
            arc(r, height - r, 0.5 * math.pi, math.pi)
        else:
            points.append((0, height))

        arr_type = wintypes.POINT * len(points)
        arr = arr_type(*(wintypes.POINT(x, y) for x, y in points))
        hrgn = create_polygon(arr, len(points), 2)
        if not hrgn:
            return False

        apply_native_window_polish(widget, corner="square", border_color=border_color)
        if set_region(wintypes.HWND(hwnd), hrgn, True):
            return True
        delete_object(hrgn)
    except Exception:
        return False
    return False


def clear_native_region(widget: QWidget) -> None:
    """SetWindowRgn で付けた切り抜きを解除する（DWMの角丸へ切り替える用）。"""
    _, set_region, _, _ = _region_apis()
    if set_region is None or widget is None:
        return
    try:
        set_region(wintypes.HWND(int(widget.winId())), None, True)
    except Exception:
        pass


def apply_native_top_corner_region(
    widget: QWidget,
    *,
    radius: int = 12,
    top_left: bool = True,
    top_right: bool = True,
    border_color: str | None = None,
) -> bool:
    return apply_native_corner_region(
        widget,
        radius=radius,
        top_left=top_left,
        top_right=top_right,
        bottom_right=False,
        bottom_left=False,
        border_color=border_color,
    )

def _repolish(widget: QWidget) -> None:
    try:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    except Exception:
        pass


def prepare_popup_chrome(
    widget: QWidget,
    *,
    background: str | None = None,
    border_color: str | None = None,
    corner: str = "round",
) -> bool:
    """不透明なフレームレスポップアップの角を DWM に任せる。

    QRegion・QSS の角丸・DWM の角を重ねると、角に暗い画素が出たり半径がずれたりする。
    """
    if widget is None or not native_rounding_available():
        try:
            widget.setProperty("mayotterNativeRounded", False)
        except Exception:
            pass
        return False
    try:
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setProperty("mayotterNativeRounded", True)
        widget.clearMask()

        if background is None:
            background = color("SURFACE")
        if border_color is None:
            border_color = color("BORDER")

        pal = widget.palette()
        bg = QColor(map_color(background))
        pal.setColor(QPalette.ColorRole.Window, bg)
        pal.setColor(QPalette.ColorRole.Base, bg)
        widget.setPalette(pal)
        _repolish(widget)
    except Exception:
        pass
    ok = apply_native_window_polish(widget, corner=corner, border_color=border_color)
    # Tool/Dialog はネイティブ化で winId が変わることがあるので次のターンで再適用する
    try:
        QTimer.singleShot(0, lambda w=widget: apply_native_window_polish(
            w, corner=corner, border_color=border_color
        ))
    except Exception:
        pass
    return ok


class _WindowPolishFilter(QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if not isinstance(obj, QWidget) or not obj.isWindow():
            return False
        if event.type() not in (QEvent.Type.Show, QEvent.Type.WinIdChange):
            return False

        def _apply(w=obj):
            try:
                if not w.isWindow():
                    return
                flags = w.windowFlags()
                if flags & Qt.WindowType.ToolTip:
                    return
                if w.objectName() == "mayotter_minimal_tooltip":
                    return
                # MainWindow/Dock は自前で形と切替中のマスクを管理する
                if w.__class__.__name__ == "MainWindow":
                    return
                # 半透明の補助ウィンドウ（切替シェル・ツールチップ・ノブ）は自前で縁を描くので
                # DWM の枠を付けない
                if w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
                    return
                compact = bool(flags & (Qt.WindowType.Tool | Qt.WindowType.Popup | Qt.WindowType.Dialog))
                if compact:
                    prepare_popup_chrome(w, corner="round")
                else:
                    apply_native_window_polish(w, corner="round")
            except RuntimeError:
                pass
            except Exception:
                pass

        QTimer.singleShot(0, _apply)
        return False


def install_window_polish(app) -> None:
    if app is None or getattr(app, "_mayotter_window_polish_filter", None) is not None:
        return
    filt = _WindowPolishFilter(app)
    app.installEventFilter(filt)
    app._mayotter_window_polish_filter = filt
