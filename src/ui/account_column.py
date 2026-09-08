from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QWidget,
    QMenu,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QFrame,
    QPushButton,
    QSizePolicy,
)
from PySide6.QtCore import (
    QSize, Qt, Signal, QEvent, QTimer, Property,
    QPropertyAnimation, QEasingCurve, QVariantAnimation,
)
from PySide6.QtGui import (
    QMouseEvent, QResizeEvent, QColor, QIcon, QPainter, QPixmap, QPolygonF,
    QPen, QPainterPath, QPaintEvent,
)
from PySide6.QtCore import QPointF, QRectF

from src.browser.webview import XWebView
from src.ui.icons import (
    make_home_icon,
    make_back_icon,
    make_forward_icon,
)
from src.ui import resize_debug as _rzdbg

_INTERNAL_ID_RE = re.compile(r"^[0-9a-f]{8}$")

class _UrlBar(QLineEdit):

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_url_context_menu)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def _style_menu(self, menu) -> None:
        try:
            from src.ui.theme import SURFACE, BORDER, TEXT, TEXT_MUTED, RADIUS_SM, dark_palette
            menu.setStyleSheet(
                f"QMenu {{ background-color: {SURFACE}; color: {TEXT};"
                f" border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px; padding: 4px; }}"
                f"QMenu::item {{ color: {TEXT}; padding: 5px 18px 5px 12px; border-radius: 4px; }}"
                f"QMenu::item:selected {{ background-color: rgba(148,178,230,0.18); color: {TEXT}; }}"
                f"QMenu::item:disabled {{ color: {TEXT_MUTED}; }}"
            )
            menu.setPalette(dark_palette())
        except Exception:
            menu.setStyleSheet(
                "QMenu { background:#181c26; color:#f1f3f7; border:1px solid #2b3242; }"
                "QMenu::item { color:#f1f3f7; padding:5px 18px 5px 12px; }"
                "QMenu::item:selected { background:rgba(148,178,230,0.18); color:#f1f3f7; }"
                "QMenu::item:disabled { color:#7f899a; }"
            )

    def _show_url_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu, QApplication
        from PySide6.QtGui import QAction
        menu = QMenu(self)
        self._style_menu(menu)
        text = self.text() or ""
        sel = self.selectedText() or ""
        clip = ""
        try:
            clip = QApplication.clipboard().text() or ""
        except Exception:
            pass
        can_edit = not self.isReadOnly()
        has_sel = bool(sel)
        has_text = bool(text.strip())
        act_undo = QAction("元に戻す", menu)
        act_redo = QAction("やり直す", menu)
        act_cut = QAction("切り取り", menu)
        act_copy = QAction("コピー", menu)
        act_paste = QAction("貼り付け", menu)
        act_sel = QAction("すべて選択", menu)
        act_undo.setEnabled(can_edit and bool(getattr(self, "isUndoAvailable", lambda: False)()))
        act_redo.setEnabled(can_edit and bool(getattr(self, "isRedoAvailable", lambda: False)()))
        act_cut.setEnabled(can_edit and has_sel)
        act_copy.setEnabled(has_sel or has_text)
        act_paste.setEnabled(bool(clip.strip()))
        act_sel.setEnabled(has_text)
        act_undo.triggered.connect(lambda _checked=False: self.undo())
        act_redo.triggered.connect(lambda _checked=False: self.redo())
        act_cut.triggered.connect(lambda _checked=False: self.cut())
        act_copy.triggered.connect(lambda _checked=False: self._copy_url_text())
        act_paste.triggered.connect(lambda _checked=False: self._paste_url_text())
        act_sel.triggered.connect(lambda _checked=False: self.selectAll())
        menu.addAction(act_undo)
        menu.addAction(act_redo)
        menu.addSeparator()
        menu.addAction(act_cut)
        menu.addAction(act_copy)
        menu.addAction(act_paste)
        menu.addSeparator()
        menu.addAction(act_sel)
        menu.exec(self.mapToGlobal(pos))

    def _copy_url_text(self) -> None:
        from PySide6.QtWidgets import QApplication
        text = self.selectedText()
        if not text:
            text = self.text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste_url_text(self) -> None:
        from PySide6.QtWidgets import QApplication
        clip = (QApplication.clipboard().text() or "").strip()
        if not clip:
            return
        self.setText(clip)
        self.setToolTip(clip)
        self.clicked.emit()

class _BoundaryHandle(QWidget):

    stow_right_clicked = Signal()
    reset_widths_clicked = Signal()

    _IDLE_WIDTH = 5
    _RESIZE_HIT_HALF = 1

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("column_resize_handle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setMouseTracking(True)
        self.setFixedWidth(self._IDLE_WIDTH)
        self._bar = QWidget(self)
        self._bar.setObjectName("boundary_hint_bar")
        self._hint = False
        self._active = False
        self._actions_visible = False
        self._expand = 0.0
        self._btn_reset = None
        self._btn_stow = None

        self._expand_anim = QVariantAnimation(self)
        self._expand_anim.setDuration(180)
        self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._expand_anim.valueChanged.connect(self._on_expand_changed)
        self._expand_anim.finished.connect(self._on_expand_finished)

    def _on_expand_changed(self, value) -> None:
        try:
            self._expand = float(value)
        except (TypeError, ValueError):
            self._expand = 0.0
        self._apply_expand_layout()

    def set_hint(self, active: bool) -> None:
        if active != self._hint:
            self._hint = active
            self.setProperty("hint", active)
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            style.unpolish(self._bar)
            style.polish(self._bar)
            self._bar.update()

    def _position_bar(self) -> None:
        bw = 1
        self._bar.setGeometry((self.width() - bw) // 2, 0, bw, self.height())
        if self._actions_visible:
            self._apply_expand_layout()

    def _boundary_pivot_in_window(self):
        win = self.window()
        if win is None:
            return None
        c = self.mapTo(win, self.rect().center())
        top = self.mapTo(win, self.rect().topLeft())
        bot = self.mapTo(win, self.rect().bottomLeft())
        return win, int(c.x()), int(top.y()), int(bot.y())

    def _apply_expand_layout(self) -> None:
        pivot = self._boundary_pivot_in_window()
        if pivot is None:
            return
        win, cx, top, bot = pivot
        fn = getattr(win, "update_boundary_actions", None)
        if callable(fn):
            fn(cx, top, bot, float(self._expand), self._owner_column())

    def _position_action_buttons(self) -> None:
        self._apply_expand_layout()

    def _animate_expand(self, target: float) -> None:
        self._expand_anim.stop()
        self._expand_anim.setStartValue(float(self._expand))
        self._expand_anim.setEndValue(float(target))
        self._expand_anim.start()

    def _show_actions(self, show: bool) -> None:
        if self._active:
            show = False
        show = bool(show)
        if show and self._actions_visible and float(self._expand) > 0.5:
            return
        if (not show) and (not self._actions_visible) and float(self._expand) < 0.05:
            return
        self._actions_visible = show
        if show:
            self._expand = 0.0
            self.set_hint(True)
            self._apply_expand_layout()
            self._animate_expand(1.0)
        else:
            self._animate_expand(0.0)
            QTimer.singleShot(160, self._hide_actions_if_collapsed)

    def _on_expand_finished(self) -> None:
        if self._actions_visible:
            return
        if float(self._expand) > 0.05:
            return
        self.set_hint(False)
        win = self.window()
        hide = getattr(win, "hide_boundary_actions", None) if win is not None else None
        if callable(hide):
            hide()

    def _hide_actions_if_collapsed(self) -> None:
        self._on_expand_finished()

    def enterEvent(self, event) -> None:
        if self._active:
            super().enterEvent(event)
            return
        if not self._actions_visible:
            self.set_hint(True)
            self._show_actions(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        QTimer.singleShot(40, self._maybe_hide_actions)
        super().leaveEvent(event)

    def _maybe_hide_actions(self) -> None:
        if self._active:
            return
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        if self.rect().contains(self.mapFromGlobal(pos)):
            return
        win = self.window()
        over = getattr(win, "boundary_actions_contain_global", None) if win is not None else None
        if callable(over) and over(pos):
            return
        self.set_hint(False)
        self._show_actions(False)

    _WINDOW_EDGE_MARGIN = 2

    def _yield_to_window_resize(self, event: QMouseEvent) -> bool:
        top = self.window()
        if top is None:
            return False
        if getattr(top, "_edge_dock_enabled", False) and getattr(top, "_edge_dock_revealed", False):
            return False
        local = top.mapFromGlobal(event.globalPosition().toPoint())
        m = self._WINDOW_EDGE_MARGIN
        near_edge = (
            local.x() < m or local.x() >= top.width() - m
            or local.y() < m or local.y() >= top.height() - m
        )
        if not near_edge:
            _rzdbg.log(
                "boundary_press",
                action="column_resize",
                local=(local.x(), local.y()),
                window_size=(top.width(), top.height()),
                margin=m,
            )
            return False
        wh = top.windowHandle()
        if wh is None:
            _rzdbg.log("boundary_yield_fail", reason="no_window_handle")
            return False
        edges = Qt.Edges(0)
        if local.x() < m:
            edges |= Qt.Edge.LeftEdge
        elif local.x() >= top.width() - m:
            edges |= Qt.Edge.RightEdge
        if local.y() < m:
            edges |= Qt.Edge.TopEdge
        elif local.y() >= top.height() - m:
            edges |= Qt.Edge.BottomEdge
        ok = wh.startSystemResize(edges)
        _rzdbg.log(
            "startSystemResize",
            source="boundary_yield",
            edges=int(edges),
            ok=bool(ok),
            local=(local.x(), local.y()),
            window_size=(top.width(), top.height()),
        )
        return True

    def _try_boundary_action_click(self, event: QMouseEvent) -> bool:
        win = self.window()
        if win is None:
            return False
        ov = getattr(win, "_boundary_overlay", None)
        if ov is None or not ov.isVisible() or float(getattr(ov, "_t", 0.0)) <= 0.02:
            return False
        try:
            if hasattr(ov, "_refresh_action_rects"):
                ov._refresh_action_rects()
            local = ov.mapFromGlobal(event.globalPosition().toPoint())
            stow = getattr(ov, "_stow_rect", None)
            reset = getattr(ov, "_reset_rect", None)
            print(
                f"[ResizeHandle] press global→overlay local=({local.x()},{local.y()}) "
                f"stow={stow} reset={reset}",
                flush=True,
            )
            if stow is not None and stow.contains(local):
                print("[ResizeHandle] hit=STOW → dispatch Stow (not Resize)", flush=True)
                fn = getattr(win, "_on_boundary_stow_clicked", None)
                if callable(fn):
                    fn()
                return True
            if reset is not None and reset.contains(local):
                print("[ResizeHandle] hit=RESET → dispatch Reset (not Resize)", flush=True)
                fn = getattr(win, "_on_boundary_reset_clicked", None)
                if callable(fn):
                    fn()
                return True
        except Exception as e:
            print(f"[ResizeHandle] boundary action check failed: {e}", flush=True)
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._yield_to_window_resize(event):
                event.accept()
                return
            if self._try_boundary_action_click(event):
                event.accept()
                return
            local_x = event.position().toPoint().x()
            cx = self.width() // 2
            if abs(local_x - cx) > self._RESIZE_HIT_HALF + 1:
                event.accept()
                return
            print("[ResizeHandle] mousePress → column Resize drag", flush=True)
            _rzdbg.log("boundary_press", action="column_drag_start")
            self._active = True
            self._expand_anim.stop()
            self._actions_visible = False
            self._expand = 0.0
            win = self.window()
            hide = getattr(win, "hide_boundary_actions", None) if win is not None else None
            if callable(hide):
                hide()
            self.set_hint(True)
            self._position_bar()
            self._press_x = event.globalPosition().x()
            self.raise_()
            self.setProperty("dragging", True)
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def begin_external_drag(self, global_x: float) -> None:
        self._active = True
        self._expand_anim.stop()
        self._actions_visible = False
        self._expand = 0.0
        win = self.window()
        hide = getattr(win, "hide_boundary_actions", None) if win is not None else None
        if callable(hide):
            hide()
        self.set_hint(True)
        self._position_bar()
        self._press_x = float(global_x)
        self.raise_()
        self.setProperty("dragging", True)
        self.grabMouse()

    def _owner_column(self):
        w = self.parentWidget()
        while w is not None:
            if type(w).__name__ == "AccountColumn":
                return w
            w = w.parentWidget()
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active and event.buttons() & Qt.MouseButton.LeftButton:
            delta = int(event.globalPosition().x() - self._press_x)
            col = self._owner_column()
            if col is not None:
                col.boundary_dragged.emit(delta)
            event.accept()
            return
        if self._try_boundary_action_hover_cursor(event):
            event.accept()
            return
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        super().mouseMoveEvent(event)

    def _try_boundary_action_hover_cursor(self, event: QMouseEvent) -> bool:
        win = self.window()
        if win is None:
            return False
        ov = getattr(win, "_boundary_overlay", None)
        if ov is None or not ov.isVisible() or float(getattr(ov, "_t", 0.0)) <= 0.02:
            return False
        try:
            if hasattr(ov, "_refresh_action_rects"):
                ov._refresh_action_rects()
            local = ov.mapFromGlobal(event.globalPosition().toPoint())
            stow = getattr(ov, "_stow_rect", None)
            reset = getattr(ov, "_reset_rect", None)
            if (stow is not None and stow.contains(local)) or (
                reset is not None and reset.contains(local)
            ):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return True
        except Exception:
            pass
        return False

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._active and event.button() == Qt.MouseButton.LeftButton:
            self._active = False
            self.setProperty("dragging", False)
            self.set_hint(False)
            self.releaseMouse()
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            col = self._owner_column()
            if col is not None:
                col.boundary_drag_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

class _ColumnDragHandle(QWidget):

    REORDER_START_DISTANCE = 8

    pressed_drag = Signal()
    moved_drag = Signal(float)
    released_drag = Signal(float)
    cancelled_drag = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("col_drag_handle")
        self.setFixedSize(20, 28)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("ドラッグしてカラムを並べ替え")
        self._pressed = False
        self._dragging = False
        self._press_x = 0.0
        self._press_y = 0.0
        try:
            from src.ui.icons import make_column_grip_icon
            self._icon = make_column_grip_icon("#9fb4d8", 16)
            self._icon_active = make_column_grip_icon("#eaf1fb", 16)
        except Exception:
            self._icon = None
            self._icon_active = None
        self.setFixedSize(20, 28)
        self.setStyleSheet(
            "QWidget#col_drag_handle { background: transparent; border: 1px solid transparent; border-radius: 4px; }"
            "QWidget#col_drag_handle:hover { background: rgba(148,178,230,0.18); border: 1px solid #3d6a9e; }"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        icon = None
        if self._dragging and getattr(self, "_icon_active", None) is not None:
            icon = self._icon_active
        else:
            icon = self._icon
        if icon is None:
            return
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        pm = icon.pixmap(16, 16)
        x = (self.width() - pm.width()) // 2
        y = (self.height() - pm.height()) // 2
        p.drawPixmap(x, y, pm)
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            gp = event.globalPosition()
            self._pressed = True
            self._dragging = False
            self._press_x = float(gp.x())
            self._press_y = float(gp.y())
            self.grabMouse()
            self.pressed_drag.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._pressed:
            super().mouseMoveEvent(event)
            return
        gp = event.globalPosition()
        gx = float(gp.x())
        gy = float(gp.y())
        if not self._dragging:
            dx = abs(gx - self._press_x)
            dy = abs(gy - self._press_y)
            if max(dx, dy) < self.REORDER_START_DISTANCE:
                event.accept()
                return
            self._dragging = True
        self.moved_drag.emit(gx)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._pressed = False
            self._dragging = False
            try:
                self.releaseMouse()
            except Exception:
                pass
            gx = float(event.globalPosition().x())
            if was_dragging:
                self.released_drag.emit(gx)
            else:
                self.cancelled_drag.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

class RefreshMotionButton(QToolButton):

    _IDLE = 0
    _PRESS = 1
    _FLOW = 2
    _REFRESHING = 3
    _COMPLETING = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setObjectName("reload_btn")
        self.setToolTip("再読み込み")
        self.setText("")
        self.setIcon(QIcon())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._state = self._IDLE
        self._phase = 0.0
        self._press_t = 0.0
        self._flow_t = 0.0
        self._complete_t = 0.0
        self._load_active = False
        self._load_started_at = 0.0
        self._min_refresh_ms = 220.0
        self._pending_complete = False
        self._load_gen = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self.clicked.connect(self._on_clicked_motion)

    def bind_webview(self, wv) -> None:
        prev = getattr(self, "_bound_wv", None)
        if prev is not None and prev is not wv:
            for sig, slot in (
                ("loadStarted", self.on_load_started),
                ("loadFinished", self.on_load_finished),
            ):
                try:
                    getattr(prev, sig).disconnect(slot)
                except Exception:
                    pass
        self._bound_wv = wv
        if wv is None:
            return
        try:
            wv.loadStarted.connect(self.on_load_started)
        except Exception:
            pass
        try:
            wv.loadFinished.connect(self.on_load_finished)
        except Exception:
            pass

    def _on_clicked_motion(self) -> None:
        if self._state in (self._REFRESHING, self._FLOW):
            self._enter_press()
            return
        self._enter_press()

    def _enter_press(self) -> None:
        self._state = self._PRESS
        self._press_t = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def on_load_started(self) -> None:
        import time as _t
        self._load_gen += 1
        self._load_active = True
        self._pending_complete = False
        self._load_started_at = _t.monotonic()
        if self._state in (self._IDLE, self._PRESS, self._COMPLETING):
            self._state = self._FLOW
            self._flow_t = 0.0
        elif self._state != self._REFRESHING:
            self._state = self._REFRESHING
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def on_load_finished(self, _ok: bool = True) -> None:
        import time as _t
        gen = int(self._load_gen)
        self._load_active = False
        if self._state in (self._IDLE,):
            return
        elapsed = (_t.monotonic() - self._load_started_at) * 1000.0
        if elapsed < self._min_refresh_ms and self._state in (
            self._FLOW, self._REFRESHING, self._PRESS
        ):
            self._pending_complete = True
            remain = max(0, int(self._min_refresh_ms - elapsed))
            QTimer.singleShot(remain, lambda g=gen: self._begin_complete_for(g))
            return
        self._begin_complete_for(gen)

    def _begin_complete_for(self, gen: int) -> None:
        if gen != int(self._load_gen):
            return
        if self._load_active:
            return
        self._begin_complete()

    def _begin_complete(self) -> None:
        if self._load_active:
            return
        self._pending_complete = False
        self._state = self._COMPLETING
        self._complete_t = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _on_tick(self) -> None:
        dt = 0.016
        st = self._state
        if st == self._PRESS:
            self._press_t += dt
            if self._press_t >= 0.07:
                if self._load_active:
                    self._state = self._FLOW
                    self._flow_t = 0.0
                else:
                    self._state = self._FLOW
                    self._flow_t = 0.0
        elif st == self._FLOW:
            self._flow_t += dt
            if self._flow_t >= 0.22:
                self._state = self._REFRESHING
                self._phase = 0.0
        elif st == self._REFRESHING:
            self._phase = (self._phase + dt / 1.15) % 1.0
            if self._pending_complete and not self._load_active:
                self._begin_complete()
                return
        elif st == self._COMPLETING:
            self._complete_t += dt
            if self._complete_t >= 0.16:
                self._state = self._IDLE
                self._phase = 0.0
                self._timer.stop()
        else:
            self._timer.stop()
            return
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = min(self.width(), self.height()) * 0.22
        idle_c = QColor("#aeb6c5")
        accent = QColor("#4a7ec7")
        bright = QColor("#7aa3d9")

        st = self._state
        if st == self._IDLE:
            self._draw_refresh_icon(p, cx, cy, r, idle_c, full=True)
        elif st == self._PRESS:
            k = 1.0 - 0.06 * min(1.0, self._press_t / 0.07)
            self._draw_refresh_icon(p, cx, cy, r * k, idle_c, full=True, pen_w=1.35)
        elif st == self._FLOW:
            t = min(1.0, self._flow_t / 0.22)
            te = 1.0 - (1.0 - t) ** 3
            self._draw_flowing_arc(p, cx, cy, r, accent, te, head=0.35 + 0.25 * te)
        elif st == self._REFRESHING:
            import math
            ph = self._phase
            breath = 0.5 + 0.5 * math.sin(ph * math.pi * 2)
            head = 0.28 + 0.22 * breath
            gap = 0.18 + 0.12 * (1.0 - breath)
            self._draw_flowing_arc(
                p, cx, cy, r, accent, ph, head=head, gap=gap, pen_w=1.55
            )
        elif st == self._COMPLETING:
            t = min(1.0, self._complete_t / 0.16)
            te = 1.0 - (1.0 - t) ** 2
            if te < 0.55:
                self._draw_flowing_arc(
                    p, cx, cy, r, bright, 0.15 + 0.5 * te, head=0.55, gap=0.08, pen_w=1.7
                )
            else:
                self._draw_refresh_icon(p, cx, cy, r, idle_c, full=True, pen_w=1.5)
        p.end()

    def _draw_refresh_icon(
        self, p: QPainter, cx: float, cy: float, r: float, color: QColor,
        *, full: bool = True, pen_w: float = 1.45,
    ) -> None:
        import math
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.drawArc(rect, int(40 * 16), int(140 * 16))
        p.drawArc(rect, int(220 * 16), int(140 * 16))
        self._arrow_tip(p, cx, cy, r, math.radians(40 + 140), color, pen_w)
        self._arrow_tip(p, cx, cy, r, math.radians(220 + 140), color, pen_w)

    def _arrow_tip(
        self, p: QPainter, cx: float, cy: float, r: float, angle: float, color: QColor, pen_w: float
    ) -> None:
        import math
        x = cx + r * math.cos(angle)
        y = cy - r * math.sin(angle)
        tx, ty = -math.sin(angle), -math.cos(angle)
        nx, ny = math.cos(angle), -math.sin(angle)
        s = max(2.2, pen_w * 1.6)
        path = QPainterPath()
        path.moveTo(x - tx * s + nx * s * 0.35, y - ty * s + ny * s * 0.35)
        path.lineTo(x, y)
        path.lineTo(x - tx * s - nx * s * 0.35, y - ty * s - ny * s * 0.35)
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_flowing_arc(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        color: QColor,
        phase: float,
        *,
        head: float = 0.4,
        gap: float = 0.2,
        pen_w: float = 1.55,
    ) -> None:
        import math
        pen = QPen(color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start_deg = (phase * 360.0) % 360.0
        span = max(40.0, min(300.0, head * 360.0))
        trail = max(20.0, span * 0.45)
        gap_deg = max(12.0, gap * 360.0)
        c2 = QColor(color)
        c2.setAlpha(160)
        p.drawArc(rect, int(start_deg * 16), int(-span * 16))
        pen2 = QPen(c2, max(1.1, pen_w * 0.85), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        p.drawArc(rect, int((start_deg + span + gap_deg) * 16), int(-trail * 16))
        head_a = math.radians(start_deg)
        hx = cx + r * math.cos(head_a)
        hy = cy - r * math.sin(head_a)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(hx, hy), pen_w * 0.85, pen_w * 0.85)

class AccountColumn(QWidget):

    closed = Signal()
    resized = Signal(int)
    enabled_changed = Signal(bool)
    boundary_dragged = Signal(int)
    boundary_drag_finished = Signal()
    stow_right_requested = Signal(object)
    reset_widths_requested = Signal()
    reorder_requested = Signal(float)
    reorder_drag_moved = Signal(float)
    reorder_drag_finished = Signal()
    activated = Signal()
    tabs_changed = Signal()
    current_tab_changed = Signal(int)
    tab_title_changed = Signal()
    new_tab_requested = Signal(str)
    url_edit_requested = Signal()

    RESIZE_HANDLE_WIDTH = 3
    MIN_WIDTH = 200
    DEFAULT_WIDTH = 400
    LONG_PRESS_MS = 500
    DRAG_ABORT_PX = 8

    def __init__(
        self,
        account_id: str,
        display_name: str,
        webview: XWebView,
        width: int = DEFAULT_WIDTH,
        enabled: bool = True,
        initial_url: str = "",
        column_id: str = "",
        column_type: str = "home",
        title: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._account_id = account_id
        self._display_name = (display_name or "").strip()
        if column_id:
            self._column_id = str(column_id)
        else:
            from uuid import uuid4
            self._column_id = f"col_{account_id}_{uuid4().hex[:10]}"
        self._column_type = column_type
        self._title = title
        self._webview = webview
        self._tabs: list[XWebView] = [webview]
        self._current_tab = 0
        self._current_web_url = ""
        self._enabled = enabled
        self._initial_url = initial_url
        self._loaded_once = False

        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._current_width = width
        self.set_width(width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_frame = QFrame()
        nav_frame.setObjectName("column_nav")
        nav_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        nav_bar = QHBoxLayout(nav_frame)
        nav_bar.setContentsMargins(2, 2, 2, 2)
        nav_bar.setSpacing(2)

        self._back_btn = QToolButton()
        self._back_btn.setIcon(make_back_icon("#aeb6c5", 14))
        self._back_btn.setIconSize(QSize(14, 14))
        self._back_btn.setText("")
        self._back_btn.setFixedSize(26, 26)
        self._back_btn.setObjectName("back_btn")
        self._back_btn.setToolTip("戻る")
        self._back_btn.clicked.connect(self._on_back)
        nav_bar.addWidget(self._back_btn)

        self._forward_btn = QToolButton()
        self._forward_btn.setIcon(make_forward_icon("#aeb6c5", 14))
        self._forward_btn.setIconSize(QSize(14, 14))
        self._forward_btn.setText("")
        self._forward_btn.setFixedSize(26, 26)
        self._forward_btn.setObjectName("forward_btn")
        self._forward_btn.setToolTip("進む")
        self._forward_btn.clicked.connect(self._on_forward)
        nav_bar.addWidget(self._forward_btn)
        self._nav_hist_bound_page = None

        self._reload_btn = RefreshMotionButton(self)
        self._reload_btn.clicked.connect(self._on_reload)
        nav_bar.addWidget(self._reload_btn)

        self._home_btn = QToolButton()
        self._home_btn.setIcon(make_home_icon("#aeb6c5", 16))
        self._home_btn.setIconSize(QSize(16, 16))
        self._home_btn.setText("")
        self._home_btn.setFixedSize(26, 26)
        self._home_btn.setObjectName("home_btn")
        self._home_btn.setToolTip("初期ページへ戻る")
        self._home_btn.clicked.connect(self.go_home)
        nav_bar.addWidget(self._home_btn)

        self._col_drag_handle = _ColumnDragHandle(self)
        self._col_drag_handle.pressed_drag.connect(self._on_col_grip_pressed)
        self._col_drag_handle.moved_drag.connect(self._on_col_grip_moved)
        self._col_drag_handle.released_drag.connect(self._on_col_grip_released)
        self._col_drag_handle.cancelled_drag.connect(self._on_col_grip_cancelled)
        nav_bar.addWidget(self._col_drag_handle, 0)

        self._url_bar = _UrlBar()
        self._url_bar.setObjectName("url_bar")
        self._url_bar.setPlaceholderText("URL または検索キーワード")
        self._url_bar.setMinimumHeight(26)
        self._url_bar.clicked.connect(self.url_edit_requested)
        nav_bar.addWidget(self._url_bar, 1)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setObjectName("close_btn")
        close_btn.setToolTip("カラムを閉じる")
        close_btn.clicked.connect(self._on_close)
        nav_bar.addWidget(close_btn)

        layout.addWidget(nav_frame)

        self._body = QWidget(self)
        self._body.setObjectName("column_body")
        body_row = QHBoxLayout(self._body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)
        body_row.addWidget(webview, 1)
        self._resize_handle = _BoundaryHandle(self._body)
        self._resize_handle.setFixedWidth(AccountColumn.RESIZE_HANDLE_WIDTH)
        self._resize_handle.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._resize_handle.stow_right_clicked.connect(
            lambda: self.stow_right_requested.emit(self)
        )
        self._resize_handle.reset_widths_clicked.connect(self.reset_widths_requested.emit)
        self._resize_handle.hide()
        body_row.addWidget(self._resize_handle, 0)
        layout.addWidget(self._body, 1)

        for nav_btn in (
            self._back_btn,
            self._forward_btn,
            self._reload_btn,
            self._home_btn,
            close_btn,
        ):
            nav_btn.pressed.connect(self.activated)

        if hasattr(webview, 'url_changed'):
            webview.url_changed.connect(
                lambda url, w=webview: self._on_webview_url_changed(w, url)
            )
        if hasattr(webview, 'pressed'):
            webview.pressed.connect(self.activated)
        if hasattr(webview, 'titleChanged'):
            webview.titleChanged.connect(lambda *_: self.tab_title_changed.emit())
        webview.tab_opener = self.new_tab_requested.emit
        try:
            self._reload_btn.bind_webview(webview)
        except Exception:
            pass
        try:
            self._bind_nav_history(webview)
        except Exception:
            pass

        self._drag_armed = False
        self._drag_press_x = 0.0
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(self.LONG_PRESS_MS)
        self._drag_timer.timeout.connect(self._arm_drag)
        self._nav_frame = nav_frame
        self._profile_resolve_attempted = False
        self._profile_resolve_retries = 0
        self._profile_state = "IDLE"
        self._profile_tried_settings = False
        self._profile_waiting_self_redirect = False
        self._resolve_request_id = 0
        self._lists_resolved_url = ""
        self._nav_target_lock = ""
        if self._column_type == "profile":
            QTimer.singleShot(0, self._bootstrap_profile)
        elif self._column_type == "lists":
            QTimer.singleShot(0, self._bootstrap_lists)

    def add_tab_view(self, webview) -> int:
        if webview in self._tabs:
            return self._tabs.index(webview)
        self._tabs.append(webview)
        body_lay = self._body.layout()
        if body_lay is not None:
            body_lay.insertWidget(max(0, body_lay.count() - 1), webview, 1)
        else:
            self.layout().addWidget(webview, 1)
        webview.hide()
        if hasattr(webview, 'url_changed'):
            webview.url_changed.connect(
                lambda url, w=webview: self._on_webview_url_changed(w, url)
            )
        if hasattr(webview, 'pressed'):
            webview.pressed.connect(self.activated)
        if hasattr(webview, 'titleChanged'):
            webview.titleChanged.connect(lambda *_: self.tab_title_changed.emit())
        webview.tab_opener = self.new_tab_requested.emit
        index = len(self._tabs) - 1
        self.set_current_tab(index)
        self.tabs_changed.emit()
        self.activated.emit()
        return index

    def set_current_tab(self, index: int) -> None:
        if not (0 <= index < len(self._tabs)):
            return
        previous = self._current_tab
        self._current_tab = index
        for i, tab in enumerate(self._tabs):
            tab.setVisible(i == index)
        active = self._tabs[index]
        try:
            active.raise_()
        except Exception:
            pass
        pending = getattr(active, "_pending_restore_url", None)
        if pending:
            try:
                active._pending_restore_url = None
            except Exception:
                pass
            try:
                active.load_url(str(pending), restore=True)
            except TypeError:
                try:
                    active.load_url(str(pending))
                except Exception:
                    pass
            except Exception:
                pass
        url_getter = getattr(active, "get_current_url", None)
        self._on_url_changed(url_getter() if callable(url_getter) else "")
        if previous != index:
            self.current_tab_changed.emit(index)
        try:
            self._reload_btn.bind_webview(active)
        except Exception:
            pass
        try:
            self._bind_nav_history(active)
        except Exception:
            pass

    def _bind_nav_history(self, wv) -> None:
        prev_page = getattr(self, "_nav_hist_bound_page", None)
        page = None
        try:
            page = wv.page() if wv is not None else None
        except Exception:
            page = None
        if prev_page is not None and prev_page is not page:
            try:
                hist = prev_page.history()
                hist.historyChanged.disconnect(self._update_nav_history_buttons)
            except Exception:
                pass
            try:
                prev_page.urlChanged.disconnect(self._update_nav_history_buttons)
            except Exception:
                pass
        self._nav_hist_bound_page = page
        if page is None:
            self._update_nav_history_buttons()
            return
        try:
            hist = page.history()
            hist.historyChanged.connect(self._update_nav_history_buttons)
        except Exception:
            pass
        try:
            page.urlChanged.connect(self._update_nav_history_buttons)
        except Exception:
            pass
        self._update_nav_history_buttons()

    def _update_nav_history_buttons(self, *_args) -> None:
        can_back = False
        can_fwd = False
        try:
            wv = self.current_webview()
            page = wv.page() if wv is not None else None
            if page is not None:
                hist = page.history()
                can_back = bool(hist.canGoBack())
                can_fwd = bool(hist.canGoForward())
        except Exception:
            pass
        on = "#aeb6c5"
        off = "#5c6474"
        try:
            self._back_btn.setIcon(make_back_icon(on if can_back else off, 14))
            self._forward_btn.setIcon(make_forward_icon(on if can_fwd else off, 14))
        except Exception:
            pass

    def _enforce_single_visible_tab(self) -> None:
        if not self._tabs:
            return
        idx = self._current_tab if 0 <= self._current_tab < len(self._tabs) else 0
        self._current_tab = idx
        for i, tab in enumerate(self._tabs):
            want = i == idx
            tab.setVisible(want)
        try:
            self._tabs[idx].raise_()
        except Exception:
            pass

    def close_tab(self, index: int) -> None:
        if not (0 <= index < len(self._tabs)):
            return
        closing_last = len(self._tabs) == 1
        if closing_last:
            self.closed.emit()
            return
        tab = self._tabs.pop(index)
        body_lay = self._body.layout() if getattr(self, "_body", None) is not None else None
        if body_lay is not None:
            body_lay.removeWidget(tab)
        else:
            self.layout().removeWidget(tab)
        tab.hide()
        tab.deleteLater()
        if self._current_tab >= len(self._tabs):
            self._current_tab = len(self._tabs) - 1
        elif self._current_tab > index:
            self._current_tab -= 1
        self.set_current_tab(self._current_tab)
        self.tabs_changed.emit()

    def move_tab(self, from_index: int, to_index: int) -> None:
        count = len(self._tabs)
        if not (0 <= from_index < count):
            return
        to_index = max(0, min(to_index, count - 1))
        if to_index == from_index:
            return
        tab = self._tabs.pop(from_index)
        self._tabs.insert(to_index, tab)
        if self._current_tab == from_index:
            self._current_tab = to_index
        elif from_index < self._current_tab <= to_index:
            self._current_tab -= 1
        elif to_index <= self._current_tab < from_index:
            self._current_tab += 1
        self.tabs_changed.emit()

    def current_webview(self) -> XWebView:
        return self._tabs[self._current_tab]

    def get_tab_count(self) -> int:
        return len(self._tabs)

    def export_tabs_state(self) -> dict:
        tabs_out = []
        for wv in list(self._tabs):
            url = ""
            try:
                getter = getattr(wv, "get_current_url", None)
                if callable(getter):
                    url = (getter() or "").strip()
                if not url and hasattr(wv, "url") and callable(wv.url):
                    u = wv.url()
                    url = (u.toString() if hasattr(u, "toString") else str(u) or "").strip()
            except Exception:
                url = ""
            if not url or url.startswith("about:") or url.startswith("data:"):
                url = (getattr(self, "_initial_url", None) or "") if not tabs_out else ""
            tabs_out.append({"url": url or ""})
        active = int(getattr(self, "_current_tab", 0) or 0)
        if tabs_out:
            active = max(0, min(active, len(tabs_out) - 1))
        else:
            active = 0
            tabs_out = [{"url": (self._initial_url or "").strip()}]
        return {"tabs": tabs_out, "active_tab": active}

    def get_current_tab_url(self) -> str:
        live = ""
        try:
            wv = self.current_webview()
            if wv is not None:
                getter = getattr(wv, "get_current_url", None)
                if callable(getter):
                    live = (getter() or "").strip()
                if not live and hasattr(wv, "url") and callable(wv.url):
                    try:
                        u = wv.url()
                        live = u.toString() if hasattr(u, "toString") else str(u)
                        live = (live or "").strip()
                    except Exception:
                        live = ""
        except Exception:
            live = ""
        if live and live not in ("about:blank", "data:"):
            self._current_web_url = live
            return live
        cur = (self._current_web_url or "").strip()
        if cur:
            return cur
        return (self._initial_url or "").strip()

    def tab_views(self) -> list:
        return list(self._tabs)

    def tab_count(self) -> int:
        return len(self._tabs)

    def webviews(self) -> list[XWebView]:
        return list(self._tabs)

    def navigate(self, url: str) -> None:
        if self._enabled:
            self.current_webview().load_url(url)

    def _on_col_grip_pressed(self) -> None:
        self.activated.emit()
        self._drag_armed = False
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                print(f"[REORDER] press column={getattr(self, 'get_column_id', lambda: '?')()}", flush=True)
        except Exception:
            pass

    def _on_col_grip_moved(self, global_x: float) -> None:
        if not self._drag_armed:
            self._drag_armed = True
            self._arm_drag()
            try:
                import os
                if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                    print(f"[REORDER] drag_start x={global_x}", flush=True)
            except Exception:
                pass
        try:
            self.reorder_drag_moved.emit(float(global_x))
        except Exception:
            pass

    def _on_col_grip_released(self, global_x: float) -> None:
        if not self._drag_armed:
            return
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                print(f"[REORDER] release commit x={global_x}", flush=True)
        except Exception:
            pass
        try:
            self.reorder_requested.emit(float(global_x))
        except Exception:
            pass
        self._disarm_drag(emit_finished=False)
        try:
            self.reorder_drag_finished.emit()
        except Exception:
            pass

    def _on_col_grip_cancelled(self) -> None:
        try:
            import os
            if os.environ.get("MAYOTTER_COLUMN_DEBUG"):
                print("[REORDER] cancel (click / sub-threshold)", flush=True)
        except Exception:
            pass
        was = self._drag_armed
        self._disarm_drag(emit_finished=False)
        if was:
            try:
                self.reorder_drag_finished.emit()
            except Exception:
                pass

    def _arm_drag(self) -> None:
        self._drag_armed = True
        handle = getattr(self, "_col_drag_handle", None)
        if handle is not None:
            handle.setCursor(Qt.CursorShape.SizeAllCursor)
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            if getattr(self, "_reorder_opacity_effect", None) is None:
                eff = QGraphicsOpacityEffect(self)
                self._reorder_opacity_effect = eff
                self.setGraphicsEffect(eff)
            self._reorder_opacity_effect.setOpacity(0.85)
        except Exception:
            pass
        try:
            self._reorder_prev_stylesheet = self.styleSheet() or ""
            self.setStyleSheet(
                (self._reorder_prev_stylesheet + "\n" if self._reorder_prev_stylesheet else "")
                + "AccountColumn { border: 2px solid #1d9bf0; border-radius: 6px; background-color: rgba(29,155,240,0.06); }"
            )
        except Exception:
            self._reorder_prev_stylesheet = ""

    def _disarm_drag(self, emit_finished: bool = True) -> None:
        was_armed = self._drag_armed
        self._drag_armed = False
        self._drag_timer.stop()
        handle = getattr(self, "_col_drag_handle", None)
        if handle is not None:
            try:
                if handle.mouseGrabber() is handle:
                    handle.releaseMouse()
            except Exception:
                try:
                    handle.releaseMouse()
                except Exception:
                    pass
            handle.setCursor(Qt.CursorShape.SizeAllCursor)
        try:
            if getattr(self, "_reorder_opacity_effect", None) is not None:
                self._reorder_opacity_effect.setOpacity(1.0)
                self.setGraphicsEffect(None)
                self._reorder_opacity_effect = None
        except Exception:
            pass
        try:
            prev = getattr(self, "_reorder_prev_stylesheet", None)
            if prev is not None:
                self.setStyleSheet(prev)
                self._reorder_prev_stylesheet = None
        except Exception:
            pass
        if was_armed and emit_finished:
            try:
                self.reorder_drag_finished.emit()
            except Exception:
                pass

    def eventFilter(self, obj, event: QEvent) -> bool:
        return False

    def _position_resize_handles(self) -> None:
        if not self._resize_handle.isVisible():
            return
        self._resize_handle.setFixedWidth(self.RESIZE_HANDLE_WIDTH)
        self._resize_handle._position_bar()

    def set_boundary_enabled(self, enabled: bool) -> None:
        self._resize_handle.setVisible(enabled)
        if enabled:
            self._resize_handle.setFixedWidth(self.RESIZE_HANDLE_WIDTH)
            self._resize_handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self._position_resize_handles()

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        self._maybe_load_initial()
        self.enabled_changed.emit(self._enabled)

    def _maybe_load_initial(self) -> None:
        if not self._enabled or self._loaded_once:
            return
        if self._column_type == "profile":
            self._bootstrap_profile()
            return
        if self._column_type == "lists":
            self._bootstrap_lists()
            return
        if self._initial_url:
            self._webview.load_url(self._initial_url)

    def _on_lists_home_for_retry(self, ok: bool = True) -> None:
        if not getattr(self, "_lists_retry_after_home", False):
            return
        self._lists_retry_after_home = False
        try:
            wv = self.current_webview()
            if wv is not None:
                wv.loadFinished.disconnect(self._on_lists_home_for_retry)
        except Exception:
            pass
        if getattr(self, "_nav_target_lock", "") == "lists" and self._profile_state == "RESOLVED":
            return
        self._session_resolve_target = "lists"
        self._profile_resolve_attempted = False
        self._lists_cookie_retry_phase = True
        self._profile_resolve_retries = 0
        started = False
        try:
            started = bool(self._try_resolve_profile_from_cookies())
        except Exception:
            started = False
        QTimer.singleShot(800, lambda: self._try_resolve_profile_from_session(force=False))
        QTimer.singleShot(2000, lambda: self._try_resolve_profile_from_session(force=False))
        if not started:
            QTimer.singleShot(3500, self._lists_session_resolve_timeout)

    def _lists_cookie_retry_timeout(self) -> None:
        if self._profile_state == "RESOLVED":
            return
        if getattr(self, "_profile_waiting_self_redirect", False):
            return
        if self._profile_state == "RESOLVING":
            return

    def _lists_session_resolve_timeout(self) -> None:
        if self._profile_state == "RESOLVED":
            return
        if getattr(self, "_profile_waiting_self_redirect", False):
            return
        if self._profile_state != "FAILED":
            self._lists_show_failed_hub()

    def _lists_show_failed_hub(self) -> None:
        self._profile_resolve_attempted = True
        self._profile_state = "FAILED"
        self._profile_waiting_self_redirect = False
        try:
            self._url_bar.setText("現在のリストを確認できませんでした")
            self._url_bar.setToolTip(
                "ログイン中のXアカウントから本人のリストURLを解決できませんでした"
            )
        except Exception:
            pass

    def _bootstrap_lists(self) -> None:
        if getattr(self, "_lists_bootstrap_started", False):
            return
        if getattr(self, "_profile_resolve_attempted", False) and self._profile_state in ("RESOLVED", "FAILED"):
            return
        self._lists_bootstrap_started = True
        self._lists_home_attempted = False
        existing = (self._initial_url or "").strip()
        if existing.startswith("http") and "/lists" in existing and "/i/lists" not in existing:
            try:
                self._url_bar.setText(existing)
                self._url_bar.setToolTip(existing)
            except Exception:
                pass
            self._webview.load_url(existing)
            self._profile_resolve_attempted = True
            self._profile_state = "RESOLVED"
            self._nav_target_lock = "lists"
            self._lists_resolved_url = existing
            return

        self._profile_state = "RESOLVING"
        rid = self._begin_resolve_request("lists")
        self._lists_resolve_request_id = rid
        try:
            self._url_bar.setText("リストを取得中…")
            self._url_bar.setToolTip("ログイン中のXアカウントからリストを取得しています")
        except Exception:
            pass

        if self._try_resolve_profile_from_cookies():
            return

        if not getattr(self, "_lists_home_attempted", False):
            self._lists_home_attempted = True
            self._lists_retry_after_home = True
            self._profile_resolve_attempted = True
            try:
                wv = self.current_webview()
                if wv is not None:
                    wv.loadFinished.connect(self._on_lists_home_for_retry)
            except Exception:
                pass
            self._webview.load_url("https://x.com/home")
            QTimer.singleShot(2500, self._lists_cookie_retry_timeout)
            return
        self._lists_show_failed_hub()

    def _bootstrap_profile(self) -> None:
        if getattr(self, "_profile_resolve_attempted", False):
            return
        existing = (self._initial_url or "").strip()
        if existing.startswith("http") and not self._is_session_bootstrap_url(existing):
            try:
                self._url_bar.setText(existing)
                self._url_bar.setToolTip(existing)
            except Exception:
                pass
            self._webview.load_url(existing)
            self._profile_resolve_attempted = True
            self._profile_state = "RESOLVED"
            return

        self._profile_state = "RESOLVING"
        rid = self._begin_resolve_request("profile")
        self._profile_resolve_request_id = rid
        try:
            self._url_bar.setText("プロフィールを取得中…")
            self._url_bar.setToolTip("ログイン中のXアカウントからプロフィールを取得しています")
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[PROFILE] bootstrap column={getattr(self, '_column_id', '')} "
                    f"current={self._current_web_url!r}",
                    flush=True,
                )
        except Exception:
            pass

        if self._try_resolve_profile_from_cookies():
            return

        current = (self._current_web_url or "").strip()
        if current and ("x.com" in current or "twitter.com" in current) and "/login" not in current.lower():
            self._schedule_profile_resolve()
            return
        self._webview.load_url("https://x.com/home")
        self._schedule_profile_resolve()

    def _try_resolve_profile_from_cookies(self) -> bool:
        wv = self.current_webview()
        if wv is None:
            return False
        try:
            profile = wv.page().profile() if hasattr(wv, "page") else None
        except Exception:
            profile = None
        if profile is None:
            return False
        try:
            store = profile.cookieStore()
        except Exception:
            return False

        self._profile_cookie_uids: list[str] = []
        self._profile_cookie_done = False

        def _on_cookie(cookie) -> None:
            try:
                name = bytes(cookie.name()).decode("utf-8", "ignore")
                if name != "twid":
                    return
                val = bytes(cookie.value()).decode("utf-8", "ignore")
                from urllib.parse import unquote
                raw = unquote(val)
                uid = ""
                if raw.startswith("u=") and raw[2:].isdigit():
                    uid = raw[2:]
                else:
                    import re as _re
                    m = _re.search(r"(\d{5,})", raw)
                    if m:
                        uid = m.group(1)
                if uid and uid not in self._profile_cookie_uids:
                    self._profile_cookie_uids.append(uid)
                    try:
                        import os
                        if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                            print(f"[PROFILE] twid uid={uid}", flush=True)
                    except Exception:
                        pass
            except Exception:
                pass

        def _on_cookies_finished(final: bool = False) -> None:
            if self._profile_cookie_done:
                return
            uids = list(getattr(self, "_profile_cookie_uids", []) or [])
            if not uids and not final:
                return
            self._profile_cookie_done = True
            try:
                store.cookieAdded.disconnect(_on_cookie)
            except Exception:
                pass
            if not uids:
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print("[PROFILE] no twid cookie — fall back", flush=True)
                except Exception:
                    pass
                target = getattr(self, "_session_resolve_target", "profile")
                if target == "lists":
                    if getattr(self, "_lists_home_attempted", False):
                        self._lists_show_failed_hub()
                        return
                    self._lists_home_attempted = True
                    self._lists_retry_after_home = True
                    self._profile_resolve_attempted = True
                    try:
                        wv.loadFinished.connect(self._on_lists_home_for_retry)
                    except Exception:
                        pass
                    self._webview.load_url("https://x.com/home")
                    QTimer.singleShot(2500, self._lists_cookie_retry_timeout)
                    return
                self._profile_resolve_attempted = False
                current = (self._current_web_url or "").strip()
                if current and ("x.com" in current or "twitter.com" in current):
                    self._schedule_profile_resolve()
                else:
                    self._webview.load_url("https://x.com/home")
                    self._schedule_profile_resolve()
                return
            uid = uids[0]
            if getattr(self, "_nav_target_lock", "") == "lists" or (
                self._profile_state == "RESOLVED" and self._column_type == "lists"
            ):
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print("[LISTS] skip /i/user — already lists-locked", flush=True)
                except Exception:
                    pass
                return
            self_url = f"https://x.com/i/user/{uid}"
            self._profile_resolve_attempted = True
            self._profile_waiting_self_redirect = True
            self._cookie_resolve_request_id = int(
                getattr(self, "_resolve_request_id", 0) or 0
            )
            try:
                try:
                    wv.url_changed.disconnect(self._on_profile_self_redirect)
                except Exception:
                    pass
                wv.url_changed.connect(self._on_profile_self_redirect)
            except Exception:
                pass
            try:
                target = getattr(self, "_session_resolve_target", "profile")
                self._url_bar.setText(
                    "リストを取得中…" if target == "lists" else "プロフィールを取得中…"
                )
            except Exception:
                pass
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[PROFILE] load self_url={self_url}", flush=True)
            except Exception:
                pass
            wv.load_url(self_url)

        try:
            store.cookieAdded.connect(_on_cookie)
            store.loadAllCookies()
            QTimer.singleShot(500, lambda: _on_cookies_finished(False))
            QTimer.singleShot(1600, lambda: _on_cookies_finished(True))
            return True
        except Exception:
            return False

    def _on_profile_self_redirect(self, url: str) -> None:
        if not getattr(self, "_profile_waiting_self_redirect", False):
            return
        rid = int(getattr(self, "_cookie_resolve_request_id", 0) or 0)
        target = getattr(self, "_session_resolve_target", None) or self._column_type
        if not self._resolve_request_alive(rid, target):
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(
                        f"[RESOLVE] ignore stale redirect id={rid} "
                        f"current={self._resolve_request_id} target={target} url={url!r}",
                        flush=True,
                    )
            except Exception:
                pass
            return
        if getattr(self, "_nav_target_lock", "") == "lists":
            return
        if self._profile_state == "RESOLVED" and self._column_type == "lists":
            return
        u = (url or "").strip()
        if not u.startswith("http"):
            return
        if self._is_session_bootstrap_url(u):
            return
        if "/i/user/" in u:
            return
        self._profile_waiting_self_redirect = False
        try:
            wv = self.current_webview()
            if wv is not None and hasattr(wv, "url_changed"):
                wv.url_changed.disconnect(self._on_profile_self_redirect)
        except Exception:
            pass

        final = u
        if target == "lists" or self._column_type == "lists":
            if self._is_user_lists_url(u):
                self._apply_resolved_lists_url(u, request_id=rid)
                return
            if not self._is_canonical_profile_url(u):
                try:
                    import os
                    if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                        print(f"[LISTS] reject non-profile redirect url={u!r}", flush=True)
                except Exception:
                    pass
                self._lists_show_failed_hub()
                return
            self._apply_resolved_lists_url(u.rstrip("/") + "/lists", request_id=rid)
            return

        if self._column_type != "profile":
            return
        self._profile_state = "RESOLVED"
        self._nav_target_lock = "profile"
        self._initial_url = final
        self._current_web_url = final
        try:
            self._url_bar.setText(final)
            self._url_bar.setToolTip(final)
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(f"[PROFILE] resolved via cookie/redirect url={final} target={target}", flush=True)
        except Exception:
            pass
        self._schedule_history_clear_when_on(final, rid)

    def _clear_profile_bootstrap_history(self) -> None:
        try:
            wv = self.current_webview()
            if wv is None:
                return
            page = wv.page() if hasattr(wv, "page") else None
            if page is None:
                return
            hist = page.history() if hasattr(page, "history") else None
            if hist is None:
                return
            hist.clear()
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print("[PROFILE] history cleared after resolve", flush=True)
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _normalize_nav_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        try:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(u)
            path = (parts.path or "").rstrip("/") or ""
            return urlunsplit((parts.scheme.lower(), (parts.netloc or "").lower(), path, "", "")).rstrip("/")
        except Exception:
            return u.rstrip("/").split("?")[0].split("#")[0].lower()

    def _begin_resolve_request(self, target: str) -> int:
        self._resolve_request_id = int(getattr(self, "_resolve_request_id", 0) or 0) + 1
        self._session_resolve_target = target
        self._nav_target_lock = ""
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[RESOLVE] begin id={self._resolve_request_id} "
                    f"column={getattr(self, '_column_id', '')} target={target}",
                    flush=True,
                )
        except Exception:
            pass
        return self._resolve_request_id

    def _resolve_request_alive(self, request_id: int, target: str | None = None) -> bool:
        if int(request_id) != int(getattr(self, "_resolve_request_id", 0) or 0):
            return False
        if self._profile_state == "RESOLVED":
            lock = getattr(self, "_nav_target_lock", "") or ""
            if target and lock and target != lock:
                return False
            if lock == "lists" and target == "profile":
                return False
        if target is not None:
            cur = getattr(self, "_session_resolve_target", "") or self._column_type
            if cur and target != cur and target != self._column_type:
                return False
        return True

    def _schedule_history_clear_when_on(self, expected_url: str, request_id: int) -> None:
        expected = self._normalize_nav_url(expected_url)

        def _try_clear(attempt: int = 0) -> None:
            if not self._resolve_request_alive(request_id):
                return
            cur = (self._current_web_url or "").strip()
            try:
                wv = self.current_webview()
                if wv is not None and hasattr(wv, "url") and callable(wv.url):
                    cur = wv.url().toString() or cur
            except Exception:
                pass
            if self._normalize_nav_url(cur) == expected:
                self._clear_profile_bootstrap_history()
                return
            if attempt < 8:
                QTimer.singleShot(250, lambda: _try_clear(attempt + 1))

        QTimer.singleShot(300, lambda: _try_clear(0))

    def _apply_resolved_lists_url(self, final: str, request_id: int | None = None) -> None:
        final = (final or "").strip()
        if not final.startswith("http") or "/i/lists" in final:
            self._lists_show_failed_hub()
            return
        if request_id is not None and not self._resolve_request_alive(int(request_id), "lists"):
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[LISTS] skip stale apply id={request_id} url={final}", flush=True)
            except Exception:
                pass
            return
        if self._is_canonical_profile_url(final) and not self._is_user_lists_url(final):
            final = final.rstrip("/") + "/lists"
        if not self._is_user_lists_url(final):
            self._lists_show_failed_hub()
            return
        norm_final = self._normalize_nav_url(final)
        if self._profile_state == "RESOLVED" and getattr(self, "_nav_target_lock", "") == "lists":
            if self._normalize_nav_url(getattr(self, "_lists_resolved_url", "") or self._initial_url or "") == norm_final:
                return
            if self._is_user_lists_url(getattr(self, "_lists_resolved_url", "") or ""):
                return

        already_there = False
        try:
            candidates = []
            cur = (self._current_web_url or "").strip()
            if cur:
                candidates.append(cur)
            wv0 = self.current_webview()
            if wv0 is not None:
                try:
                    if hasattr(wv0, "url") and callable(wv0.url):
                        candidates.append(wv0.url().toString() or "")
                except Exception:
                    pass
                try:
                    if hasattr(wv0, "get_current_url"):
                        candidates.append(wv0.get_current_url() or "")
                except Exception:
                    pass
            for c in candidates:
                if c and self._normalize_nav_url(c) == norm_final:
                    already_there = True
                    break
        except Exception:
            already_there = False

        self._profile_state = "RESOLVED"
        self._nav_target_lock = "lists"
        self._session_resolve_target = "lists"
        self._profile_resolve_attempted = True
        self._profile_waiting_self_redirect = False
        self._lists_bootstrap_started = True
        self._lists_resolved_url = final
        self._initial_url = final
        self._current_web_url = final
        self._cookie_resolve_request_id = -1
        try:
            wv = self.current_webview()
            if wv is not None and hasattr(wv, "url_changed"):
                try:
                    wv.url_changed.disconnect(self._on_profile_self_redirect)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._url_bar.setText(final)
            self._url_bar.setToolTip(final)
        except Exception:
            pass
        try:
            import os
            if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                print(
                    f"[LISTS] resolved url={final} already_there={already_there} "
                    f"lock=lists id={getattr(self, '_resolve_request_id', 0)}",
                    flush=True,
                )
        except Exception:
            pass
        if already_there:
            QTimer.singleShot(200, self._clear_profile_bootstrap_history)
            return
        try:
            wv = self.current_webview()
            if wv is not None:
                wv.load_url(final)
        except Exception:
            pass
        QTimer.singleShot(400, self._clear_profile_bootstrap_history)

    @staticmethod
    def _is_user_lists_url(url: str) -> bool:
        u = (url or "").strip()
        if not u.startswith("http") or "/i/lists" in u:
            return False
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(u)
        except Exception:
            return False
        host = (parts.hostname or "").lower()
        if host not in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            return False
        segs = [s for s in (parts.path or "").strip("/").split("/") if s]
        if len(segs) != 2 or segs[1].lower() != "lists":
            return False
        handle = segs[0].lower()
        reserved = {
            "home", "explore", "search", "notifications", "messages", "i",
            "settings", "compose", "login", "logout", "signup", "intent",
            "hashtag", "share", "tos", "privacy",
        }
        return handle not in reserved

    @staticmethod
    def _is_session_bootstrap_url(url: str) -> bool:
        u = (url or "").strip().rstrip("/").lower()
        if not u:
            return True
        if u in ("https://x.com", "https://twitter.com", "http://x.com", "http://twitter.com"):
            return True
        if u.endswith("/home") or "/home?" in (url or "").lower():
            return True
        if "/settings/" in u or "/i/flow/" in u or "/login" in u or "/i/user/" in u:
            return True
        if u.endswith("/i/lists") or "/i/lists?" in u or u.endswith("/i/lists/"):
            return True
        if "/status/" in u:
            return True
        return False

    @staticmethod
    def _is_canonical_profile_url(url: str) -> bool:
        u = (url or "").strip()
        if not u.startswith("http"):
            return False
        if AccountColumn._is_session_bootstrap_url(u):
            return False
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(u)
        except Exception:
            return False
        host = (parts.hostname or "").lower()
        if host not in ("x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            return False
        path = (parts.path or "").strip("/")
        if not path:
            return False
        segs = [s for s in path.split("/") if s]
        if len(segs) != 1:
            return False
        handle = segs[0].lower()
        reserved = {
            "home", "explore", "search", "notifications", "messages", "i",
            "settings", "compose", "login", "logout", "signup", "intent",
            "hashtag", "share", "tos", "privacy",
        }
        if handle in reserved:
            return False
        return True

    def _schedule_profile_resolve(self) -> None:
        if getattr(self, "_profile_resolve_attempted", False) and self._profile_resolve_retries > 0:
            return
        self._profile_resolve_attempted = True
        wv = self.current_webview()
        if wv is not None and hasattr(wv, "loadFinished"):
            try:
                wv.loadFinished.connect(self._on_profile_bootstrap_load_finished)
            except Exception:
                pass
        QTimer.singleShot(1200, lambda: self._try_resolve_profile_from_session(force=False))

    def _on_profile_bootstrap_load_finished(self, ok: bool) -> None:
        wv = self.current_webview()
        if wv is not None and hasattr(wv, "loadFinished"):
            try:
                wv.loadFinished.disconnect(self._on_profile_bootstrap_load_finished)
            except Exception:
                pass
        if self._column_type != "profile":
            return
        QTimer.singleShot(600, lambda: self._try_resolve_profile_from_session(force=False))

    def _try_resolve_profile_from_session(self, force: bool = False) -> None:
        if self._column_type not in ("profile", "lists"):
            return
        if self._profile_state == "RESOLVED":
            return
        if self._column_type == "lists" and getattr(self, "_lists_resolved_url", ""):
            return
        cur = (self._current_web_url or self._initial_url or "").strip()
        if cur.startswith("http") and not self._is_session_bootstrap_url(cur):
            if self._column_type == "lists":
                if self._is_canonical_profile_url(cur):
                    final = cur.rstrip("/") + "/lists"
                    self._apply_resolved_lists_url(final)
                    return
                if "/lists" in cur and "/i/lists" not in cur and self._is_user_lists_url(cur):
                    self._apply_resolved_lists_url(cur)
                    return
            else:
                try:
                    self._url_bar.setText(cur)
                    self._url_bar.setToolTip(cur)
                except Exception:
                    pass
                self._profile_state = "RESOLVED"
                return
        wv = self.current_webview()
        if wv is None:
            self._set_profile_failed("FAILED")
            return
        try:
            eng = wv.page() if hasattr(wv, "page") else None
        except Exception:
            eng = None
        if eng is None:
            self._set_profile_failed("FAILED")
            return
        js = r"""
        (function() {
          function clean(h) {
            if (!h) return '';
            try { h = String(h); } catch (e) { return ''; }
            h = h.split('?')[0].split('#')[0];
            return h;
          }
          function absHref(node) {
            if (!node) return '';
            try {
              // Prefer DOM property (resolved absolute URL) over attribute.
              var h = node.href || '';
              if (!h) h = node.getAttribute('href') || '';
              return clean(h);
            } catch (e) { return ''; }
          }
          function isReserved(pathUser) {
            var u = (pathUser || '').toLowerCase();
            var reserved = {
              home:1, explore:1, notifications:1, messages:1, i:1, settings:1,
              compose:1, search:1, login:1, logout:1, jobs:1, premium:1, tos:1,
              privacy:1, signup:1, intent:1, share:1, hashtag:1, following:1,
              followers:1, lists:1, bookmarks:1, communities:1, about:1,
              download:1, more:1, display:1, connect:1
            };
            return !!reserved[u];
          }
          function profileUrlFromHref(h) {
            h = clean(h);
            if (!h) return '';
            // Absolute
            var m = h.match(/^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/@?([A-Za-z0-9_]{1,40})\/?$/i);
            if (m && !isReserved(m[1])) return 'https://x.com/' + m[1];
            // Site-relative
            m = h.match(/^\/@?([A-Za-z0-9_]{1,40})\/?$/i);
            if (m && !isReserved(m[1])) return 'https://x.com/' + m[1];
            return '';
          }
          function pack(status, url) {
            return JSON.stringify({status: status, url: url || ''});
          }
          try {
            var path = (location.pathname || '').toLowerCase();
            if (path.indexOf('/login') >= 0 || path.indexOf('/i/flow/login') >= 0) {
              return pack('not_logged_in');
            }

            var probes = [
              'a[data-testid="AppTabBar_Profile_Link"]',
              '[data-testid="AppTabBar_Profile_Link"]',
              '[data-testid="AppTabBar_Profile_Link"] a',
              'a[data-testid="AppTabBar_Profile_Link"][href]',
              'a[aria-label="Profile"]',
              'a[aria-label="プロフィール"]',
              'a[aria-label*="Profile"][href]',
              'a[aria-label*="プロフィール"][href]'
            ];
            for (var i = 0; i < probes.length; i++) {
              var n = document.querySelector(probes[i]);
              if (!n) continue;
              // element itself may be the anchor or a wrapper
              var candidates = [n];
              if (n.tagName !== 'A') {
                var inner = n.querySelector('a[href]');
                if (inner) candidates.push(inner);
                if (n.closest) {
                  var outer = n.closest('a[href]');
                  if (outer) candidates.push(outer);
                }
              }
              for (var c = 0; c < candidates.length; c++) {
                var pu = profileUrlFromHref(absHref(candidates[c]));
                if (pu) return pack('ok', pu);
              }
            }

            // Explicit user Lists links: /{handle}/lists (never /i/lists)
            function listsUrlFromHref(h) {
              h = clean(h);
              if (!h) return '';
              var m = h.match(/^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/@?([A-Za-z0-9_]{1,40})\/lists\/?$/i);
              if (m && !isReserved(m[1])) return 'https://x.com/' + m[1] + '/lists';
              m = h.match(/^\/@?([A-Za-z0-9_]{1,40})\/lists\/?$/i);
              if (m && !isReserved(m[1])) return 'https://x.com/' + m[1] + '/lists';
              return '';
            }
            var allAnchors = document.querySelectorAll('a[href]');
            for (var li = 0; li < allAnchors.length; li++) {
              var lu = listsUrlFromHref(absHref(allAnchors[li]));
              if (lu) return pack('ok', lu);
            }

            // Account switcher button: only accept a real nested profile anchor href
            var switcher = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
            if (switcher) {
              var a = switcher.querySelector('a[href]');
              var pu2 = profileUrlFromHref(absHref(a));
              if (pu2) return pack('ok', pu2);
            }

            // Nav / header / bottom bar anchors with real href
            var roots = document.querySelectorAll(
              'nav a[href], header a[href], [role="navigation"] a[href], [data-testid="Sidebar"] a[href], [data-testid="BottomBar"] a[href], [data-testid="primaryColumn"] a[href]'
            );
            for (var j = 0; j < roots.length; j++) {
              var pu3 = profileUrlFromHref(absHref(roots[j]));
              if (pu3) return pack('ok', pu3);
            }

            // Logged-out login CTA without app chrome
            if (document.querySelector('a[href*="/login"]') || document.querySelector('[data-testid="login"]')) {
              var hasApp = document.querySelector(
                'a[data-testid="AppTabBar_Home_Link"], a[data-testid="AppTabBar_Profile_Link"], [data-testid="AppTabBar_Home_Link"]'
              );
              if (!hasApp) return pack('not_logged_in');
            }
          } catch (e) {
            return pack('failed');
          }
          return pack('failed');
        })();
        """

        def _done(result):
            status = "failed"
            url = ""
            raw = result
            if isinstance(result, dict):
                status = str(result.get("status") or "failed")
                url = str(result.get("url") or "").strip()
            elif isinstance(result, str):
                s = result.strip()
                if s.startswith("{"):
                    try:
                        import json
                        obj = json.loads(s)
                        status = str(obj.get("status") or "failed")
                        url = str(obj.get("url") or "").strip()
                    except Exception:
                        if s.startswith("http"):
                            status, url = "ok", s
                elif s.startswith("http"):
                    status, url = "ok", s
            try:
                import os
                if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                    print(f"[PROFILE] js_raw={raw!r} status={status} url={url!r}", flush=True)
            except Exception:
                pass

            if status == "ok" and url.startswith("http") and not self._is_session_bootstrap_url(url):
                if self._column_type == "lists":
                    if getattr(self, "_nav_target_lock", "") == "lists" and self._profile_state == "RESOLVED":
                        return
                    if not self._resolve_request_alive(js_request_id, "lists"):
                        return
                    if self._is_user_lists_url(url):
                        final = url
                    elif self._is_canonical_profile_url(url):
                        final = url.rstrip("/") + "/lists"
                    else:
                        final = ""
                    if final:
                        self._apply_resolved_lists_url(final, request_id=js_request_id)
                        return
                else:
                    if not self._resolve_request_alive(js_request_id, "profile"):
                        return
                    if getattr(self, "_nav_target_lock", "") == "lists":
                        return
                    self._profile_state = "RESOLVED"
                    self._nav_target_lock = "profile"
                    self._initial_url = url
                    try:
                        self._url_bar.setText(url)
                        self._url_bar.setToolTip(url)
                    except Exception:
                        pass
                    self._current_web_url = url
                    try:
                        wv.load_url(url)
                    except Exception:
                        pass
                    QTimer.singleShot(400, self._clear_profile_bootstrap_history)
                    return

            if status == "not_logged_in":
                if self._column_type == "lists":
                    self._lists_show_failed_hub()
                    try:
                        self._url_bar.setText("Xにログインしてください")
                    except Exception:
                        pass
                else:
                    self._set_profile_failed("NOT_LOGGED_IN")
                return

            self._profile_resolve_retries = getattr(self, "_profile_resolve_retries", 0) + 1
            max_retries = 8 if self._column_type == "lists" else 12
            if self._profile_resolve_retries < max_retries:
                QTimer.singleShot(600, lambda: self._try_resolve_profile_from_session(force=False))
            else:
                if self._column_type == "lists":
                    self._lists_show_failed_hub()
                else:
                    self._set_profile_failed("FAILED")

        js_request_id = int(getattr(self, "_resolve_request_id", 0) or 0)
        try:
            eng.runJavaScript(js, _done)
        except Exception:
            self._set_profile_failed("FAILED")

    def _set_profile_failed(self, state: str = "FAILED") -> None:
        self._profile_state = state
        if state == "NOT_LOGGED_IN":
            msg = "Xにログインしてください"
        else:
            msg = "現在のXアカウントを確認できませんでした"
        try:
            self._url_bar.setText(msg)
            self._url_bar.setToolTip(msg)
        except Exception:
            pass
        cur = (self._current_web_url or "").lower()
        if "/settings/" in cur:
            try:
                self.current_webview().load_url("https://x.com/home")
            except Exception:
                pass

    def _on_close(self) -> None:
        self.closed.emit()

    def _on_back(self) -> None:
        self.current_webview().go_back()
        QTimer.singleShot(0, self._update_nav_history_buttons)

    def _on_forward(self) -> None:
        self.current_webview().go_forward()
        QTimer.singleShot(0, self._update_nav_history_buttons)

    def _on_reload(self) -> None:
        self.reload_page()

    def reload_page(self) -> None:
        if self._enabled:
            self.current_webview().reload_page()

    def go_home(self) -> bool:
        if not self._enabled:
            return False
        url = self._initial_url or "https://x.com/"
        self.current_webview().load_url(url)
        return True

    def _on_url_changed(self, url: str) -> None:
        try:
            self._update_nav_history_buttons()
        except Exception:
            pass
        if not url:
            return
        self._loaded_once = True
        if (
            self._column_type == "lists"
            and getattr(self, "_nav_target_lock", "") == "lists"
            and self._profile_state == "RESOLVED"
        ):
            lists_url = (getattr(self, "_lists_resolved_url", "") or self._initial_url or "").strip()
            if lists_url and self._is_user_lists_url(lists_url):
                if self._is_canonical_profile_url(url) or (
                    self._is_session_bootstrap_url(url) and "/lists" not in (url or "")
                ):
                    try:
                        import os
                        if os.environ.get("MAYOTTER_PROFILE_DEBUG"):
                            print(
                                f"[LISTS] bounce late nav {url!r} → {lists_url!r}",
                                flush=True,
                            )
                    except Exception:
                        pass
                    if self._normalize_nav_url(url) != self._normalize_nav_url(lists_url):
                        self._current_web_url = lists_url
                        self._url_bar.setText(lists_url)
                        try:
                            wv = self.current_webview()
                            if wv is not None:
                                wv.load_url(lists_url)
                        except Exception:
                            pass
                    return
        self._current_web_url = url
        self._url_bar.setText(url)

    def _on_webview_url_changed(self, webview, url: str) -> None:
        if webview is self._tabs[self._current_tab]:
            self._on_url_changed(url)
        else:
            if url:
                self._loaded_once = True

    def get_account_id(self) -> str:
        return self._account_id

    def get_column_id(self) -> str:
        return self._column_id

    def get_column_type(self) -> str:
        return self._column_type

    def get_title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        self._title = title

    def get_display_name(self) -> str:
        return self._display_name

    def get_initial_url(self) -> str:
        return self._initial_url

    def set_display_name(self, name: str) -> None:
        self._display_name = (name or "").strip()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self._enabled:
            self._enabled = enabled
            if enabled:
                self._maybe_load_initial()
            self.enabled_changed.emit(enabled)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mousePressEvent(event)

    def set_width(self, width: int, emit_signal: bool = True) -> None:
        self._current_width = max(self.MIN_WIDTH, int(width))
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self._current_width)
        self.resize(self._current_width, self.height() if self.height() > 0 else 100)
        self.updateGeometry()
        if emit_signal:
            self.resized.emit(self._current_width)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        h = self.minimumHeight() if self.minimumHeight() > 0 else 400
        return QSize(self._current_width, h)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.MIN_WIDTH, 100)

    def get_width(self) -> int:
        return self._current_width

    def showEvent(self, event: QEvent) -> None:
        self._position_resize_handles()
        self._enforce_single_visible_tab()
        super().showEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._position_resize_handles()
        super().resizeEvent(event)
