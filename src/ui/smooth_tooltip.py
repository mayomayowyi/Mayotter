from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from src.ui.theme import BORDER, SURFACE_RAISED, TEXT


class _MinimalTooltip(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("mayotter_minimal_tooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowOpacity(0.0)

        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.AutoText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(320)
        self._label.setStyleSheet(
            f"QLabel {{ color:{TEXT}; background:transparent; border:none;"
            " font-size:11px; padding:0px; }}"
        )

        layout = QVBoxLayout(self)
        # 3px はsubtle shadow/AA用。本文はコンパクトに保つ。
        layout.setContentsMargins(11, 7, 11, 7)
        layout.setSpacing(0)
        layout.addWidget(self._label)

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.finished.connect(self._after_animation)
        self._hiding = False
        self._source = None
        self._text = ""

    def _surface_path(self, offset_y: float = 0.0) -> QPainterPath:
        rect = QRectF(self.rect()).adjusted(3.5, 3.5 + offset_y, -3.5, -3.5 + offset_y)
        path = QPainterPath()
        if rect.width() > 0 and rect.height() > 0:
            path.addRoundedRect(rect, 6.5, 6.5)
        return path

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        shadow = self._surface_path(1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawPath(shadow)

        surface = self._surface_path(0.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SURFACE_RAISED))
        p.drawPath(surface)
        pen = QPen(QColor(BORDER))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(surface)

    def show_tip(self, text: str, global_pos: QPoint, source=None) -> None:
        text = str(text or "").strip()
        if not text:
            self.hide_tip(immediate=True)
            return

        same = self.isVisible() and text == self._text and source is self._source
        self._source = source
        self._text = text
        self._label.setText(text)
        self._label.adjustSize()
        self.adjustSize()
        self._place(global_pos)

        self._anim.stop()
        self._hiding = False
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
        else:
            self.raise_()

        if same and float(self.windowOpacity()) > 0.97:
            self.setWindowOpacity(1.0)
            return

        start = max(0.0, min(1.0, float(self.windowOpacity())))
        self._anim.setDuration(max(38, int(78 * (1.0 - start))))
        self._anim.setStartValue(start)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def hide_tip(self, *, immediate: bool = False) -> None:
        self._anim.stop()
        if immediate or not self.isVisible():
            self._hiding = False
            self.setWindowOpacity(0.0)
            self.hide()
            self._source = None
            return
        self._hiding = True
        start = max(0.0, min(1.0, float(self.windowOpacity())))
        self._anim.setDuration(max(34, int(58 * start)))
        self._anim.setStartValue(start)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.start()

    def _after_animation(self) -> None:
        if self._hiding:
            self._hiding = False
            self.hide()
            self._source = None
            self.setWindowOpacity(0.0)
        elif self.isVisible():
            self.setWindowOpacity(1.0)

    def _place(self, global_pos: QPoint) -> None:
        pos = QPoint(global_pos) + QPoint(11, 16)
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen is None:
            self.move(pos)
            return
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = min(max(area.left() + 6, pos.x()), area.right() - w - 6)
        y = min(max(area.top() + 6, pos.y()), area.bottom() - h - 6)
        if y < global_pos.y() and global_pos.y() - h - 10 >= area.top():
            y = global_pos.y() - h - 10
        self.move(x, y)


class TooltipController(QObject):
    _HIDE_EVENTS = {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
        QEvent.Type.KeyPress,
        QEvent.Type.WindowDeactivate,
        QEvent.Type.ApplicationDeactivate,
    }

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._tip = _MinimalTooltip()
        self._source = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(42)
        self._hide_timer.timeout.connect(self._finish_delayed_hide)

    def _cancel_delayed_hide(self) -> None:
        if self._hide_timer.isActive():
            self._hide_timer.stop()

    def _finish_delayed_hide(self) -> None:
        self._tip.hide_tip()
        self._source = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        et = event.type()
        if et == QEvent.Type.ToolTip:
            try:
                text = str(obj.toolTip() or "")
            except Exception:
                text = ""
            if not text:
                return False
            try:
                pos = event.globalPos()
            except Exception:
                pos = QCursor.pos()
            self._cancel_delayed_hide()
            self._source = obj
            self._tip.show_tip(text, pos, obj)
            return True

        if et == QEvent.Type.Leave and obj is self._source:
            # 隣のボタンへ移ったときにフェードアウト/インでちらつかないよう、
            # 次の ToolTip イベントを少しだけ待つ。
            self._hide_timer.start()
        elif et in self._HIDE_EVENTS:
            self._cancel_delayed_hide()
            self._tip.hide_tip()
            self._source = None
        elif et in (QEvent.Type.Hide, QEvent.Type.Destroy) and obj is self._source:
            self._cancel_delayed_hide()
            self._tip.hide_tip(immediate=True)
            self._source = None
        return False


def install_smooth_tooltips(app: QApplication) -> TooltipController | None:
    if app is None:
        return None
    existing = getattr(app, "_mayotter_tooltip_controller", None)
    if existing is not None:
        return existing
    controller = TooltipController(app)
    app.installEventFilter(controller)
    app._mayotter_tooltip_controller = controller
    return controller
