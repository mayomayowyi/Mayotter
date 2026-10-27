"""WebEngine 本体を移動・半透明化せず、静止画だけでドラッグを可視化する。"""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui import theme


class ColumnDragPreview(QWidget):
    def __init__(self, column, viewport, global_x):
        super().__init__(viewport.window(), Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
        self.setGeometry(QRect(viewport.mapToGlobal(QPoint()), viewport.size()))
        # キャプチャは開始時の一度だけ。移動中に Chromium の同期 readback を繰り返さない。
        self._snapshot = column.grab()
        self._origin = column.mapToGlobal(QPoint()) - viewport.mapToGlobal(QPoint())
        self._size = column.size()
        self._anchor = float(global_x)
        self._offset = 0
        self._previous_offset = 0
        self._opacity = 1.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(140)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self.close)
        self.show()

    def move_to(self, global_x):
        self._previous_offset = self._offset
        self._offset = int(round(float(global_x) - self._anchor))
        self.update()

    def finish(self):
        if self._fade.state() == QVariantAnimation.State.Running:
            return
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for offset, alpha in ((0, 0.16), (self._previous_offset, 0.18), (self._offset, 0.68)):
            rect = QRectF(self._origin.x() + offset, self._origin.y(), self._size.width(), self._size.height())
            painter.setOpacity(self._opacity * alpha)
            painter.drawPixmap(rect, self._snapshot, QRectF(self._snapshot.rect()))
        painter.setOpacity(self._opacity)
        painter.setPen(QPen(QColor(theme.ACCENT), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = QRectF(self._origin.x() + self._offset, self._origin.y(), self._size.width(), self._size.height())
        painter.drawRoundedRect(outline.adjusted(1, 1, -1, -1), 6, 6)
        painter.end()
