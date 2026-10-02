from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QTimer, QVariantAnimation, QEasingCurve, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QWidget
from src.ui.theme import color as theme_color


class _TransitionCurtain(QWidget):
    """WebEngine から独立した遷移用 surface。"""

    def __init__(self, parent) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self._window = parent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frame_global = QRect()
        self._alpha = 0.0
        self._transition_source = QRect()
        self._transition_target = QRect()
        self._motion_source = QRect()
        self._motion_target = QRect()
        self._transition_progress = 0.0
        self._source_edge: str | None = None
        self._target_edge: str | None = None
        self._shell_motion = False
        self._source_column_count = 1
        self._target_column_count = 1

    def invalidate_theme_cache(self) -> None:
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                gp = None
            frame = QRect(self._frame_global)
            if gp is not None and frame.isValid() and frame.contains(gp):
                title_h = min(40, max(28, int(frame.height() * 0.08)))
                if gp.y() <= frame.top() + title_h:
                    begin_drag = getattr(
                        self._window, "_begin_edge_dock_drag_from_transition", None
                    )
                    if callable(begin_drag):
                        try:
                            if begin_drag(gp):
                                event.accept()
                                return
                        except Exception:
                            pass
        event.ignore()

    def set_frame_global(self, rect: QRect) -> None:
        rect = QRect(rect)
        if self._frame_global == rect:
            return
        # 描画は frame_path でクリップされるため dirty は旧frame∪newframeで足りる。
        # shell motion中はcanvasが画面全体になるので、ここは全域updateにしない。
        dirty = self._local_frame_rect(self._frame_global).united(
            self._local_frame_rect(rect)
        ).adjusted(-3, -3, 3, 3)
        self._frame_global = rect
        if dirty.isValid():
            self.update(dirty)
        else:
            self.update()

    def set_alpha(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(self._alpha - value) < 0.001:
            return
        self._alpha = value
        dirty = self._local_frame_rect(self._frame_global).adjusted(-3, -3, 3, 3)
        if dirty.isValid():
            self.update(dirty)
        else:
            self.update()

    def configure_transition(
        self,
        source: QRect,
        target: QRect,
        source_edge: str | None = None,
        target_edge: str | None = None,
    ) -> None:
        self._transition_source = QRect(source)
        self._transition_target = QRect(target)
        self._source_edge = source_edge if source_edge in ("left", "right", "top", "bottom") else None
        self._target_edge = target_edge if target_edge in ("left", "right", "top", "bottom") else None
        self._shell_motion = bool(
            (self._source_edge is not None or self._target_edge is not None)
            and self._source_edge != self._target_edge
        )
        self._source_column_count = self._column_count_for_edge(self._source_edge)
        self._target_column_count = self._column_count_for_edge(self._target_edge)
        # ON/OFF を含め、transition surface 自体を source→target geometry へ動かす。
        # 固定すると Dock OFF で MainWindow が突然現れたように見える。
        self._motion_source = QRect(source)
        self._motion_target = QRect(target)
        self.stop_shell_motion(final=False)
        self._transition_progress = 0.0
        self.update()

    def start_shell_motion(self, _duration_ms: int) -> None:
        if not self.shell_motion_active:
            return
        self._transition_progress = 0.0
        self.update()

    def stop_shell_motion(self, *, final: bool) -> None:
        if final:
            self._transition_progress = 1.0
        self.update()

    def set_transition_progress(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(self._transition_progress - value) < 0.001:
            return
        self._transition_progress = value
        # shell motion中は描画が現在のframe内へ収まる。frameが進む分は
        # 続いて呼ばれる set_frame_global が old∪new を dirty に含める。
        # _transition_local_union は QRect#united で外接矩形になり、
        # 右→上のような切替では画面全体まで広がってしまうため使わない。
        if self.shell_motion_active:
            dirty = self._local_frame_rect(self._frame_global).adjusted(-4, -4, 4, 4)
        else:
            dirty = self._transition_local_union().adjusted(-4, -4, 4, 4)
        if dirty.isValid():
            self.update(dirty)
        else:
            self.update()

    @property
    def shell_motion_active(self) -> bool:
        return bool(self._shell_motion)

    def motion_source_frame(self) -> QRect:
        return QRect(self._motion_source if self._motion_source.isValid() else self._transition_source)

    def motion_target_frame(self) -> QRect:
        return QRect(self._motion_target if self._motion_target.isValid() else self._transition_target)

    def _transition_local_union(self) -> QRect:
        source = self._local_frame_rect(self._transition_source)
        target = self._local_frame_rect(self._transition_target)
        if source.isValid() and target.isValid():
            return source.united(target)
        if source.isValid():
            return source
        return target

    def _local_frame_rect(self, rect: QRect) -> QRect:
        local = QRect(rect)
        if not local.isValid():
            return QRect()
        local.translate(-self.x(), -self.y())
        return local

    @property
    def alpha(self) -> float:
        return float(self._alpha)

    def frame_global(self) -> QRect:
        return QRect(self._frame_global)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self._alpha <= 0.001 or not self._frame_global.isValid():
            painter.end()
            return

        local = QRect(self._frame_global)
        local.translate(-self.x(), -self.y())
        rect = QRectF(local).adjusted(0.5, 0.5, -0.5, -0.5)
        if rect.width() <= 0 or rect.height() <= 0:
            painter.end()
            return

        alpha = int(round(255 * self._alpha))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self.shell_motion_active:
            self._paint_window_transfer(painter, rect, alpha)
        else:
            self._paint_shell_rect(painter, rect, alpha, header=True)
        painter.end()

    def _paint_shell_rect(
        self, painter: QPainter, rect: QRectF, alpha: int, *, header: bool
    ) -> None:
        if rect.width() <= 0 or rect.height() <= 0 or alpha <= 0:
            return
        radius = min(10.0, max(3.0, min(rect.width(), rect.height()) * 0.06))
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, alpha / 255.0)))
        painter.setPen(QPen(QColor(theme_color("BORDER")), 1.0))
        painter.setBrush(QColor(theme_color("TRANSITION_BG")))
        painter.drawPath(path)
        if header and rect.height() >= 28:
            top_h = min(26.0, rect.height() * 0.16)
            top = QRectF(
                rect.left() + 1.0,
                rect.top() + 1.0,
                max(0.0, rect.width() - 2.0),
                top_h,
            )
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(top, QColor(theme_color("SURFACE")))
            painter.restore()
            line_y = min(rect.bottom() - 1.0, top.bottom())
            painter.setPen(QPen(QColor(theme_color("BORDER")), 1.0))
            painter.drawLine(
                int(rect.left() + 1),
                int(line_y),
                int(rect.right() - 1),
                int(line_y),
            )
        painter.restore()

    def _column_count_for_edge(self, edge: str | None) -> int:
        mode = "normal"
        if edge in ("left", "right"):
            mode = "lr"
        elif edge in ("top", "bottom"):
            mode = "tb"

        count = 0
        try:
            packs = self._window._service_packs()
            count = len(list((packs or {}).get(mode) or []))
        except Exception:
            count = 0

        if count <= 0:
            attr = {
                "normal": "_normal_column_count",
                "lr": "_edge_dock_column_count_lr",
                "tb": "_edge_dock_column_count_tb",
            }.get(mode, "_normal_column_count")
            try:
                count = int(getattr(self._window, attr, 0) or 0)
            except Exception:
                count = 0
        return max(1, min(8, count or 1))

    def _paint_window_transfer(
        self,
        painter: QPainter,
        bounds: QRectF,
        alpha: int,
    ) -> None:
        if alpha <= 0 or bounds.width() <= 2 or bounds.height() <= 2:
            return

        opacity = max(0.0, min(1.0, alpha / 255.0))
        progress = max(0.0, min(1.0, float(self._transition_progress)))
        travel = self._smootherstep01(self._phase(progress, 0.16, 0.34))
        travel *= 1.0 - self._smootherstep01(self._phase(progress, 0.64, 0.83))

        background = QColor(theme_color("TRANSITION_BG"))
        surface = QColor(theme_color("SURFACE"))
        raised = QColor(theme_color("SURFACE_RAISED"))
        border = QColor(theme_color("BORDER"))
        frame_path = self._motion_frame_path(bounds, progress)

        painter.save()
        painter.setOpacity(opacity)
        painter.setClipPath(frame_path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawPath(frame_path)
        header_h = min(
            34.0,
            max(18.0, bounds.height() * (0.075 + 0.035 * (1.0 - travel))),
        )
        header = QRectF(
            bounds.left(),
            bounds.top(),
            bounds.width(),
            min(bounds.height(), header_h),
        )
        painter.setBrush(surface)
        painter.drawRect(header)

        pad_x = max(8.0, min(18.0, bounds.width() * 0.035))
        pad_top = max(8.0, min(14.0, bounds.height() * 0.026))
        pad_bottom = max(8.0, min(16.0, bounds.height() * 0.030))
        content = QRectF(
            bounds.left() + pad_x,
            header.bottom() + pad_top,
            max(1.0, bounds.width() - pad_x * 2.0),
            max(1.0, bounds.bottom() - header.bottom() - pad_top - pad_bottom),
        )

        self._paint_transfer_columns(
            painter,
            content,
            progress,
            opacity,
            raised,
            border,
        )

        painter.setOpacity(opacity)
        # 枠線は frame_path の clip を外して描く。clip したままだと線の外側半分が
        # 切られ、移動中は枠がほぼ見えなくなる。
        painter.setClipping(False)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(frame_path)
        painter.restore()

    def _paint_transfer_columns(
        self,
        painter: QPainter,
        content: QRectF,
        progress: float,
        opacity: float,
        fill: QColor,
        border: QColor,
    ) -> None:
        if content.width() <= 2 or content.height() <= 2 or opacity <= 0.001:
            return

        source_count = max(1, min(8, int(self._source_column_count or 1)))
        target_count = max(1, min(8, int(self._target_column_count or 1)))
        count = max(source_count, target_count)
        p = max(0.0, min(1.0, float(progress)))

        compact_w = min(content.width() * 0.58, max(92.0, content.width() * 0.34))
        compact_h = min(content.height() * 0.76, max(68.0, content.height() * 0.58))
        compact = QRectF(
            content.center().x() - compact_w * 0.5,
            content.center().y() - compact_h * 0.5,
            compact_w,
            compact_h,
        )

        def _slot(group: QRectF, slots: int, index: int) -> QRectF:
            slots = max(1, int(slots))
            gap = max(2.0, min(6.0, group.width() * 0.012))
            cell_w = max(2.0, (group.width() - gap * (slots - 1)) / slots)
            x = group.left() + index * (cell_w + gap)
            return QRectF(x, group.top(), cell_w, group.height())

        def _lerp_rectf(a: QRectF, b: QRectF, value: float) -> QRectF:
            value = self._smootherstep01(value)
            return QRectF(
                a.x() + (b.x() - a.x()) * value,
                a.y() + (b.y() - a.y()) * value,
                a.width() + (b.width() - a.width()) * value,
                a.height() + (b.height() - a.height()) * value,
            )

        if p < 0.32:
            stage = self._phase(p, 0.02, 0.32)
            phase = "depart"
        elif p > 0.66:
            stage = self._phase(p, 0.66, 0.98)
            phase = "arrive"
        else:
            stage = 1.0
            phase = "travel"

        painter.save()
        painter.setPen(QPen(border, 1.0))
        chrome = QColor(theme_color("SURFACE"))
        line = QColor(theme_color("BORDER_STRONG"))

        for index in range(count):
            compact_rect = _slot(compact, count, index)
            if index < source_count:
                source_rect = _slot(content, source_count, index)
            else:
                source_rect = QRectF(
                    compact_rect.center().x(),
                    compact_rect.center().y(),
                    1.0,
                    1.0,
                )

            if index < target_count:
                target_rect = _slot(content, target_count, index)
            else:
                target_rect = QRectF(
                    compact_rect.center().x(),
                    compact_rect.center().y(),
                    1.0,
                    1.0,
                )

            if phase == "depart":
                card = _lerp_rectf(source_rect, compact_rect, stage)
            elif phase == "arrive":
                card = _lerp_rectf(compact_rect, target_rect, stage)
            else:
                card = QRectF(compact_rect)

            card_alpha = opacity
            if index >= source_count:
                card_alpha *= self._smootherstep01(self._phase(p, 0.54, 0.78))
            if index >= target_count:
                card_alpha *= 1.0 - self._smootherstep01(self._phase(p, 0.30, 0.58))
            if card_alpha <= 0.001 or card.width() <= 1.0 or card.height() <= 1.0:
                continue

            painter.setOpacity(card_alpha)
            shade = QColor(fill)
            if index % 2:
                shade = shade.darker(103)
            painter.setBrush(shade)
            painter.setPen(QPen(border, 1.0))
            painter.drawRect(card)

            top_h = min(18.0, max(5.0, card.height() * 0.085))
            if card.width() > 8.0 and card.height() > 14.0:
                top = QRectF(
                    card.left() + 1.0,
                    card.top() + 1.0,
                    max(1.0, card.width() - 2.0),
                    max(2.0, top_h),
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(chrome)
                painter.drawRect(top)

                painter.setPen(QPen(line, 1.0))
                y = top.bottom() + max(5.0, card.height() * 0.12)
                line_left = card.left() + max(4.0, card.width() * 0.12)
                line_right = card.right() - max(4.0, card.width() * 0.12)
                if line_right > line_left:
                    painter.drawLine(
                        QPointF(line_left, y),
                        QPointF(line_right, y),
                    )

        painter.restore()

    def _motion_frame_path(self, rect: QRectF, progress: float) -> QPainterPath:
        radius = min(14.0, max(7.0, min(rect.width(), rect.height()) * 0.055))
        progress = max(0.0, min(1.0, float(progress)))
        source = self._source_edge
        target = self._target_edge

        source_radii = self._edge_corner_radii(source, radius)
        target_radii = self._edge_corner_radii(target, radius)
        floating = (radius, radius, radius, radius)

        if source == target:
            radii = source_radii
        elif progress < 0.18:
            t = self._smootherstep01(progress / 0.18)
            radii = tuple(
                a + (b - a) * t for a, b in zip(source_radii, floating)
            )
        elif progress > 0.82:
            t = self._smootherstep01((progress - 0.82) / 0.18)
            radii = tuple(
                a + (b - a) * t for a, b in zip(floating, target_radii)
            )
        else:
            radii = floating

        return self._rounded_rect_path(rect, *radii)

    @staticmethod
    def _edge_corner_radii(edge: str | None, radius: float) -> tuple[float, float, float, float]:
        r = max(0.0, float(radius))
        # TL, TR, BR, BL。接着辺も含めて四隅すべて丸める。
        return r, r, r, r

    @staticmethod
    def _rounded_rect_path(
        rect: QRectF, tl: float, tr: float, br: float, bl: float
    ) -> QPainterPath:
        l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
        max_r = max(0.0, min(rect.width(), rect.height()) * 0.5)
        tl, tr, br, bl = (max(0.0, min(v, max_r)) for v in (tl, tr, br, bl))
        k = 0.5522847498307936
        path = QPainterPath()
        path.moveTo(l + tl, t)
        path.lineTo(r - tr, t)
        if tr > 0.0:
            path.cubicTo(r - tr + tr * k, t, r, t + tr - tr * k, r, t + tr)
        else:
            path.lineTo(r, t)
        path.lineTo(r, b - br)
        if br > 0.0:
            path.cubicTo(r, b - br + br * k, r - br + br * k, b, r - br, b)
        else:
            path.lineTo(r, b)
        path.lineTo(l + bl, b)
        if bl > 0.0:
            path.cubicTo(l + bl - bl * k, b, l, b - bl + bl * k, l, b - bl)
        else:
            path.lineTo(l, b)
        path.lineTo(l, t + tl)
        if tl > 0.0:
            path.cubicTo(l, t + tl - tl * k, l + tl - tl * k, t, l + tl, t)
        else:
            path.lineTo(l, t)
        path.closeSubpath()
        return path

    @staticmethod
    def _phase(value: float, start: float, end: float) -> float:
        if end <= start:
            return 1.0 if value >= end else 0.0
        return max(0.0, min(1.0, (float(value) - start) / (end - start)))

    @staticmethod
    def _smootherstep01(value: float) -> float:
        t = max(0.0, min(1.0, float(value)))
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

class TransitionCommitGate(QObject):
    """WebEngine の unsafe frame を見せず、固定 overlay 上で遷移をつなぐ。"""

    _POLL_MS = 12
    _READY_TIMEOUT_MS = 360
    _SURFACE_POLL_MS = 40
    _SURFACE_TIMEOUT_MS = 760
    _MIN_SURFACE_SETTLE_MS = 64
    _SURFACE_READY_STREAK = 2
    _FAILSAFE_MS = 1600
    _WORLD_ID = 1

    _CURTAIN_IN_MS = 42
    _SHELL_FADE_IN_MS = 72
    _MORPH_MIN_MS = 145
    _MORPH_MAX_MS = 205
    _SHELL_MOTION_MS = 1120
    _CURTAIN_OUT_MS = 96
    _SHELL_FADE_OUT_MS = 150
    _PROBE_SIZE = 10

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._generation = 0
        self._active = False
        self._releasing = False
        self._source_geometry = QRect()
        self._target_geometry = QRect()
        self._source_region = QRegion()
        self._finalize: Callable[[], None] | None = None
        self._pages: list[object] = []
        self._views: list[object] = []
        self._deadline = 0.0
        self._surface_deadline = 0.0
        self._armed_at = 0.0
        self._surface_ready_streak = 0
        self._surface_probe_pending = False
        self._poll_serial = 0
        self._poll_results: dict[int, bool] = {}

        self._curtain: _TransitionCurtain | None = None
        self._cover_anim: QVariantAnimation | None = None
        self._morph_anim: QVariantAnimation | None = None
        self._fade_anim: QVariantAnimation | None = None
        self._contract_serial = 0
        self._morph_done = False
        self._surface_ready = False
        self._target_staged = False
        self._shell_only_region = QRegion()
        self._shell_only_had_mask = False
        self._source_edge: str | None = None
        self._target_edge: str | None = None

    def invalidate_theme_cache(self) -> None:
        curtain = self._curtain
        if curtain is not None:
            try:
                curtain.invalidate_theme_cache()
            except Exception:
                pass

    @property
    def active(self) -> bool:
        return bool(self._active)

    @property
    def busy(self) -> bool:
        return bool(
            self._active
            or self._releasing
            or self._curtain is not None
            or self._cover_anim is not None
            or self._morph_anim is not None
            or self._fade_anim is not None
        )

    def _ensure_window_opaque(self) -> None:
        """Dock transition中はMainWindowのopacity animationを持ち越さない。"""
        try:
            stop = getattr(self._window, "_stop_window_opacity_anim", None)
            if callable(stop):
                stop()
        except Exception:
            pass
        try:
            if abs(float(self._window.windowOpacity()) - 1.0) > 0.001:
                self._window.setWindowOpacity(1.0)
        except Exception:
            pass

    def contract(
        self,
        target_geometry: QRect,
        continuation: Callable[[], None],
        *,
        source_edge: str | None = None,
        target_edge: str | None = None,
    ) -> None:
        """現在の画面を覆い、本体の resize/pack 切替を overlay の裏へ隔離する。"""
        if self.busy:
            return

        self._ensure_window_opaque()
        source = QRect(self._window.geometry())
        target = QRect(target_geometry)
        if (
            not source.isValid()
            or not target.isValid()
            or source.width() <= 1
            or source.height() <= 1
            or target.width() <= 1
            or target.height() <= 1
        ):
            QTimer.singleShot(0, continuation)
            return

        try:
            timer = getattr(self._window, "_normal_mask_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
        except Exception:
            pass

        self._contract_serial += 1
        serial = self._contract_serial
        source_edge, target_edge = self._resolve_transition_edges(
            source_edge, target_edge
        )
        self._source_edge = source_edge
        self._target_edge = target_edge
        self._source_geometry = QRect(source)
        self._target_geometry = QRect(target)
        self._source_region = self._window_mask_or_full(source)
        self._ensure_curtain(source, target)

        curtain = self._curtain
        if curtain is None:
            QTimer.singleShot(0, continuation)
            return

        curtain.configure_transition(
            source, target, source_edge=source_edge, target_edge=target_edge
        )
        curtain.set_transition_progress(0.0)
        curtain.set_frame_global(curtain.motion_source_frame())
        # cover fade中は実ウィンドウをまだparkしない。
        # これならロゴtransitionも自然にfade-inでき、背後のdesktopは露出しない。
        curtain.set_alpha(0.0)
        curtain.show()
        curtain.raise_()

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(
            self._SHELL_FADE_IN_MS
            if curtain.shell_motion_active
            else self._CURTAIN_IN_MS
        )
        anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))
        anim.valueChanged.connect(
            lambda value, s=serial: self._set_curtain_alpha(s, float(value))
        )
        anim.finished.connect(
            lambda s=serial, cb=continuation: self._finish_cover(s, cb)
        )
        self._cover_anim = anim
        anim.start()

    def begin(self, target_geometry: QRect, finalize: Callable[[], None]) -> None:
        self._ensure_window_opaque()
        self._generation += 1
        generation = self._generation
        self._active = True
        self._releasing = False
        self._finalize = finalize
        self._pages = []
        self._views = []
        self._deadline = 0.0
        self._surface_deadline = 0.0
        self._armed_at = 0.0
        self._surface_ready_streak = 0
        self._surface_probe_pending = False
        self._poll_serial = 0
        self._poll_results = {}
        self._surface_ready = False
        self._morph_done = False
        self._target_staged = False

        current = QRect(self._window.geometry())
        target = QRect(target_geometry)
        if not target.isValid():
            target = QRect(current)
        target.setWidth(max(1, int(target.width())))
        target.setHeight(max(1, int(target.height())))

        if not self._source_geometry.isValid():
            self._source_geometry = QRect(current)
            self._source_region = self._window_mask_or_full(current)
        self._target_geometry = QRect(target)

        if self._curtain is None:
            self._ensure_curtain(self._source_geometry, target)
            if self._curtain is not None:
                self._curtain.set_frame_global(self._curtain.motion_source_frame())
                self._curtain.set_alpha(1.0)
                self._curtain.show()
                self._curtain.raise_()
        else:
            self._resize_curtain_canvas(self._source_geometry, target)

        # 本体は morph 中に一切見せない。window region を毎フレーム変更しない。
        self._park_window_hidden()
        self._start_morph(generation)

        QTimer.singleShot(
            self._FAILSAFE_MS,
            lambda g=generation: self._force_ready(g) if self._is_current(g) else None,
        )

    def hold(self) -> None:
        if not self._active:
            return
        if self._morph_done:
            self._stage_target_window()
        else:
            self._park_window_hidden()
        curtain = self._curtain
        if curtain is not None:
            try:
                curtain.raise_()
            except Exception:
                pass

    def arm(self, webviews: Iterable[object]) -> None:
        if not self._active or self._releasing:
            return
        self.hold()
        generation = self._generation

        pages: list[object] = []
        views: list[object] = []
        seen: set[int] = set()
        for view in webviews:
            if view is None:
                continue
            try:
                page = view.page()
            except Exception:
                continue
            if page is None:
                continue
            key = id(page)
            if key in seen:
                continue
            seen.add(key)
            pages.append(page)
            views.append(view)
        self._pages = pages
        self._views = views

        if not pages:
            self._surface_ready = True
            self._try_reveal(generation)
            return

        token = int(generation)
        script = (
            "(() => {"
            f"const t={token};"
            "globalThis.__mayotterVisualCommitToken=0;"
            "const done=()=>setTimeout(()=>{globalThis.__mayotterVisualCommitToken=t;},0);"
            "if (typeof requestAnimationFrame !== 'function') { done(); return 0; }"
            "requestAnimationFrame(()=>requestAnimationFrame(done));"
            "return 0;"
            "})()"
        )
        for page in pages:
            self._run_javascript(page, script, lambda _value: None)

        now = time.monotonic()
        self._armed_at = now
        self._deadline = now + self._READY_TIMEOUT_MS / 1000.0
        self._surface_deadline = now + self._SURFACE_TIMEOUT_MS / 1000.0
        self._surface_ready_streak = 0
        self._surface_probe_pending = False
        QTimer.singleShot(self._POLL_MS, lambda g=generation: self._poll(g))

    def cancel(self, *, finalize: bool = True) -> None:
        self._ensure_window_opaque()
        self._contract_serial += 1
        self._stop_animation("cover")
        self._stop_animation("morph")
        self._stop_animation("fade")

        finalizer = self._finalize if self._active and finalize else None
        self._generation += 1
        self._active = False
        self._releasing = False
        self._pages = []
        self._views = []
        self._surface_probe_pending = False
        self._surface_ready_streak = 0
        self._surface_ready = False
        self._morph_done = False
        self._target_staged = False
        self._finalize = None

        if finalizer is not None:
            try:
                finalizer()
            except Exception:
                pass
        elif not self._source_region.isEmpty() and self._same_geometry(
            QRect(self._window.geometry()), self._source_geometry
        ):
            try:
                self._window.setMask(QRegion(self._source_region))
            except Exception:
                pass
        else:
            try:
                self._window.clearMask()
            except Exception:
                pass

        self._destroy_curtain()
        self._reset_geometry_state()

    def _finish_cover(self, serial: int, continuation: Callable[[], None]) -> None:
        if serial != self._contract_serial:
            return
        self._stop_animation("cover")
        curtain = self._curtain
        if curtain is not None:
            try:
                curtain.set_alpha(1.0)
                curtain.raise_()
            except Exception:
                pass

        # cover 完了後は本体を 1x1 region に退避。これ以降 WebEngine の細い断片は出さない。
        self._park_window_hidden()
        try:
            continuation()
        except Exception:
            self.cancel(finalize=False)
            raise

        if not self._active:
            self._finish_shell_only_transition(serial)

    def _finish_shell_only_transition(self, serial: int) -> None:
        if serial != self._contract_serial:
            return
        curtain = self._curtain
        if curtain is None:
            return

        target = QRect(self._window.geometry())
        self._shell_only_had_mask = False
        self._shell_only_region = QRegion()
        try:
            current = self._window.mask()
            if current is not None and not current.isEmpty():
                self._shell_only_had_mask = True
                self._shell_only_region = QRegion(current)
        except Exception:
            pass

        # commit 側が最終 mask を作った後に再度隠し、shell の morph 後に戻す。
        self._park_window_hidden()
        self._resize_curtain_canvas(self._source_geometry, target)
        self._animate_shell_only_to(serial, target)

    def _animate_shell_only_to(self, serial: int, target: QRect) -> None:
        curtain = self._curtain
        if curtain is None:
            self._restore_shell_only_target()
            return

        if curtain.shell_motion_active:
            start = curtain.motion_source_frame()
            end = curtain.motion_target_frame()
        else:
            start = QRect(curtain.frame_global())
            end = QRect(target)
        if not start.isValid():
            start = QRect(self._source_geometry)
        if not end.isValid():
            end = QRect(target)

        if self._same_geometry(start, end) and not curtain.shell_motion_active:
            curtain.set_frame_global(end)
            self._restore_shell_only_target()
            self._fade_shell_only(serial)
            return

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(
            self._SHELL_MOTION_MS
            if curtain.shell_motion_active
            else self._morph_duration(start, end)
        )
        anim.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.Linear)
            if curtain.shell_motion_active
            else QEasingCurve(QEasingCurve.Type.InOutCubic)
        )
        anim.valueChanged.connect(
            lambda value, s=serial, a=QRect(start), b=QRect(end):
            self._on_shell_only_morph(s, a, b, float(value))
        )

        def _done() -> None:
            if serial != self._contract_serial:
                return
            self._stop_animation("morph")
            if self._curtain is not None:
                if self._curtain.shell_motion_active:
                    self._curtain.stop_shell_motion(final=True)
                self._curtain.set_frame_global(end)
            self._restore_shell_only_target()
            self._fade_shell_only(serial)

        anim.finished.connect(_done)
        self._morph_anim = anim
        if curtain.shell_motion_active:
            curtain.start_shell_motion(self._SHELL_MOTION_MS)
        anim.start()

    def _on_shell_only_morph(self, serial: int, start: QRect, end: QRect, value: float) -> None:
        if serial != self._contract_serial or self._curtain is None:
            return
        if self._curtain.shell_motion_active:
            self._curtain.set_transition_progress(value)
            frame = self._transfer_rect(start, end, value)
        else:
            frame = self._lerp_rect(start, end, value)
        # morph中は本体が1x1 regionに退避済みで、前面を奪う他要素も無い。
        # 毎tickのraise_(SetWindowPos)は無駄な再合成を招くため状態変更時だけにする。
        self._curtain.set_frame_global(frame)

    def _restore_shell_only_target(self) -> None:
        try:
            if self._shell_only_had_mask and not self._shell_only_region.isEmpty():
                self._window.setMask(QRegion(self._shell_only_region))
            else:
                self._window.clearMask()

            # 1x1の退避regionでWin32側の最終shapeも失われるため、
            # Qt maskを戻しただけで終えず、MainWindow自身のauthoritative shapeを再適用する。
            if bool(getattr(self._window, "_edge_dock_enabled", False)):
                apply_shape = getattr(self._window, "_apply_dock_shape_mask", None)
                if callable(apply_shape):
                    apply_shape(force=True)
            else:
                apply_shape = getattr(self._window, "_update_window_mask", None)
                if callable(apply_shape):
                    apply_shape()
            self._window.update()
        except Exception:
            pass

    def _fade_shell_only(self, serial: int) -> None:
        curtain = self._curtain
        if curtain is None:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(curtain.alpha)
        anim.setEndValue(0.0)
        anim.setDuration(
            self._SHELL_FADE_OUT_MS
            if curtain.shell_motion_active
            else self._CURTAIN_OUT_MS
        )
        anim.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.InOutSine)
            if curtain.shell_motion_active
            else QEasingCurve(QEasingCurve.Type.OutCubic)
        )
        anim.valueChanged.connect(
            lambda value, s=serial: self._set_curtain_alpha(s, float(value))
        )

        def _done() -> None:
            if serial != self._contract_serial:
                return
            self._stop_animation("fade")
            self._destroy_curtain()
            self._shell_only_region = QRegion()
            self._shell_only_had_mask = False
            self._reset_geometry_state()

        anim.finished.connect(_done)
        self._fade_anim = anim
        anim.start()

    def _set_curtain_alpha(self, serial: int, value: float) -> None:
        if serial != self._contract_serial:
            return
        curtain = self._curtain
        if curtain is None:
            return
        try:
            curtain.set_alpha(value)
        except Exception:
            pass

    def _resolve_transition_edges(
        self, source_edge: str | None, target_edge: str | None
    ) -> tuple[str | None, str | None]:
        valid = {"left", "right", "top", "bottom"}
        source_edge = source_edge if source_edge in valid else None
        target_edge = target_edge if target_edge in valid else None
        if source_edge is not None or target_edge is not None:
            return source_edge, target_edge

        # _toggle_edge_dock()は方向を明示しないので、現在のDock状態から意味だけ補う。
        # geometry推測ではなく、既存stateを使うためmulti-monitorでも支点がぶれない。
        try:
            edge = getattr(self._window, "_edge_dock_direction", None)
            if edge not in valid:
                return None, None
            if bool(getattr(self._window, "_edge_dock_enabled", False)):
                return edge, None
            return None, edge
        except Exception:
            return None, None

    def _ensure_curtain(self, source: QRect, target: QRect) -> None:
        if self._curtain is None:
            try:
                self._curtain = _TransitionCurtain(self._window)
            except Exception:
                self._curtain = None
                return
        self._resize_curtain_canvas(source, target)

    def _resize_curtain_canvas(self, source: QRect, target: QRect) -> None:
        curtain = self._curtain
        if curtain is None:
            return
        canvas = QRect(source).united(QRect(target)).adjusted(-2, -2, 2, 2)
        if not canvas.isValid() or canvas.width() <= 1 or canvas.height() <= 1:
            canvas = QRect(source)
        try:
            if curtain.geometry() != canvas:
                curtain.setGeometry(canvas)
        except Exception:
            pass

    def _start_morph(self, generation: int) -> None:
        if not self._is_current(generation):
            return
        curtain = self._curtain
        if curtain is None:
            self._morph_done = True
            self._stage_target_window()
            self._try_reveal(generation)
            return

        geometry_start = QRect(self._source_geometry)
        geometry_end = QRect(self._target_geometry)
        if not geometry_end.isValid():
            geometry_end = QRect(geometry_start)
        self._resize_curtain_canvas(geometry_start, geometry_end)

        if curtain.shell_motion_active:
            start = curtain.motion_source_frame()
            end = curtain.motion_target_frame()
        else:
            start = QRect(geometry_start)
            end = QRect(geometry_end)
        if not start.isValid():
            start = QRect(geometry_start)
        if not end.isValid():
            end = QRect(start)

        curtain.set_frame_global(start)
        curtain.set_alpha(1.0)
        # morph開始時の前面確保はここで一度だけ（毎tick raise_ は廃止）。
        curtain.raise_()

        if self._same_geometry(start, end) and not curtain.shell_motion_active:
            curtain.set_frame_global(end)
            self._morph_done = True
            self._stage_target_window()
            self._try_reveal(generation)
            return

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(
            self._SHELL_MOTION_MS
            if curtain.shell_motion_active
            else self._morph_duration(start, end)
        )
        anim.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.Linear)
            if curtain.shell_motion_active
            else QEasingCurve(QEasingCurve.Type.InOutCubic)
        )
        anim.valueChanged.connect(
            lambda value, g=generation, a=QRect(start), b=QRect(end):
            self._on_morph_value(g, a, b, float(value))
        )
        anim.finished.connect(lambda g=generation: self._finish_morph(g))
        self._morph_anim = anim
        if curtain.shell_motion_active:
            curtain.start_shell_motion(self._SHELL_MOTION_MS)
        anim.start()

    def _on_morph_value(
        self, generation: int, start: QRect, end: QRect, value: float
    ) -> None:
        if not self._is_current(generation):
            return
        curtain = self._curtain
        if curtain is None:
            return
        try:
            if curtain.shell_motion_active:
                curtain.set_transition_progress(value)
                curtain.set_frame_global(self._transfer_rect(start, end, value))
            else:
                curtain.set_frame_global(self._lerp_rect(start, end, value))
        except Exception:
            pass

    def _finish_morph(self, generation: int) -> None:
        if not self._is_current(generation):
            return
        self._stop_animation("morph")
        curtain = self._curtain
        if curtain is not None:
            try:
                if curtain.shell_motion_active:
                    curtain.stop_shell_motion(final=True)
                curtain.set_frame_global(
                    curtain.motion_target_frame()
                    if curtain.shell_motion_active
                    else QRect(self._target_geometry)
                )
                curtain.raise_()
            except Exception:
                pass
        self._morph_done = True
        self._stage_target_window()
        self._try_reveal(generation)

    def _poll(self, generation: int) -> None:
        if not self._is_current(generation) or self._releasing:
            return
        now = time.monotonic()
        if not self._pages or now >= self._deadline:
            self._schedule_surface_probe(generation, 0)
            return

        self._poll_serial += 1
        serial = self._poll_serial
        self._poll_results = {}
        script = "globalThis.__mayotterVisualCommitToken || 0"
        for index, page in enumerate(list(self._pages)):
            self._run_javascript(
                page,
                script,
                lambda value, i=index, g=generation, s=serial: self._on_poll_result(
                    g, s, i, value
                ),
            )

    def _on_poll_result(self, generation: int, serial: int, index: int, value) -> None:
        if not self._is_current(generation) or self._releasing or serial != self._poll_serial:
            return
        try:
            ready = int(value or 0) == generation
        except Exception:
            ready = False
        self._poll_results[index] = ready
        if len(self._poll_results) < len(self._pages):
            return
        if all(self._poll_results.values()) or time.monotonic() >= self._deadline:
            self._schedule_surface_probe(generation, 0)
            return
        QTimer.singleShot(self._POLL_MS, lambda g=generation: self._poll(g))

    def _schedule_surface_probe(self, generation: int, delay_ms: int) -> None:
        if not self._is_current(generation) or self._releasing:
            return
        if self._surface_probe_pending:
            return
        self._surface_probe_pending = True
        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda g=generation: self._probe_surfaces(g),
        )

    def _probe_surfaces(self, generation: int) -> None:
        self._surface_probe_pending = False
        if not self._is_current(generation) or self._releasing:
            return

        # morph 中は本体を 1x1 region に退避している。probe は target を stage してから。
        if not self._morph_done:
            self._schedule_surface_probe(generation, self._SURFACE_POLL_MS)
            return

        self._stage_target_window()
        now = time.monotonic()
        if now >= self._surface_deadline:
            self._surface_ready = True
            self._try_reveal(generation)
            return

        elapsed_ms = int((now - self._armed_at) * 1000.0)
        if elapsed_ms < self._MIN_SURFACE_SETTLE_MS:
            self._schedule_surface_probe(
                generation, self._MIN_SURFACE_SETTLE_MS - elapsed_ms
            )
            return

        ready = True
        for view in list(self._views):
            if not self._surface_is_ready(view):
                ready = False
                break

        if ready:
            self._surface_ready_streak += 1
        else:
            self._surface_ready_streak = 0

        if self._surface_ready_streak >= self._SURFACE_READY_STREAK:
            self._surface_ready = True
            self._try_reveal(generation)
            return

        self._schedule_surface_probe(generation, self._SURFACE_POLL_MS)

    def _surface_is_ready(self, view) -> bool:
        """大きな黒帯だけを、小さな edge probe で判定する。full-size grab はしない。"""
        try:
            if view is None or view.width() <= 4 or view.height() <= 4:
                return False
            w = int(view.width())
            h = int(view.height())
        except Exception:
            return True

        # QWebEngineView.grab() はGPU/CPU同期を伴うため、1 view 8回のprobeは重い。
        # 黒帯検出に必要な四辺中央 + 中央の5点へ限定する。
        probes = (
            (0.50, 0.08),
            (0.92, 0.50),
            (0.50, 0.92),
            (0.08, 0.50),
            (0.50, 0.50),
        )
        black: list[bool] = []
        for px, py in probes:
            ratio = self._probe_black_ratio(view, w, h, px, py)
            if ratio is None:
                return True
            black.append(ratio >= 0.94)

        # pure-black が複数箇所へ連続して出るときだけ unsafe。
        # X の通常dark theme(#0b111f系)は pure #000 ではない。
        edge_black = sum(1 for value in black[:4] if value)
        if edge_black >= 2:
            return False
        if edge_black >= 1 and black[4]:
            return False
        return True

    def _probe_black_ratio(
        self, view, width: int, height: int, px: float, py: float
    ) -> float | None:
        size = max(6, int(self._PROBE_SIZE))
        rw = min(size, max(1, width))
        rh = min(size, max(1, height))
        x = max(0, min(width - rw, int(round((width - rw) * px))))
        y = max(0, min(height - rh, int(round((height - rh) * py))))
        try:
            pixmap = view.grab(QRect(x, y, rw, rh))
            if pixmap is None or pixmap.isNull():
                return 1.0
            image = pixmap.toImage()
        except Exception:
            return None

        iw = max(1, int(image.width()))
        ih = max(1, int(image.height()))
        total = iw * ih
        black = 0
        try:
            for yy in range(ih):
                for xx in range(iw):
                    c = image.pixelColor(xx, yy)
                    if (
                        c.alpha() > 16
                        and c.red() <= 3
                        and c.green() <= 3
                        and c.blue() <= 3
                    ):
                        black += 1
        except Exception:
            return None
        return black / max(1, total)

    def _run_javascript(self, page, script: str, callback: Callable[[object], None]) -> None:
        try:
            page.runJavaScript(script, self._WORLD_ID, callback)
            return
        except TypeError:
            pass
        except Exception:
            callback(0)
            return
        try:
            page.runJavaScript(script, callback)
        except Exception:
            callback(0)

    def _is_current(self, generation: int) -> bool:
        return bool(self._active and generation == self._generation)

    def _force_ready(self, generation: int) -> None:
        if not self._is_current(generation) or self._releasing:
            return
        self._surface_ready = True
        if not self._morph_done:
            self._stop_animation("morph")
            curtain = self._curtain
            if curtain is not None:
                try:
                    if curtain.shell_motion_active:
                        curtain.stop_shell_motion(final=True)
                    curtain.set_frame_global(
                        curtain.motion_target_frame()
                        if curtain.shell_motion_active
                        else QRect(self._target_geometry)
                    )
                    curtain.raise_()
                except Exception:
                    pass
            self._morph_done = True
        self._stage_target_window()
        self._try_reveal(generation)

    def _try_reveal(self, generation: int) -> None:
        if not self._is_current(generation) or self._releasing:
            return
        if not self._surface_ready or not self._morph_done:
            return

        self._releasing = True
        self._pages = []
        self._views = []
        self._surface_probe_pending = False

        self._ensure_window_opaque()
        finalize = self._finalize
        self._finalize = None
        # finalize 中に通常 mask を適用できるよう active は先に落とす。
        self._active = False
        if finalize is not None:
            try:
                finalize()
            except Exception:
                pass

        try:
            self._window.setUpdatesEnabled(True)
            self._window.update()
        except Exception:
            pass

        # DWM barrier は reveal 直前の1回だけ。複数回の同期待ちは animation を詰まらせる。
        self._dwm_flush()
        self._fade_curtain_out(generation)

    def _fade_curtain_out(self, generation: int) -> None:
        curtain = self._curtain
        if curtain is None:
            self._finish_reveal(generation)
            return

        # surface-ready確認とfinalizeが完了した実ウィンドウを背後に置いたまま、
        # curtainだけを短くfade-outする。ON/OFFも即時切替に戻さない。
        anim = QVariantAnimation(self)
        anim.setStartValue(curtain.alpha)
        anim.setEndValue(0.0)
        anim.setDuration(
            self._SHELL_FADE_OUT_MS
            if curtain.shell_motion_active
            else self._CURTAIN_OUT_MS
        )
        anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))
        anim.valueChanged.connect(
            lambda value, g=generation: self._on_fade_value(g, float(value))
        )
        anim.finished.connect(lambda g=generation: self._finish_reveal(g))
        self._fade_anim = anim
        anim.start()

    def _on_fade_value(self, generation: int, value: float) -> None:
        if generation != self._generation or not self._releasing:
            return
        curtain = self._curtain
        if curtain is None:
            return
        try:
            curtain.set_alpha(value)
            curtain.raise_()
        except Exception:
            pass

    def _finish_reveal(self, generation: int) -> None:
        if generation != self._generation and self._active:
            return
        self._stop_animation("fade")
        self._destroy_curtain()
        self._releasing = False
        self._pages = []
        self._views = []
        self._surface_probe_pending = False
        self._surface_ready_streak = 0
        self._surface_ready = False
        self._morph_done = False
        self._target_staged = False
        self._reset_geometry_state()
        self._ensure_window_opaque()
        try:
            self._window.update()
        except Exception:
            pass

    def _park_window_hidden(self) -> None:
        # 1x1 region 退避中も DWM の枠が本体サイズで残らないよう、枠だけ一度消す。
        # 復元は _destroy_curtain（全終了経路の共通cleanup）で行う。
        if not getattr(self, "_border_suppressed", False):
            try:
                from src.ui.window_polish import set_window_border_hidden
                self._border_suppressed = set_window_border_hidden(self._window, True)
            except Exception:
                pass
        try:
            self._window.setMask(QRegion(QRect(0, 0, 1, 1)))
        except Exception:
            pass

    def _stage_target_window(self) -> None:
        if self._target_staged:
            return
        try:
            current = QRect(self._window.geometry())
            if current.width() <= 1 or current.height() <= 1:
                return
            w = max(1, int(current.width()))
            h = max(1, int(current.height()))
            radius = max(3, min(10, min(w, h) // 2))
            self._window.setMask(
                self._target_window_region(w, h, radius, self._target_edge)
            )
            self._window.setUpdatesEnabled(True)
            self._window.update()
            self._target_staged = True
        except Exception:
            pass

    def _destroy_curtain(self) -> None:
        if getattr(self, "_border_suppressed", False):
            self._border_suppressed = False
            # 枠の可否は収納/展開の現在状態で決める（収納中に枠を復活させない）
            try:
                self._window._native_border_theme = None
                self._window._refresh_native_borders()
            except Exception:
                pass
        curtain = self._curtain
        self._curtain = None
        if curtain is None:
            return
        try:
            curtain.stop_shell_motion(final=False)
            curtain.hide()
            curtain.deleteLater()
        except Exception:
            pass

    def _stop_animation(self, which: str) -> None:
        attr = {
            "cover": "_cover_anim",
            "morph": "_morph_anim",
            "fade": "_fade_anim",
        }.get(which)
        if attr is None:
            return
        anim = getattr(self, attr, None)
        setattr(self, attr, None)
        if anim is None:
            return
        try:
            anim.stop()
            anim.deleteLater()
        except Exception:
            pass

    def _window_mask_or_full(self, geometry: QRect) -> QRegion:
        try:
            current = self._window.mask()
            if current is not None and not current.isEmpty():
                return QRegion(current)
        except Exception:
            pass
        return QRegion(QRect(0, 0, max(1, geometry.width()), max(1, geometry.height())))

    def _morph_duration(self, source: QRect, target: QRect) -> int:
        sw = max(1, source.width())
        sh = max(1, source.height())
        tw = max(1, target.width())
        th = max(1, target.height())
        scale_delta = max(abs(sw - tw) / max(sw, tw), abs(sh - th) / max(sh, th))
        move_delta = max(
            abs(source.center().x() - target.center().x()) / max(sw, tw),
            abs(source.center().y() - target.center().y()) / max(sh, th),
        )
        travel = min(1.0, max(scale_delta, min(1.0, move_delta)))
        return int(
            self._MORPH_MIN_MS
            + (self._MORPH_MAX_MS - self._MORPH_MIN_MS) * travel
        )

    @staticmethod
    def _target_window_region(
        width: int, height: int, radius: int, edge: str | None
    ) -> QRegion:
        """最終Windowと同じ角規則（四隅すべて丸）をstaging中にも使う。"""
        w = max(1, int(width))
        h = max(1, int(height))
        r = max(0, min(int(radius), w // 2, h // 2))
        if r <= 1:
            return QRegion(0, 0, w, h)

        region = QRegion(0, 0, w, h)
        corners = (
            (QRect(0, 0, r, r), QRect(0, 0, 2 * r, 2 * r)),
            (QRect(w - r, 0, r, r), QRect(w - 2 * r, 0, 2 * r, 2 * r)),
            (QRect(w - r, h - r, r, r), QRect(w - 2 * r, h - 2 * r, 2 * r, 2 * r)),
            (QRect(0, h - r, r, r), QRect(0, h - 2 * r, 2 * r, 2 * r)),
        )
        for square, ellipse_rect in corners:
            region = region.subtracted(QRegion(square))
            region = region.united(
                QRegion(ellipse_rect, QRegion.RegionType.Ellipse).intersected(
                    QRegion(square)
                )
            )
        return region

    def _reset_geometry_state(self) -> None:
        self._source_geometry = QRect()
        self._target_geometry = QRect()
        self._source_region = QRegion()
        self._shell_only_region = QRegion()
        self._shell_only_had_mask = False
        self._source_edge = None
        self._target_edge = None

    def _transfer_rect(self, a: QRect, b: QRect, t: float) -> QRect:
        t = max(0.0, min(1.0, float(t)))

        def _smooth(value: float) -> float:
            value = max(0.0, min(1.0, value))
            return value * value * (3.0 - 2.0 * value)

        aw, ah = max(1, a.width()), max(1, a.height())
        bw, bh = max(1, b.width()), max(1, b.height())
        max_w, max_h = max(aw, bw), max(ah, bh)
        min_w, min_h = min(aw, bw), min(ah, bh)

        compact_w = min(max_w, max(220, min(440, int(round(min_w * 0.72)))))
        compact_h = min(max_h, max(150, min(300, int(round(min_h * 0.58)))))

        depart_end = 0.22
        arrive_start = 0.70
        if t <= depart_end:
            u = _smooth(t / depart_end)
            w = aw + (compact_w - aw) * u
            h = ah + (compact_h - ah) * u
        elif t < arrive_start:
            w = float(compact_w)
            h = float(compact_h)
        else:
            u = _smooth((t - arrive_start) / (1.0 - arrive_start))
            w = compact_w + (bw - compact_w) * u
            h = compact_h + (bh - compact_h) * u

        acx = a.x() + aw * 0.5
        acy = a.y() + ah * 0.5
        bcx = b.x() + bw * 0.5
        bcy = b.y() + bh * 0.5

        u = _smooth(t)
        cx = acx + (bcx - acx) * u
        cy = acy + (bcy - acy) * u

        iw = max(1, int(round(w)))
        ih = max(1, int(round(h)))
        x = int(round(cx - iw * 0.5))
        y = int(round(cy - ih * 0.5))

        if self._target_edge == "top":
            y = int(round(a.top() + (b.top() - a.top()) * u))
        elif self._target_edge == "bottom":
            bottom = a.bottom() + (b.bottom() - a.bottom()) * u
            y = int(round(bottom - ih + 1))
        elif self._target_edge == "left":
            x = int(round(a.left() + (b.left() - a.left()) * u))
        elif self._target_edge == "right":
            right = a.right() + (b.right() - a.right()) * u
            x = int(round(right - iw + 1))

        return QRect(
            x,
            y,
            iw,
            ih,
        )

    @staticmethod
    def _lerp_rect(a: QRect, b: QRect, t: float) -> QRect:
        t = max(0.0, min(1.0, float(t)))
        x = int(round(a.x() + (b.x() - a.x()) * t))
        y = int(round(a.y() + (b.y() - a.y()) * t))
        w = max(1, int(round(a.width() + (b.width() - a.width()) * t)))
        h = max(1, int(round(a.height() + (b.height() - a.height()) * t)))
        return QRect(x, y, w, h)

    @staticmethod
    def _same_geometry(a: QRect, b: QRect) -> bool:
        return (
            abs(a.x() - b.x()) <= 1
            and abs(a.y() - b.y()) <= 1
            and abs(a.width() - b.width()) <= 1
            and abs(a.height() - b.height()) <= 1
        )

    @staticmethod
    def _dwm_flush() -> None:
        if sys.platform != "win32":
            return
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass
