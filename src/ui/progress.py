"""Mayotter 共通の進行メーター（細く丸いミニマルな見た目、値の変化と待機表示が滑らか）。"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QProgressBar

from src.ui.theme import color

_HEIGHT = 6
_BUSY_MS = 1500


class SmoothProgressBar(QProgressBar):
    """QProgressBar 互換。範囲が (0, 0) のときは待機表示（イージングで往復する帯）になる。

    animate=True のとき、値の変化を短いイージングで補間する。呼び出し側が表示値を自前で補間している場合は False。
    """

    def __init__(self, parent=None, *, animate: bool = True) -> None:
        super().__init__(parent)
        self._animate = animate
        self._shown = 0.0
        self._phase = 0.0
        self.setTextVisible(False)
        self.setFixedHeight(_HEIGHT)
        self.setMinimumWidth(120)
        self._value_anim = QVariantAnimation(self)
        self._value_anim.setDuration(240)
        self._value_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._value_anim.valueChanged.connect(self._on_shown)
        self._busy_anim = QVariantAnimation(self)
        self._busy_anim.setStartValue(0.0)
        self._busy_anim.setEndValue(1.0)
        self._busy_anim.setDuration(_BUSY_MS)
        self._busy_anim.setLoopCount(-1)
        self._busy_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._busy_anim.valueChanged.connect(self._on_phase)

    def _indeterminate(self) -> bool:
        return self.minimum() == 0 and self.maximum() == 0

    def _fraction(self) -> float:
        span = self.maximum() - self.minimum()
        return 0.0 if span <= 0 else max(0.0, min(1.0, (self.value() - self.minimum()) / span))

    def _on_shown(self, value) -> None:
        self._shown = float(value)
        self.update()

    def _on_phase(self, value) -> None:
        self._phase = float(value)
        self.update()

    def _sync_animations(self) -> None:
        if self.isVisible() and self._indeterminate():
            if self._busy_anim.state() != QVariantAnimation.State.Running:
                self._busy_anim.start()
        else:
            self._busy_anim.stop()

    def setRange(self, minimum: int, maximum: int) -> None:
        super().setRange(minimum, maximum)
        self._sync_animations()
        self.update()

    def setValue(self, value: int) -> None:
        super().setValue(value)
        target = self._fraction()
        self._value_anim.stop()
        if self._animate and self.isVisible() and abs(target - self._shown) > 0.002:
            self._value_anim.setStartValue(self._shown)
            self._value_anim.setEndValue(target)
            self._value_anim.start()
        else:
            self._shown = target
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animations()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._busy_anim.stop()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        painter.fillPath(track, QColor(color('BORDER')))
        painter.setClipPath(track)
        fill = QColor(color('ACCENT_STRONG'))
        if self._indeterminate():
            width = rect.width() * 0.34
            left = -width + (rect.width() + width) * self._phase
            bar = QRectF(left, 0, width, rect.height())
        else:
            bar = QRectF(0, 0, max(rect.height(), rect.width() * self._shown) if self._shown > 0 else 0, rect.height())
        if bar.width() > 0:
            path = QPainterPath()
            path.addRoundedRect(bar, radius, radius)
            painter.fillPath(path, fill)
        painter.end()
