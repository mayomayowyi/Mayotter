from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from src.core.i18n import tr
from src.ui.app_event_filter import install_app_event_filter, remove_app_event_filter
from src.ui import theme


def _translucent(color: str, alpha: float) -> str:
    c = QColor(color)
    return f'rgba({c.red()},{c.green()},{c.blue()},{round(alpha * 255)})'


class FlipGestureBar(QLabel):
    """Webページの選択・スクロールと競合しないジェスチャー開始領域。"""

    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.origin = None
        self.wheel_distance = QPoint()
        self.wheel_used = False
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self.setMouseTracking(True)
        self.reset_wheel = QTimer(self)
        self.reset_wheel.setSingleShot(True)
        self.reset_wheel.setInterval(220)
        self.reset_wheel.timeout.connect(self._reset_wheel)
        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        self.setText(tr('左右にスワイプしてカラムを切り替え'))
        self.setAccessibleName(self.text())
        self.setToolTip(tr('ここで左右スワイプ・水平スクロール・左右キーを使用できます'))
        self.setStyleSheet(f'color:{theme.TEXT_SECONDARY};background:{theme.SURFACE};'
                           f'border-bottom:1px solid {theme.BORDER};font-size:11px;')

    def _finish_drag(self, point):
        if self.origin is None:
            return
        delta = point - self.origin
        self.origin = None
        threshold = max(48, min(100, self.width() // 8))
        if abs(delta.x()) >= threshold and abs(delta.x()) > abs(delta.y()) * 1.7:
            self.controller.step(1 if delta.x() < 0 else -1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._finish_drag(event.position().toPoint())
            event.accept()

    def event(self, event):
        kind = event.type()
        if kind == QEvent.Type.TouchBegin:
            points = event.points()
            self.origin = points[0].position().toPoint() if len(points) == 1 else None
            event.accept()
            return True
        if kind == QEvent.Type.TouchUpdate:
            if len(event.points()) != 1:
                self.origin = None
            event.accept()
            return True
        if kind == QEvent.Type.TouchEnd:
            if event.points():
                self._finish_drag(event.points()[0].position().toPoint())
            event.accept()
            return True
        if kind in (QEvent.Type.TouchCancel, QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
            self.origin = None
            self._reset_wheel()
        return super().event(event)

    def _reset_wheel(self):
        self.wheel_distance = QPoint()
        self.wheel_used = False

    def wheelEvent(self, event):
        if event.phase() == Qt.ScrollPhase.ScrollBegin:
            self._reset_wheel()
        delta = event.pixelDelta()
        pixel = not delta.isNull()
        if not pixel:
            delta = event.angleDelta()
        if abs(delta.y()) >= abs(delta.x()):
            self._reset_wheel()
            event.ignore()
            return
        self.wheel_distance += delta
        if not self.wheel_used and abs(self.wheel_distance.x()) >= (64 if pixel else 120):
            self.controller.step(1 if self.wheel_distance.x() < 0 else -1)
            self.wheel_used = True
        if event.phase() == Qt.ScrollPhase.ScrollEnd:
            self._reset_wheel()
        else:
            self.reset_wheel.start()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.controller.step(1 if event.key() == Qt.Key.Key_Right else -1)
            event.accept()
        else:
            super().keyPressEvent(event)


class FlipBubbleButton(QPushButton):
    def __init__(self, title, parent):
        self.full_title = title
        super().__init__(parent)
        self.setText(title)
        self.setToolTip(title)
        self.setAccessibleName(title)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(self.full_title, Qt.TextElideMode.ElideRight, max(1, self.width() - 28))
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)


class FlipBubbles(QScrollArea):
    def __init__(self, controller, side):
        super().__init__(controller.viewport)
        self.controller = controller
        self.side = side
        self.columns = ()
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body = QWidget()
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(8, 8, 8, 8)
        self.rows.setSpacing(6)
        self.setWidget(body)
        self.fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self._finished)
        self.target = QRect()
        self.wanted = False
        self.hide()

    def populate(self, columns):
        signature = tuple((c, c.get_display_name() or c.get_title()) for c in columns)
        if signature == self.columns:
            return
        self.columns = signature
        while self.rows.count():
            old = self.rows.takeAt(0).widget()
            old.hide()
            old.deleteLater()
        for col, title in signature:
            button = FlipBubbleButton(title, self.widget())
            button.setMinimumHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            shadow = QGraphicsDropShadowEffect(button)
            shadow.setBlurRadius(14)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(0, 0, 0, 70))
            button.setGraphicsEffect(shadow)
            button.clicked.connect(lambda checked=False, col=col: self.controller.select(col))
            self.rows.addWidget(button)
        self.setStyleSheet(
            f'QScrollArea{{background:transparent;border:0;}}'
            f'QScrollArea>QWidget>QWidget{{background:transparent;}}'
            # 背景を少し透かした角丸の吹き出し。hover で不透明に近づけ、アクセント色の縁で選べることを示す
            f'QPushButton{{color:{theme.TEXT};background:{_translucent(theme.SURFACE, 0.84)};'
            f'border:1px solid {_translucent(theme.BORDER, 0.9)};border-radius:16px;padding:6px 12px;text-align:left;}}'
            f'QPushButton:hover{{background:{_translucent(theme.SURFACE_HOVER, 0.96)};border-color:{theme.BORDER_ACCENT};}}'
            f'QPushButton:pressed{{background:{theme.ACCENT};}}'
        )

    def reveal(self, show):
        show = bool(show and self.columns)
        if show == self.wanted:
            return
        self.wanted = show
        self.animation.stop()
        self.animation.setStartValue(self.fade.opacity() if self.isVisible() else 0.)
        self.animation.setEndValue(.96 if show else 0.)
        if show:
            width = max(100, min(250, int(self.controller.viewport.width() * .36)))
            height = min(max(50, len(self.columns) * 40 + 16), max(50, self.controller.viewport.height() - 100))
            x = 28 if self.side == 'left' else self.controller.viewport.width() - 28 - width
            self.target = QRect(x, max(38, (self.controller.viewport.height() - height) // 2), width, height)
            self.show()
            self.raise_()
        self.animation.start()

    def _frame(self, value):
        t = float(value)
        self.fade.setOpacity(t)
        rect = QRect(self.target)
        shrink = round((1 - t) * self.target.width() * .04)
        rect.adjust(shrink, shrink, -shrink, -shrink)
        rect.translate(round((1 - t) * (-12 if self.side == 'left' else 12)), 0)
        self.setGeometry(rect)

    def _finished(self):
        if not self.wanted:
            self.hide()


class FlipMode(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.viewport = window._scroll.viewport()
        self.enabled = False
        self.selected = None
        self.scope = None
        self.index = 0
        self.pending = None
        self.laying_out = False
        self.bar = FlipGestureBar(self, window._edge_dock_root)
        window._edge_dock_root.layout().insertWidget(1, self.bar)
        self.bubbles = {s: FlipBubbles(self, s) for s in ('left', 'right')}
        self.outgoing = None
        self.direction = 1
        self.transition_columns = ()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(210)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.setStartValue(0.)
        self.animation.setEndValue(1.)
        self.animation.valueChanged.connect(self._slide_frame)
        self.animation.finished.connect(self._slide_finished)
        self.hover_side = None
        self.hover = QTimer(self)
        self.hover.setSingleShot(True)
        self.hover.setInterval(200)
        self.hover.timeout.connect(self._reveal_hover)
        self.leave = QTimer(self)
        self.leave.setSingleShot(True)
        self.leave.setInterval(400)
        self.leave.timeout.connect(self.hide_bubbles)

    def columns(self):
        return list(self.window._columns)

    def refresh_theme(self):
        self.bar.refresh_theme()
        for panel in self.bubbles.values():
            panel.columns = ()
        if self.enabled:
            self.layout()

    def _scope(self):
        return self.window._workspace_id, bool(self.window._grok_mode)

    def set_enabled(self, enabled):
        if self.enabled == enabled:
            return
        self.cancel()
        self.enabled = enabled
        self.bar.setVisible(enabled)
        self.scope = None
        if enabled:
            scroll = self.window._scroll
            self.scroll_policy = scroll.horizontalScrollBarPolicy()
            self.scroll_resizable = scroll.widgetResizable()
            self.scroll_position = scroll.horizontalScrollBar().value()
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidgetResizable(False)
            install_app_event_filter(QApplication.instance(), self)
            self.layout()
        else:
            remove_app_event_filter(QApplication.instance(), self)
            self.restore_columns()
            self.selected = None
            scroll = self.window._scroll
            scroll.setWidgetResizable(self.scroll_resizable)
            scroll.setHorizontalScrollBarPolicy(self.scroll_policy)
            self.window._bind_active_columns()
            scroll.horizontalScrollBar().setValue(self.scroll_position)

    def restore_columns(self):
        for col in self.columns():
            col.set_flip_expanded(False)

    def cancel(self):
        self.animation.stop()
        self.pending = None
        self._finish_slide_layout()
        self.hover.stop()
        self.leave.stop()
        for panel in self.bubbles.values():
            panel.animation.stop()
            panel.wanted = False
            panel.hide()
        self.bar.origin = None
        self.bar.reset_wheel.stop()
        self.bar._reset_wheel()

    def remember(self):
        sm = self.window._settings_manager
        if sm is not None and self.selected is not None and not self.window._workspace_switching:
            sm.save_flip_column(self.selected.get_column_id(), self.window._grok_mode)

    def layout(self):
        if not self.enabled or self.laying_out:
            return
        if self.animation.state() == QVariantAnimation.State.Running:
            if self.scope == self._scope() and self.transition_columns == tuple(self.columns()):
                return
            self.cancel()
        self.laying_out = True
        try:
            cols = self.columns()
            if self.scope != self._scope():
                self.cancel()
                self.scope = self._scope()
                sm = self.window._settings_manager
                cid = sm.get_flip_column(self.window._grok_mode) if sm else ''
                self.selected = next((c for c in cols if c.get_column_id() == cid), None)
                self.index = 0
            if self.selected not in cols:
                self.cancel()
                self.selected = cols[min(self.index, len(cols) - 1)] if cols else None
            if self.selected is not None:
                self.index = cols.index(self.selected)
            for col in cols:
                col.set_flip_expanded(col is self.selected)
                col.setVisible(col is self.selected)
                col.set_boundary_enabled(False)
                col._stow_btn.setEnabled(False)
            if self.selected is not None:
                col = self.selected
                col.setFixedWidth(max(1, self.viewport.width()))
                col.setMinimumHeight(0)
                self.window._set_active_column(col)
            content = self.window._scroll_content
            content.setMinimumSize(0, 0)
            content.setMaximumSize(16777215, 16777215)
            content.resize(self.viewport.size())
            self.window._scroll_layout.setGeometry(content.rect())
            self.window._scroll_layout.activate()
            for name in ('_stow_restore_rail', '_stow_restore_rail_left'):
                rail = getattr(self.window, name, None)
                if rail is not None:
                    rail.hide()
            for side, panel in self.bubbles.items():
                panel.populate(cols[:self.index] if side == 'left' else cols[self.index + 1:])
                if not panel.columns:
                    panel.reveal(False)
            self.remember()
            self.window._update_empty_state()
        finally:
            self.laying_out = False

    def step(self, direction):
        cols = self.columns()
        base = self.pending if self.pending in cols else self.selected
        if base not in cols:
            return
        index = cols.index(base) + direction
        if 0 <= index < len(cols):
            self.select(cols[index])

    def select(self, column):
        if not self.enabled or column not in self.columns():
            return
        if self.animation.state() == QVariantAnimation.State.Running:
            self.pending = column
            return
        if column is self.selected:
            return
        self.hide_bubbles()
        outgoing = self.selected
        old = self.index
        self.selected = column
        self.layout()
        self.outgoing = outgoing
        self.direction = 1 if self.index > old else -1
        self.transition_columns = tuple(self.columns())
        # QHBoxLayoutの並びを保持したまま、コンテナの位置だけを一時的に動かす。
        self.window._scroll_layout.setEnabled(False)
        if outgoing is not None:
            outgoing.set_flip_expanded(True)
            outgoing.setFixedWidth(self.viewport.width())
            outgoing.setGeometry(self.viewport.rect())
            outgoing.show()
        self.selected.setGeometry(self.viewport.rect())
        self._slide_frame(0.)
        self.animation.start()

    def _slide_frame(self, value):
        width = self.viewport.width()
        offset = round(float(value) * width) * self.direction
        if self.outgoing is not None:
            self.outgoing.move(-offset, 0)
        if self.selected is not None:
            self.selected.move(self.direction * width - offset, 0)

    def _finish_slide_layout(self):
        from shiboken6 import isValid

        if self.outgoing is not None and isValid(self.outgoing):
            self.outgoing.hide()
            self.outgoing.set_flip_expanded(False)
        self.outgoing = None
        if self.selected is not None and isValid(self.selected):
            self.selected.move(0, 0)
        if self.transition_columns:
            self.window._scroll_layout.setEnabled(True)
            self.transition_columns = ()

    def _slide_finished(self):
        self._finish_slide_layout()
        self.layout()
        pending, self.pending = self.pending, None
        if pending in self.columns() and pending is not self.selected:
            self.select(pending)

    def hide_bubbles(self):
        for panel in self.bubbles.values():
            panel.reveal(False)

    def _reveal_hover(self):
        if (self.enabled and self.window.isActiveWindow()
                and not getattr(self.window, '_settings_dialog_open', False)
                and not QApplication.mouseButtons() and self.hover_side):
            self.layout()
            self.bubbles[self.hover_side].reveal(True)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Resize and obj is self.viewport:
            self.cancel()
            QTimer.singleShot(0, self.layout)
        elif kind == QEvent.Type.WindowDeactivate and obj is self.window:
            self.cancel()
        elif kind == QEvent.Type.Leave and obj is self.window:
            self.hover.stop()
            self.leave.start()
        elif kind == QEvent.Type.MouseMove:
            if not self.window.isActiveWindow() or getattr(self.window, '_settings_dialog_open', False):
                self.hide_bubbles()
                return False
            if QApplication.mouseButtons():
                self.hover.stop()
                self.hide_bubbles()
                return False
            global_pos = event.globalPosition().toPoint()
            pos = self.viewport.mapFromGlobal(global_pos)
            bar_pos = self.bar.mapFromGlobal(global_pos)
            in_bar = self.bar.rect().contains(bar_pos)
            side = None
            # 右のWebスクロールバーには検出域も配置しない。
            if in_bar:
                side = 'left' if bar_pos.x() < 10 else 'right' if bar_pos.x() >= self.bar.width() - 10 else None
            elif 38 <= pos.y() < self.viewport.height() - 24 and 0 <= pos.x() < 7:
                side = 'left'
            elif 0 <= pos.y() < 28 and self.viewport.width() - 7 <= pos.x() < self.viewport.width():
                side = 'right'
            over_panel = any(p.isVisible() and p.rect().contains(p.mapFromGlobal(global_pos)) for p in self.bubbles.values())
            if side:
                self.leave.stop()
                if self.hover_side != side or not self.hover.isActive():
                    self.hover_side = side
                    self.hover.start()
            elif over_panel:
                self.hover.stop()
                self.leave.stop()
            else:
                self.hover.stop()
                self.hover_side = None
                if not self.leave.isActive():
                    self.leave.start()
        elif kind == QEvent.Type.MouseButtonPress:
            self.hover.stop()
            if self.animation.state() == QVariantAnimation.State.Running and isinstance(obj, QWidget):
                if self.viewport.isAncestorOf(obj) and not any(p.isAncestorOf(obj) for p in self.bubbles.values()):
                    event.accept()
                    return True
        return False
