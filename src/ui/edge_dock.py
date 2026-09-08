
from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QCursor

class PanelState(Enum):
    COLLAPSED = auto()
    EXPANDING = auto()
    EXPANDED = auto()
    COLLAPSING = auto()

class EdgeDetector(QObject):

    should_expand = Signal()
    should_collapse = Signal()

    def __init__(
        self,
        get_panel_rect: Callable[[], QRect],
        get_screen_geometry: Callable[[], QRect],
        edge: str = "right",
        trigger_px: int = 8,
        keep_open_margin: int = 40,
        hide_delay_ms: int = 450,
        poll_interval_ms: int = 50,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.get_panel_rect = get_panel_rect
        self.get_screen_geometry = get_screen_geometry
        self.edge = edge
        self.trigger_px = trigger_px
        self.keep_open_margin = keep_open_margin
        self.hide_delay_ms = hide_delay_ms

        self._state = PanelState.COLLAPSED
        self._pinned_open = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._emit_collapse)

        self._poll = QTimer(self)
        self._poll.setInterval(poll_interval_ms)
        self._poll.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._poll.isActive():
            self._poll.start()
            self._tick()

    def stop(self) -> None:
        self._poll.stop()

    @property
    def state(self) -> PanelState:
        return self._state

    def set_state(self, state: PanelState) -> None:
        self._state = state
        if state == PanelState.EXPANDED:
            self._hide_timer.stop()

    def set_pinned_open(self, pinned: bool) -> None:
        self._pinned_open = pinned
        if pinned:
            self._hide_timer.stop()

    def set_params(
        self,
        trigger_px: Optional[int] = None,
        hide_delay_ms: Optional[int] = None,
        edge: Optional[str] = None,
    ) -> None:
        if trigger_px is not None:
            self.trigger_px = trigger_px
        if hide_delay_ms is not None:
            self.hide_delay_ms = hide_delay_ms
        if edge is not None:
            self.edge = edge

    def _emit_collapse(self) -> None:
        if self._state == PanelState.EXPANDED and not self._pinned_open:
            self.should_collapse.emit()

    def _tick(self) -> None:
        if self._pinned_open:
            return
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                if app.activeModalWidget() is not None:
                    self._hide_timer.stop()
                    return
                if app.activePopupWidget() is not None:
                    self._hide_timer.stop()
                    return
        except Exception:
            pass

        pos = QCursor.pos()
        screen = self.get_screen_geometry()
        panel = self.get_panel_rect()

        near_edge = self._is_near_trigger(pos, screen, panel)
        inside_or_near_panel = self._is_inside_keep_zone(pos, panel, screen)

        if self._state in (PanelState.EXPANDING, PanelState.COLLAPSING):
            return
        if self._state == PanelState.COLLAPSED:
            if near_edge:
                self.should_expand.emit()
        elif self._state == PanelState.EXPANDED:
            if inside_or_near_panel:
                self._hide_timer.stop()
            else:
                if not self._hide_timer.isActive():
                    self._hide_timer.start(self.hide_delay_ms)

    def _is_near_trigger(self, pos: QPoint, screen: QRect, panel: QRect) -> bool:
        if not panel.isValid() or panel.width() <= 0 or panel.height() <= 0:
            return False
        tol = max(2, int(self.trigger_px))
        if self.edge == "right":
            if not (panel.top() - 2 <= pos.y() <= panel.bottom() + 2):
                return False
            return (panel.left() - tol) <= pos.x() <= (panel.right() + tol)
        if self.edge == "left":
            if not (panel.top() - 2 <= pos.y() <= panel.bottom() + 2):
                return False
            return (panel.left() - tol) <= pos.x() <= (panel.right() + tol)
        if self.edge == "top":
            if not (panel.left() - 2 <= pos.x() <= panel.right() + 2):
                return False
            return (panel.top() - tol) <= pos.y() <= (panel.bottom() + tol)
        if self.edge == "bottom":
            if not (panel.left() - 2 <= pos.x() <= panel.right() + 2):
                return False
            return (panel.top() - tol) <= pos.y() <= (panel.bottom() + tol)
        return False

    def _is_inside_keep_zone(self, pos: QPoint, panel: QRect, screen: QRect) -> bool:
        if not panel.isValid() or panel.width() <= 0:
            return False
        if self.edge == "right":
            left = panel.left() - self.keep_open_margin
            return left <= pos.x() <= screen.right() and panel.top() <= pos.y() <= panel.bottom()
        if self.edge == "left":
            right = panel.right() + self.keep_open_margin
            return screen.left() <= pos.x() <= right and panel.top() <= pos.y() <= panel.bottom()
        if self.edge == "top":
            bottom = panel.bottom() + self.keep_open_margin
            return panel.left() <= pos.x() <= panel.right() and screen.top() <= pos.y() <= bottom
        if self.edge == "bottom":
            top = panel.top() - self.keep_open_margin
            return panel.left() <= pos.x() <= panel.right() and top <= pos.y() <= screen.bottom()
        return panel.adjusted(-20, -20, 20, 20).contains(pos)

class EdgeAnimator(QObject):

    finished_expand = Signal()
    finished_collapse = Signal()
    progress_changed = Signal(float)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._anim: Optional[QVariantAnimation] = None
        self._expanding: bool = True
        self.expand_duration = 280
        self.collapse_duration = 220
        self.easing_name = "OutCubic"

    def set_durations(self, expand_ms: int, collapse_ms: int) -> None:
        self.expand_duration = max(80, expand_ms)
        self.collapse_duration = max(80, collapse_ms)

    def set_easing(self, name: str) -> None:
        self.easing_name = name if name in EASING_MAP else "OutCubic"

    def _easing(self) -> QEasingCurve:
        return QEasingCurve(EASING_MAP.get(self.easing_name, QEasingCurve.Type.OutCubic))

    def stop(self) -> None:
        anim = self._anim
        self._anim = None
        if anim is None or not isValid(anim):
            return
        try:
            anim.finished.disconnect(self._on_finished)
        except (TypeError, RuntimeError):
            pass
        try:
            anim.valueChanged.disconnect(self._on_value)
        except (TypeError, RuntimeError):
            pass
        if anim.state() == QAbstractAnimation.State.Running:
            anim.stop()

    def animate_reveal(self, start: float, end: float, duration: int, expanding: bool) -> None:
        self.stop()
        self._expanding = expanding
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(max(80, int(duration)))
        anim.setEasingCurve(self._easing())
        anim.valueChanged.connect(self._on_value)
        anim.finished.connect(self._on_finished)
        self._anim = anim
        self._on_value(start)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    def _on_value(self, v) -> None:
        self.progress_changed.emit(float(v))

    def _on_finished(self) -> None:
        expanding = self._expanding
        anim = self._anim
        self._anim = None
        if anim is not None and isValid(anim):
            anim.deleteLater()
        if expanding:
            self.finished_expand.emit()
        else:
            self.finished_collapse.emit()

from PySide6.QtCore import QEasingCurve, QVariantAnimation, QAbstractAnimation
from shiboken6 import isValid

EASING_MAP = {
    "Linear": QEasingCurve.Type.Linear,
    "InQuad": QEasingCurve.Type.InQuad,
    "OutQuad": QEasingCurve.Type.OutQuad,
    "InOutQuad": QEasingCurve.Type.InOutQuad,
    "OutCubic": QEasingCurve.Type.OutCubic,
    "InOutCubic": QEasingCurve.Type.InOutCubic,
    "OutBack": QEasingCurve.Type.OutBack,
    "InOutBack": QEasingCurve.Type.InOutBack,
}