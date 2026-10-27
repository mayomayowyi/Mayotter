"""共通のベクター描画と状態遷移を持つチェック／ラジオボタン。"""

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QRadioButton, QStyle, QStyleOptionButton, QStyleOptionFocusRect

from src.ui import theme


class _AnimatedChoice:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._indicator_progress = float(self.isChecked())
        self._indicator_animation = QVariantAnimation(self)
        self._indicator_animation.setDuration(160)
        self._indicator_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._indicator_animation.valueChanged.connect(self._animate_indicator)
        if isinstance(self, QCheckBox):
            self.checkStateChanged.connect(self._change_indicator)
        else:
            self.toggled.connect(self._change_indicator)

    def _animate_indicator(self, value):
        self._indicator_progress = float(value)
        self.update()

    def _change_indicator(self, *_):
        target = float(self.isChecked())
        self._indicator_animation.stop()
        if not self.isVisible():
            self._animate_indicator(target)
            return
        self._indicator_animation.setStartValue(self._indicator_progress)
        self._indicator_animation.setEndValue(target)
        self._indicator_animation.start()

    def hideEvent(self, event):
        self._indicator_animation.stop()
        self._animate_indicator(float(self.isChecked()))
        super().hideEvent(event)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        radio = isinstance(self, QRadioButton)
        style = self.style()
        painter = QPainter(self)
        label = QStyle.ControlElement.CE_RadioButtonLabel if radio else QStyle.ControlElement.CE_CheckBoxLabel
        contents = QStyle.SubElement.SE_RadioButtonContents if radio else QStyle.SubElement.SE_CheckBoxContents
        # CE_*Label はチェック欄の余白を計算しないため、Qt 標準の文字領域を渡す。
        label_option = QStyleOptionButton(option)
        label_option.rect = style.subElementRect(contents, option, self)
        style.drawControl(label, label_option, painter, self)
        indicator = QStyle.SubElement.SE_RadioButtonIndicator if radio else QStyle.SubElement.SE_CheckBoxIndicator
        rect = QRectF(style.subElementRect(indicator, option, self)).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        painter.setPen(QPen(QColor(theme.BORDER_STRONG), 1.25))
        painter.setBrush(QColor(theme.SURFACE))
        if radio:
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, 3.5, 3.5)
        painter.save()
        painter.setOpacity(painter.opacity() * self._indicator_progress)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.25))
        painter.setBrush(QColor(theme.ACCENT))
        if radio:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)
            painter.setBrush(QColor(theme.ACCENT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(rect.adjusted(3, 3, -3, -3))
        else:
            painter.drawRoundedRect(rect, 3.5, 3.5)
            # 塗り色とのコントラストを確保し、DPI に依存しないパスで描く。
            # 濃いアクセント色には明るい面の色、淡いアクセント色にはテーマの文字色（黒固定にしない）
            mark = QColor(theme.SURFACE_RAISED if QColor(theme.ACCENT).lightnessF() < 0.65 else theme.TEXT)
            painter.setPen(QPen(mark, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            if self.checkState() == Qt.CheckState.PartiallyChecked:
                path.moveTo(rect.left() + rect.width() * 0.25, rect.center().y())
                path.lineTo(rect.right() - rect.width() * 0.25, rect.center().y())
            else:
                path.moveTo(rect.left() + rect.width() * 0.23, rect.top() + rect.height() * 0.51)
                path.lineTo(rect.left() + rect.width() * 0.43, rect.top() + rect.height() * 0.71)
                path.lineTo(rect.left() + rect.width() * 0.78, rect.top() + rect.height() * 0.30)
            painter.drawPath(path)
        painter.restore()
        if option.state & QStyle.StateFlag.State_HasFocus:
            focus = QStyleOptionFocusRect()
            focus.initFrom(self)
            focus_element = QStyle.SubElement.SE_RadioButtonFocusRect if radio else QStyle.SubElement.SE_CheckBoxFocusRect
            focus.rect = style.subElementRect(focus_element, option, self)
            focus.backgroundColor = option.palette.window().color()
            style.drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, focus, painter, self)
        painter.end()


class AnimatedCheckBox(_AnimatedChoice, QCheckBox):
    pass


class AnimatedRadioButton(_AnimatedChoice, QRadioButton):
    pass
