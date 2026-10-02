from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QTimer, QVariantAnimation, Qt, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui.icons import make_reset_widths_icon, make_stow_left_icon, make_stow_right_icon, _COLOR_ACCENT_SOFT
from src.ui.theme import color as theme_color


class BoundaryActionOverlay(QWidget):
    stowLeftRequested = Signal()
    stowRightRequested = Signal()
    resetRequested = Signal()
    resizeHandoffRequested = Signal(float)
    syncResizeCursorRequested = Signal()
    recheckHoverRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._t = 0.0
        self._cx = 0
        self._top = 0
        self._bot = 0
        self._stow_left_rect = None
        self._stow_right_rect = None
        self._stow_rect = None
        self._reset_rect = None
        self._press_on_action = False
        self._breathe = 0.0
        self._icon_stow_left = make_stow_left_icon(_COLOR_ACCENT_SOFT, 14)
        self._icon_stow_right = make_stow_right_icon(_COLOR_ACCENT_SOFT, 14)
        self._icon_reset = make_reset_widths_icon(_COLOR_ACCENT_SOFT, 14)
        self.setObjectName("boundary_interaction_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        # 境界上では resize 可能 → デフォルト SizeHor（ボタン上だけ PointingHand）
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setEnabled(True)
        self._breathe_anim = QVariantAnimation(self)
        self._breathe_anim.setDuration(1800)
        self._breathe_anim.setStartValue(0.0)
        self._breathe_anim.setEndValue(1.0)
        self._breathe_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._breathe_anim.setLoopCount(-1)
        self._breathe_anim.valueChanged.connect(self._on_breathe)
        try:
            self.winId()
        except Exception:
            pass

    def refresh_theme(self) -> None:
        self._icon_stow_left = make_stow_left_icon(_COLOR_ACCENT_SOFT, 14)
        self._icon_stow_right = make_stow_right_icon(_COLOR_ACCENT_SOFT, 14)
        self._icon_reset = make_reset_widths_icon(_COLOR_ACCENT_SOFT, 14)
        self.update()

    def _on_breathe(self, value) -> None:
        try:
            self._breathe = float(value)
        except (TypeError, ValueError):
            self._breathe = 0.0
        if self._t > 0.5 and self.isVisible():
            self.update()

    def _sync_breathe(self) -> None:
        anim = getattr(self, "_breathe_anim", None)
        if anim is None:
            return
        if self._t >= 0.95 and self.isVisible():
            if anim.state() != QVariantAnimation.State.Running:
                anim.start()
        else:
            if anim.state() == QVariantAnimation.State.Running:
                anim.stop()
            self._breathe = 0.0

    def set_state(self, cx: int, top: int, bot: int, t: float) -> None:
        self._cx = int(cx)
        self._top = int(top)
        self._bot = int(bot)
        self._t = max(0.0, min(1.0, float(t)))
        self._refresh_action_rects()
        self._sync_breathe()
        self.update()

    def _layout_metrics(self):
        t = self._t
        btn = 22
        fixed_w = 52
        if fixed_w % 2:
            fixed_w += 1
        h = max(40, self._bot - self._top)
        return t, btn, fixed_w, h

    def _get_action_rects(self, w: int, h: int, t: float, btn: int = 22):
        if t <= 0.02 or w < 4 or h < 20:
            return None, None, None
        s = min(max(26, btn + 6), max(26, (w - 6) // 2), max(26, h // 5))
        margin = 6
        gap = 2
        stow_y = margin
        reset_y = h - s - margin
        if reset_y < stow_y + s + 8:
            reset_y = stow_y + s + 8
        if reset_y + s > h:
            reset_y = max(0, h - s)
        pair = s * 2 + gap
        left_x = max(0, (w - pair) // 2)
        right_x = left_x + s + gap
        reset_x = max(0, min(w - s, (w - s) // 2))
        return (
            QRect(left_x, stow_y, s, s),
            QRect(right_x, stow_y, s, s),
            QRect(reset_x, reset_y, s, s),
        )

    def _get_visual_rects(self, hits, t: float, btn: int = 22):
        if not hits or any(h is None for h in hits):
            return tuple(None for _ in (hits or (None, None, None)))
        scale = 0.94 + 0.06 * t
        b = float(getattr(self, "_breathe", 0.0) or 0.0)
        tri = 1.0 - abs(2.0 * b - 1.0)
        scale *= 0.985 + 0.015 * tri
        vs = max(14, int(round(btn * scale)))
        out = []
        for hit in hits:
            vs2 = min(vs, hit.width() - 2, hit.height() - 2)
            if vs2 < 10:
                out.append(hit)
                continue
            x = hit.x() + (hit.width() - vs2) // 2
            y = hit.y() + (hit.height() - vs2) // 2
            out.append(QRect(x, y, vs2, vs2))
        return tuple(out)

    def _refresh_action_rects(self) -> None:
        t, btn, fixed_w, h = self._layout_metrics()
        w = max(1, self.width()) if self.width() > 0 else fixed_w
        hh = max(1, self.height()) if self.height() > 0 else h
        left, right, reset = self._get_action_rects(w, hh, t, btn)
        self._stow_left_rect = left
        self._stow_right_rect = right
        self._stow_rect = right
        self._reset_rect = reset
        self._apply_knob_mask()

    def _apply_knob_mask(self) -> None:
        try:
            self.clearMask()
        except Exception:
            pass

    def paintEvent(self, event) -> None:
        t, btn, fixed_w, h = self._layout_metrics()
        if t <= 0.02:
            self._stow_left_rect = None
            self._stow_right_rect = None
            self._stow_rect = None
            self._reset_rect = None
            self.clearMask()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        hh = self.height()
        left, right, reset = self._get_action_rects(w, hh, t, btn)
        self._stow_left_rect = left
        self._stow_right_rect = right
        self._stow_rect = right
        self._reset_rect = reset
        self._apply_knob_mask()
        v_left, v_right, v_reset = self._get_visual_rects(
            (self._stow_left_rect, self._stow_right_rect, self._reset_rect), t, btn
        )

        b = float(getattr(self, "_breathe", 0.0) or 0.0)
        tri = 1.0 - abs(2.0 * b - 1.0)
        lift = 1.0 + 0.04 * tri
        base_face = QColor(theme_color("SURFACE_RAISED"))
        base_edge = QColor(theme_color("BORDER_STRONG"))
        face = QColor(
            min(255, int(base_face.red() * lift)),
            min(255, int(base_face.green() * lift)),
            min(255, int(base_face.blue() * lift)),
        )
        edge = QColor(
            min(255, int(base_edge.red() * lift)),
            min(255, int(base_edge.green() * lift)),
            min(255, int(base_edge.blue() * lift)),
        )
        knob_op = t
        for r in (v_left, v_right, v_reset):
            if r is None:
                continue
            p.setOpacity(knob_op)
            p.setPen(QPen(edge, 1))
            p.setBrush(face)
            rad = min(r.width(), r.height()) / 2.0
            p.drawRoundedRect(r, rad, rad)
            p.setOpacity(1.0)

        for r, icon in (
            (v_left, self._icon_stow_left),
            (v_right, self._icon_stow_right),
            (v_reset, self._icon_reset),
        ):
            if r is None or icon is None:
                continue
            pm = icon.pixmap(14, 14)
            if pm.isNull():
                continue
            p.setOpacity(knob_op)
            ix = r.x() + (r.width() - 14) // 2
            iy = r.y() + (r.height() - 14) // 2
            p.drawPixmap(ix, iy, pm)
            p.setOpacity(1.0)
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._refresh_action_rects()
        pos = event.position().toPoint()
        self._press_gpos = event.globalPosition()
        self._handed_off = False
        on_left = self._stow_left_rect is not None and self._stow_left_rect.contains(pos)
        on_right = self._stow_right_rect is not None and self._stow_right_rect.contains(pos)
        on_reset = self._reset_rect is not None and self._reset_rect.contains(pos)
        self._press_on_action = bool(on_left or on_right or on_reset)
        event.accept()

    def _update_hover_cursor(self, pos) -> None:
        self._refresh_action_rects()
        if self._stow_left_rect is not None and self._stow_left_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._stow_right_rect is not None and self._stow_right_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._reset_rect is not None and self._reset_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        press_g = getattr(self, "_press_gpos", None)
        if press_g is None or getattr(self, "_handed_off", False):
            self._update_hover_cursor(pos)
            super().mouseMoveEvent(event)
            return
        if getattr(self, "_press_on_action", False):
            event.accept()
            return
        gp = event.globalPosition()
        if abs(gp.x() - press_g.x()) < 6:
            event.accept()
            return
        self._handed_off = True
        self.resizeHandoffRequested.emit(float(press_g.x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if getattr(self, "_handed_off", False):
            self._press_gpos = None
            self._press_on_action = False
            event.accept()
            return
        self._refresh_action_rects()
        pos = event.position().toPoint()
        if self._stow_left_rect is not None and self._stow_left_rect.contains(pos):
            self.stowLeftRequested.emit()
        elif self._stow_right_rect is not None and self._stow_right_rect.contains(pos):
            self.stowRightRequested.emit()
        elif self._reset_rect is not None and self._reset_rect.contains(pos):
            self.resetRequested.emit()
        self._press_gpos = None
        self._press_on_action = False
        event.accept()

    def leaveEvent(self, event) -> None:
        # Arrow 固定にしない。隣接 handle 上なら SizeHor を維持。
        self.syncResizeCursorRequested.emit()
        QTimer.singleShot(30, self.recheckHoverRequested.emit)
        super().leaveEvent(event)
