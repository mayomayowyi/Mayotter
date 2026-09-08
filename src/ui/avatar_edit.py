
from __future__ import annotations

from pathlib import Path

from src.ui.theme import (
    apply_overlay_theme,
    overlay_stylesheet,
    SURFACE,
    TEXT,
    TEXT_SECONDARY,
    BORDER_ACCENT,
)
from src.ui.icons import make_close_icon

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

class _AvatarCanvas(QWidget):

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(280, 280)
        self.setMouseTracking(True)
        self._src: QImage | None = None
        self.crop_x = 0.0
        self.crop_y = 0.0
        self.scale = 1.0
        self.rotation = 0.0
        self._drag = False
        self._rotating = False
        self._last = QPointF()
        self._block_emit = False

    def set_image(self, path: str) -> None:
        img = QImage(path)
        self._src = None if img.isNull() else img
        self.update()

    def set_transform(self, crop_x: float, crop_y: float, scale: float, rotation: float) -> None:
        self.crop_x = max(-1.0, min(1.0, float(crop_x)))
        self.crop_y = max(-1.0, min(1.0, float(crop_y)))
        self.scale = max(1.0, min(8.0, float(scale)))
        rot = float(rotation) % 360.0
        if rot > 180.0:
            rot -= 360.0
        self.rotation = rot
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#0f1117"))
        margin = 8
        dest = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        path = QPainterPath()
        path.addEllipse(dest)
        p.setClipPath(path)
        if self._src is not None and not self._src.isNull():
            from src.media.visual import _cover_square_image

            sq = _cover_square_image(
                self._src,
                size=max(64, int(dest.width())),
                crop_x=self.crop_x,
                crop_y=self.crop_y,
                scale=self.scale,
                rotation=self.rotation,
            )
            p.drawImage(dest, sq)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(BORDER_ACCENT), 1.5))
        p.drawEllipse(dest)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = True
        self._rotating = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._last = event.position()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._drag:
            return
        pos = event.position()
        dx = pos.x() - self._last.x()
        dy = pos.y() - self._last.y()
        self._last = pos
        if self._rotating or (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.rotation = max(-180.0, min(180.0, self.rotation + dx * 0.6))
        else:
            import math
            rad = math.radians(self.rotation)
            c, s = math.cos(rad), math.sin(rad)
            ldx = c * dx + s * dy
            ldy = -s * dx + c * dy
            self.crop_x = max(-1.0, min(1.0, self.crop_x + ldx / 90.0))
            self.crop_y = max(-1.0, min(1.0, self.crop_y + ldy / 90.0))
        self.update()
        if not self._block_emit:
            self.changed.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = False
        self._rotating = False
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.08 if delta > 0 else (1.0 / 1.08)
        self.scale = max(1.0, min(8.0, self.scale * factor))
        self.update()
        if not self._block_emit:
            self.changed.emit()
        event.accept()

class AvatarEditDialog(QDialog):

    def __init__(
        self,
        image_path: str,
        *,
        crop_x: float = 0.0,
        crop_y: float = 0.0,
        scale: float = 1.0,
        rotation: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("音声投稿画像を編集")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._path = str(image_path)
        self.setMinimumWidth(340)
        self.setObjectName("mayotter_settings_dialog")
        try:
            apply_overlay_theme(self)
        except Exception:
            try:
                self.setStyleSheet(overlay_stylesheet())
            except Exception:
                pass

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(10)

        from PySide6.QtWidgets import QToolButton
        from PySide6.QtCore import QSize
        title_row = QHBoxLayout()
        title_lbl = QLabel("音声投稿画像を編集")
        title_lbl.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:600;")
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        close_tb = QToolButton()
        try:
            close_tb.setIcon(make_close_icon("#93a5c4", 12))
            close_tb.setIconSize(QSize(12, 12))
        except Exception:
            close_tb.setText("×")
        close_tb.setFixedSize(24, 24)
        close_tb.setStyleSheet(
            "QToolButton { background:transparent; border:none; border-radius:4px; }"
            "QToolButton:hover { background:#1a2740; }"
        )
        close_tb.clicked.connect(self.reject)
        title_row.addWidget(close_tb)
        root.addLayout(title_row)

        self._canvas = _AvatarCanvas()
        self._canvas.set_image(self._path)
        self._canvas.set_transform(crop_x, crop_y, scale, rotation)
        root.addWidget(self._canvas, 0, Qt.AlignmentFlag.AlignHCenter)

        scale_row = QHBoxLayout()
        scale_lbl = QLabel("拡大縮小")
        scale_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px; min-width:56px;")
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(100, 800)
        self._scale_slider.setValue(int(round(max(1.0, min(8.0, float(scale))) * 100)))
        scale_row.addWidget(scale_lbl)
        scale_row.addWidget(self._scale_slider, 1)
        root.addLayout(scale_row)

        rot0 = float(rotation) % 360.0
        if rot0 > 180.0:
            rot0 -= 360.0
        rot_row = QHBoxLayout()
        rot_lbl = QLabel("回転")
        rot_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px; min-width:56px;")
        self._rot_slider = QSlider(Qt.Orientation.Horizontal)
        self._rot_slider.setRange(-180, 180)
        self._rot_slider.setValue(int(round(rot0)))
        rot_row.addWidget(rot_lbl)
        rot_row.addWidget(self._rot_slider, 1)
        root.addLayout(rot_row)

        def _from_scale_slider(v: int) -> None:
            self._canvas.scale = max(1.0, min(8.0, float(v) / 100.0))
            self._canvas.update()

        def _from_rot_slider(v: int) -> None:
            self._canvas.rotation = float(v)
            self._canvas.update()

        self._scale_slider.valueChanged.connect(_from_scale_slider)
        self._rot_slider.valueChanged.connect(_from_rot_slider)

        def _from_canvas() -> None:
            self._scale_slider.blockSignals(True)
            self._rot_slider.blockSignals(True)
            self._scale_slider.setValue(int(round(self._canvas.scale * 100)))
            self._rot_slider.setValue(int(round(self._canvas.rotation)))
            self._scale_slider.blockSignals(False)
            self._rot_slider.blockSignals(False)

        self._canvas.changed.connect(_from_canvas)

        self._save_crop_cb = QCheckBox("編集後の画像を保存")
        self._save_crop_cb.setChecked(False)
        self._save_crop_cb.setStyleSheet(
            f"QCheckBox {{ color:{TEXT}; font-size:12px; spacing:6px; }}"
            f"QCheckBox::indicator {{ width:14px; height:14px; }}"
        )
        root.addWidget(self._save_crop_cb)

        row = QHBoxLayout()
        cancel = QPushButton("キャンセル")
        apply = QPushButton("適用")
        apply.setDefault(True)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(apply)
        root.addLayout(row)

    def set_save_cropped(self, enabled: bool) -> None:
        try:
            self._save_crop_cb.setChecked(bool(enabled))
        except Exception:
            pass

    def save_cropped_checked(self) -> bool:
        try:
            return bool(self._save_crop_cb.isChecked())
        except Exception:
            return False

    def result_transform(self) -> tuple[str, float, float, float, float]:
        c = self._canvas
        return (self._path, c.crop_x, c.crop_y, c.scale, c.rotation)

    def export_cropped_png(self, dest: Path, size: int = 512) -> str | None:
        from src.media.visual import _cover_square_image

        c = self._canvas
        if c._src is None or c._src.isNull():
            return None
        try:
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            sq = _cover_square_image(
                c._src,
                size=int(size),
                crop_x=c.crop_x,
                crop_y=c.crop_y,
                scale=c.scale,
                rotation=c.rotation,
            )
            if sq is None or sq.isNull():
                return None
            if not sq.save(str(dest), "PNG"):
                return None
            return str(dest)
        except Exception:
            return None

def open_avatar_editor(
    parent,
    image_path: str,
    *,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    save_cropped: bool = False,
    dest_dir: str | None = None,
) -> tuple[str, float, float, float, float, bool] | None:
    if not image_path or not Path(image_path).is_file():
        return None
    dlg = AvatarEditDialog(
        image_path,
        crop_x=crop_x,
        crop_y=crop_y,
        scale=scale,
        rotation=rotation,
        parent=parent,
    )
    dlg.set_save_cropped(bool(save_cropped))
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    path, cx, cy, sc, rot = dlg.result_transform()
    want_save = dlg.save_cropped_checked()
    if want_save:
        try:
            from src.core.paths import default_audio_visual_dir, ensure_directories
            ensure_directories()
            folder = Path(str(dest_dir).strip()) if dest_dir else default_audio_visual_dir()
            folder.mkdir(parents=True, exist_ok=True)
            base = "audio_visual_crop"
            out = folder / f"{base}.png"
            if out.exists():
                n = 1
                while n <= 9999:
                    candidate = folder / f"{base}_{n:03d}.png"
                    if not candidate.exists():
                        out = candidate
                        break
                    n += 1
            written = dlg.export_cropped_png(out, size=512)
            if written:
                return (written, 0.0, 0.0, 1.0, 0.0, True)
        except Exception:
            pass
    return (path, cx, cy, sc, rot, want_save)

