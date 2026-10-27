"""アプリのアイコン（EXE・Setup 共通の mayotter.ico）を元ロゴから生成する。

ZIP 版の Mayotter.exe（PyInstaller）と Setup の両方が、ビルドごとにここで作った同じ ICO を使う。
背景は透明のまま、ロゴの形・色は変えない。
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/ui/assets/mayotter_cover.png'
# 小さいサイズは、拡大済みの原稿（SOURCE）を経由せず元の mayotter_cat.png から直接縮小する。
# 拡大済み原稿の輪郭はにじんでおり、そこから作る小サイズはエクスプローラーの一覧で並が荒く見える。
SOURCE_ORIGINAL = ROOT / 'src/ui/assets/mayotter_cat.png'
# Windows の表示倍率（100/125/150/200%）の小・中・大アイコンで、拡大縮小せずに選ばれるサイズ
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

# 小さいサイズ（この値以下）だけ、本体の外側のロゴ本来の縁取りを、最低でも KEYLINE 画素の幅で描く。
# 元画像の縁取りは元の大きさの 0.3% ほどしかなく、小さいサイズでは画素より細くなって
# 輪郭がにじむだけになり、暗い背景（暗いテーマのエクスプローラー・タスクバー）では猫が見えなくなる。
SMALL_MAX_SIZE = 64
KEYLINE = 0.7
LINE_ALPHA = 0.85
SUPERSAMPLE = 8
GAP_CLOSE_MAX_SIZE = 24      # このサイズ以下では、頭と耳の境の細線（画素の1/8未満）を埋める


def load_logo(path: Path = SOURCE, min_side: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """ロゴの不透明度（0〜1、高さ×幅）と RGB を読む。min_side は縮小先の画質に必要な最小の一辺。"""
    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull() or min(image.width(), image.height()) < (min_side if min_side is not None else max(SIZES) * 2):
        raise ValueError('App icon requires the high-resolution Mayotter logo')
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    pixels = pixels[:, :image.width()].astype(np.float64)
    return pixels[..., 3] / 255.0, pixels[..., :3]


def _bounds(alpha: np.ndarray) -> tuple[int, int, int, int]:
    columns = np.flatnonzero(alpha.max(axis=0) >= 0.5)
    rows = np.flatnonzero(alpha.max(axis=1) >= 0.5)
    return columns[0], columns[-1] + 1, rows[0], rows[-1] + 1


def _area_weights(count: int, length: int, scale: float, origin: float, offset: float) -> np.ndarray:
    """出力 count 画素それぞれが覆う元画像の範囲（長さ length）への面積比。範囲外は透明として扱う。"""
    weights = np.zeros((count, length))
    for index in range(count):
        start = origin + (index - offset) / scale
        end = origin + (index + 1 - offset) / scale
        for source in range(max(0, int(np.floor(start))), min(length, int(np.ceil(end)))):
            weights[index, source] = min(end, source + 1) - max(start, source)
    return weights / (end - start)


def _rgba(color: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    """乗算済みの色と不透明度（0〜1）から RGBA（uint8）を作る。"""
    with np.errstate(invalid='ignore', divide='ignore'):
        straight = np.where(coverage[..., None] > 0, color / coverage[..., None], 0)
    return np.rint(np.dstack([straight, coverage * 255]).clip(0, 255)).astype(np.uint8)


def render_large(alpha: np.ndarray, rgb: np.ndarray, size: int) -> np.ndarray:
    """元画像（1024px）から面積平均で縮小する（縁取りは元のまま）。戻り値は (size, size, 4) の RGBA。"""
    left, right, top, bottom = _bounds(alpha)
    margin = max(1, round(size / 32))
    scale = (size - margin * 2) / (bottom - top)
    offset_x = np.floor((size - (right - left) * scale) / 2)
    wy = _area_weights(size, alpha.shape[0], scale, top, margin)
    wx = _area_weights(size, alpha.shape[1], scale, left, offset_x)
    coverage = wy @ alpha @ wx.T
    color = np.stack([wy @ (alpha * rgb[..., c]) @ wx.T for c in range(3)], axis=-1)
    return _rgba(color, coverage)


def _dilate(mask: np.ndarray, radius: float) -> np.ndarray:
    reach = int(np.ceil(radius))
    padded = np.pad(mask, reach)
    out = np.zeros_like(mask)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dy * dy + dx * dx <= radius * radius:
                out |= padded[reach + dy:reach + dy + mask.shape[0], reach + dx:reach + dx + mask.shape[1]]
    return out


def render_small(alpha: np.ndarray, rgb: np.ndarray, size: int) -> np.ndarray:
    """小さいサイズ用。本体（濃色）は元の形のまま、外側の縁取りを最低 KEYLINE 画素の幅にする。

    本体と縁取りの色は元画像から取る（本体＝不透明な画素、縁取り＝半透明の縁の画素の色）。
    縁取りの分だけ本体を内側に寄せ、アイコン全体の大きさは変えない。
    """
    fill = np.median(rgb[alpha == 1.0], axis=0)
    line = np.median(rgb[(alpha > 0.1) & (alpha < 0.9)], axis=0)
    left, right, top, bottom = _bounds(alpha)
    margin = max(1, round(size / 32)) + KEYLINE
    scale = (size - margin * 2) / (bottom - top)
    ss = SUPERSAMPLE
    offset_x = (size - (right - left) * scale) / 2
    wy = _area_weights(size * ss, alpha.shape[0], scale * ss, top, margin * ss)
    wx = _area_weights(size * ss, alpha.shape[1], scale * ss, left, offset_x * ss)
    body = (wy @ (alpha >= 0.5).astype(np.float64) @ wx.T) >= 0.5
    if size <= GAP_CLOSE_MAX_SIZE:
        body = ~_dilate(~_dilate(body, 1.0), 1.0)
    ring = _dilate(body, KEYLINE * ss) & ~body
    opacity = np.where(body, 1.0, np.where(ring, LINE_ALPHA, 0.0))
    color = np.where(body[..., None], fill, line) * opacity[..., None]

    def reduce(values: np.ndarray) -> np.ndarray:
        return values.reshape(size, ss, size, ss, *values.shape[2:]).mean(axis=(1, 3))

    return _rgba(reduce(color), reduce(opacity))


def render_frame(alpha: np.ndarray, rgb: np.ndarray, size: int) -> np.ndarray:
    return render_small(alpha, rgb, size) if size <= SMALL_MAX_SIZE else render_large(alpha, rgb, size)


def _png(frame: np.ndarray) -> bytes:
    size = frame.shape[0]
    image = QImage(frame.tobytes(), size, size, size * 4, QImage.Format.Format_RGBA8888)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError('Could not encode app icon')
    return bytes(buffer.data())


def build_ico(source_path: Path = SOURCE) -> bytes:
    alpha, rgb = load_logo(source_path)
    # ≤64px は元の原画から直接縮小する（拡大済み原稿を経由しない）。余白・位置・縦横比は従来と同じ。
    small_alpha, small_rgb = load_logo(SOURCE_ORIGINAL, min_side=SMALL_MAX_SIZE * 4)
    entries, images = [], []
    offset = 6 + 16 * len(SIZES)
    for size in SIZES:
        frame = render_frame(small_alpha, small_rgb, size) if size <= SMALL_MAX_SIZE else render_frame(alpha, rgb, size)
        png = _png(frame)
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        images.append(png)
        offset += len(png)
    return struct.pack('<HHH', 0, 1, len(SIZES)) + b''.join(entries + images)


def write_ico(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(build_ico())
    return destination


if __name__ == '__main__':
    import sys
    print(write_ico(Path(sys.argv[1])))
