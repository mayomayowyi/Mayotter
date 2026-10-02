from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from src.ui.icons import make_stow_right_icon, make_expand_left_icon, _COLOR_TEXT_SECONDARY
from src.ui.theme import color as theme_color


class StowRestoreKnob(QWidget):
    restoreRequested = Signal(str)

    _VISUAL = 22
    _HIT = 30
    _ICON = 14

    def __init__(self, parent: QWidget | None = None, side: str = "right"):
        super().__init__(parent)
        self._side = "left" if side == "left" else "right"
        self._hover = False
        self._shape_t = 0.0
        self._highlight = 0.0
        self.setObjectName("stow_restore_knob")
        self.setFixedSize(self._HIT, self._HIT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        try:
            if self._side == "left":
                self._icon = make_stow_right_icon(_COLOR_TEXT_SECONDARY, self._ICON)
            else:
                self._icon = make_expand_left_icon(_COLOR_TEXT_SECONDARY, self._ICON)
        except Exception:
            self._icon = None
        try:
            self.winId()
        except Exception:
            pass
        self._shape_anim = QVariantAnimation(self)
        self._shape_anim.setDuration(160)
        self._shape_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shape_anim.valueChanged.connect(self._on_shape_t)
        self._shape_anim.finished.connect(self._on_shape_finished)
        self._hl_phase = 0.0
        self._hl_timer = QTimer(self)
        self._hl_timer.setInterval(40)
        self._hl_timer.timeout.connect(self._on_hl_tick)
        self._hl_timer.start()

    def refresh_theme(self) -> None:
        try:
            if self._side == "left":
                self._icon = make_stow_right_icon(_COLOR_TEXT_SECONDARY, self._ICON)
            else:
                self._icon = make_expand_left_icon(_COLOR_TEXT_SECONDARY, self._ICON)
        except Exception:
            pass
        self.update()

    def _on_shape_t(self, v) -> None:
        try:
            self._shape_t = float(v)
        except Exception:
            self._shape_t = 0.0
        self.update()

    def _on_shape_finished(self) -> None:
        pass

    def _on_hl_tick(self) -> None:
        if self._hover or float(self._shape_t) > 0.15:
            if self._highlight != 0.0:
                self._highlight = 0.0
                self.repaint()
            return
        self._hl_phase = (self._hl_phase + 1.0 / 80.0) % 1.0
        self._highlight = 0.5 - 0.5 * math.cos(2.0 * math.pi * self._hl_phase)
        self.repaint()

    def _animate_shape(self, target: float) -> None:
        self._shape_anim.stop()
        self._shape_anim.setStartValue(float(self._shape_t))
        self._shape_anim.setEndValue(float(target))
        self._shape_anim.start()

    def set_app_hover(self, on: bool) -> None:
        on = bool(on)
        if on == self._hover:
            return
        self._hover = on
        if on:
            self._highlight = 0.0
            self._animate_shape(1.0)
        else:
            self._animate_shape(0.0)
            self._hl_phase = 0.0

    def enterEvent(self, event) -> None:
        self.set_app_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_app_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.restoreRequested.emit(getattr(self, "_side", "right"))
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            t = max(0.0, min(1.0, float(self._shape_t)))
            hl = float(self._highlight) if t < 0.15 else 0.0
            def _rgb(role):
                c = QColor(theme_color(role))
                return c.red(), c.green(), c.blue()

            dim_f = _rgb("SURFACE_RAISED")
            lit_f = _rgb("BORDER_ACCENT")
            dim_e = _rgb("BORDER_STRONG")
            lit_e = _rgb("ACCENT_SOFT")
            k = max(hl, t * 0.35)

            def _lerp(a, b, u):
                return tuple(
                    min(255, int(a[i] + (b[i] - a[i]) * u)) for i in range(3)
                )

            fr, fg, fb = _lerp(dim_f, lit_f, k)
            er, eg, eb = _lerp(dim_e, lit_e, k)
            face = QColor(fr, fg, fb)
            edge = QColor(er, eg, eb)
            s = float(self._VISUAL)
            r = s / 2.0
            if getattr(self, "_side", "right") == "left":
                cx = t * r
            else:
                cx = (self.width() - 1.0) - t * r
            cy = self.height() / 2.0
            path = QPainterPath()
            if t >= 0.995:
                path.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
            else:
                span = 180.0 + 180.0 * t
                if getattr(self, "_side", "right") == "left":
                    path.moveTo(cx, cy - r)
                    path.arcTo(cx - r, cy - r, 2 * r, 2 * r, 90.0, -span)
                else:
                    path.moveTo(cx, cy - r)
                    path.arcTo(cx - r, cy - r, 2 * r, 2 * r, 90.0, span)
                path.closeSubpath()
            p.setPen(QPen(edge, 1.2))
            p.setBrush(face)
            p.drawPath(path)
            if t > 0.5:
                icon = getattr(self, "_icon", None)
                if icon is not None:
                    pm = icon.pixmap(self._ICON, self._ICON)
                    if not pm.isNull():
                        p.setOpacity(min(1.0, (t - 0.5) / 0.5))
                        p.drawPixmap(
                            int(cx - self._ICON / 2),
                            int(cy - self._ICON / 2),
                            pm,
                        )
                        p.setOpacity(1.0)
        except Exception:
            pass
        finally:
            p.end()
