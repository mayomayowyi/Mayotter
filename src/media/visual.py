
from __future__ import annotations

import struct
import wave
from pathlib import Path

from src.ui.theme import color as theme_color

# 出力する動画の背景（画像が無いとき）。アプリのテーマに左右されず、半透明の白い波形が映える暗色にする
VIDEO_BG = "#0f1117"

def _theme_qcolor(role: str, alpha: int | None = None):
    from PySide6.QtGui import QColor
    c = QColor(theme_color(role))
    if alpha is not None:
        c.setAlpha(max(0, min(255, int(alpha))))
    return c

def decode_audio_to_wav(src: str | Path, dst: Path) -> Path | None:
    from src.media.ffmpeg_util import find_ffmpeg
    import subprocess
    import sys

    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    ff = str(find_ffmpeg())
    cmd = [
        ff,
        "-hide_banner",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(dst),
    ]
    kw: dict = {
        "capture_output": True,
        "timeout": 180,
        "shell": False,
    }
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(cmd, **kw)
        if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 44:
            return dst
    except Exception:
        pass
    return None

def _load_mono_pcm(audio_path: str | Path) -> tuple[list[float], int, float]:
    path = Path(audio_path)
    if not path.is_file() or path.suffix.lower() != ".wav":
        return [], 44100, 0.0
    try:
        with wave.open(str(path), "rb") as w:
            nch = w.getnchannels()
            sw = w.getsampwidth()
            rate = int(w.getframerate() or 44100)
            nframes = w.getnframes()
            if nframes <= 0 or rate <= 0 or sw not in (1, 2):
                return [], rate, 0.0
            raw = w.readframes(nframes)
        if sw == 2:
            count = len(raw) // 2
            samples = struct.unpack("<" + "h" * count, raw[: count * 2])
            scale = 32768.0
        else:
            samples = [b - 128 for b in raw]
            scale = 128.0
        if nch > 1:
            mono = []
            for i in range(0, len(samples), nch):
                chunk = samples[i : i + nch]
                mono.append(sum(chunk) / len(chunk))
            samples = mono
        floats = [max(-1.0, min(1.0, s / scale)) for s in samples]
        dur = len(floats) / float(rate) if rate else 0.0
        return floats, rate, dur
    except Exception:
        return [], 44100, 0.0

def _level_for_analysis(samples: list[float], rate: int) -> list[float]:
    """小さい録音でも波形が動くよう、解析用にだけ音量を揃える（出力音声は変えない）。"""
    try:
        import numpy as np
    except Exception:
        return samples
    if len(samples) < rate:
        return samples
    x = np.asarray(samples, dtype=np.float64)
    frame = max(1, rate // 10)
    n = len(x) // frame
    rms = np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    loud = float(np.percentile(rms, 95))
    if loud < 1e-4:
        return samples
    gain = max(1.0, min(30.0, 0.10 / loud))
    return np.clip(x * gain, -1.0, 1.0).tolist()

def _spectrum_bars_at_time(
    samples: list[float],
    rate: int,
    t_sec: float,
    *,
    n_bars: int = 128,
    fft_size: int = 2048,
    prev: list[float] | None = None,
) -> tuple[list[float], dict]:
    import math

    try:
        import numpy as np
    except Exception:
        np = None

    n_bars = max(32, int(n_bars))
    fft_size = int(fft_size)
    if fft_size < 256:
        fft_size = 256
    fft_size = 1 << int(round(math.log2(fft_size)))

    if not samples or rate <= 0:
        base = [0.0] * n_bars
        return base, {"low": 0.0, "mid": 0.0, "high": 0.0}

    center = int(max(0, min(len(samples) - 1, t_sec * rate)))
    half = fft_size // 2
    start = center - half
    chunk = [0.0] * fft_size
    for i in range(fft_size):
        si = start + i
        if 0 <= si < len(samples):
            chunk[i] = samples[si]

    rms = sum(x * x for x in chunk) / max(1, len(chunk))
    rms = math.sqrt(max(0.0, rms))

    if np is not None:
        arr = np.asarray(chunk, dtype=np.float64)
        window = np.hanning(fft_size)
        spec = np.abs(np.fft.rfft(arr * window))
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / rate)
        mag = (spec.astype(np.float64) + 1e-20) ** 2
    else:
        windowed = [
            chunk[i] * (0.5 - 0.5 * math.cos(2 * math.pi * i / max(1, fft_size - 1)))
            for i in range(fft_size)
        ]
        n_bins = fft_size // 2 + 1
        mag = []
        freqs = []
        for k in range(n_bins):
            re = im = 0.0
            for n, x in enumerate(windowed):
                ang = -2.0 * math.pi * k * n / fft_size
                re += x * math.cos(ang)
                im += x * math.sin(ang)
            mag.append(re * re + im * im + 1e-20)
            freqs.append(k * rate / float(fft_size))

    f_min = 60.0
    f_max = min(8000.0, rate * 0.45)
    if f_max <= f_min * 1.2:
        f_max = f_min * 8.0

    raw: list[float] = []
    for i in range(n_bars):
        t0 = i / max(1, n_bars - 1)
        t1 = (i + 0.999) / max(1, n_bars - 1)
        f0 = f_min * ((f_max / f_min) ** t0)
        f1 = f_min * ((f_max / f_min) ** t1)
        energy = 0.0
        if np is not None:
            mask = (freqs >= f0) & (freqs < f1)
            if np.count_nonzero(mask) >= 2:
                energy = float(np.mean(mag[mask]))
            else:
                # 低域はFFTの1ビンが複数のバーにまたがる。最寄りビンの複製だと段差になるので
                # 隣り合うビンの間を dB で線形補間する
                fc = 0.5 * (f0 + f1)
                db = np.interp(fc, freqs, 10.0 * np.log10(mag))
                energy = float(10.0 ** (db / 10.0))
        else:
            count = 0
            for fk, mv in zip(freqs, mag):
                if f0 <= fk < f1:
                    energy += mv
                    count += 1
            if count > 0:
                energy /= count
            else:
                best = min(range(len(freqs)), key=lambda j: abs(freqs[j] - 0.5 * (f0 + f1)))
                energy = mag[best]
        raw.append(max(1e-20, energy))

    smooth_raw = list(raw)
    kernel = (0.15, 0.70, 0.15)
    nxt = []
    for i in range(n_bars):
        acc = 0.0
        for k, w in enumerate(kernel):
            acc += smooth_raw[(i + k - 1) % n_bars] * w
        nxt.append(acc)
    smooth_raw = nxt

    noise_gate = 0.012
    dbs = [10.0 * math.log10(v) for v in smooth_raw]
    sorted_db = sorted(dbs)
    floor = sorted_db[max(0, n_bars // 8)]
    levels = []
    for db in dbs:
        x = (db - floor) / 48.0
        x = max(0.0, x)
        y = 1.0 - math.exp(-1.6 * x)
        y = math.tanh(0.95 * y)
        levels.append(float(y))

    presence = min(1.0, max(0.0, (rms - noise_gate * 0.35) / 0.18))
    presence = presence ** 0.65
    levels = [
        min(1.0, v * (0.35 + 0.65 * presence) + 0.12 * presence * v)
        for v in levels
    ]

    if prev is not None and len(prev) == n_bars:
        out = []
        for i, (a, b) in enumerate(zip(levels, prev)):
            frac = i / max(1, n_bars - 1)
            if a >= b:
                alpha = 0.32 + 0.48 * frac
            else:
                alpha = 0.18 + 0.36 * frac
            out.append(max(0.0, min(1.0, alpha * a + (1.0 - alpha) * b)))
        levels = out

    third = max(1, n_bars // 3)
    low_e = sum(levels[:third]) / third
    mid_e = sum(levels[third : 2 * third]) / max(1, min(third, n_bars - third))
    high_e = sum(levels[2 * third :]) / max(1, n_bars - 2 * third)
    info = {
        "low": float(low_e),
        "mid": float(mid_e),
        "high": float(high_e),
        "rms": float(rms),
        "peak_bar": int(max(range(n_bars), key=lambda i: levels[i])) if levels else 0,
    }
    return levels, info

def _visual_map_levels(
    levels: list[float],
    *,
    rms: float | None = None,
) -> list[float]:
    if not levels:
        return []
    vals = [max(0.0, min(1.0, float(v))) for v in levels]
    peak = max(vals)
    if peak <= 1e-6:
        return [0.0] * len(vals)

    if rms is not None and rms > 0.0:
        raw = max(0.0, min(1.0, float(rms) * 1.15))
    else:
        raw = max(0.0, min(1.0, peak))

    if raw <= 1e-6:
        open_amt = 0.0
    else:
        open_amt = min(0.88, (raw ** 0.55) * 2.4)

    out: list[float] = []
    for v in vals:
        s = v / peak
        out.append(float(min(1.0, open_amt * (s ** 1.25))))

    n = len(out)
    if n >= 3:
        out = [
            0.12 * out[(i - 1) % n] + 0.76 * out[i] + 0.12 * out[(i + 1) % n]
            for i in range(n)
        ]
    return out

def _closed_catmull_rom_path(points: list) -> "object":
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath

    n = len(points)
    path = QPainterPath()
    if n < 3:
        if n:
            path.moveTo(points[0])
        return path
    path.moveTo(points[0])
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        c1 = QPointF(
            p1.x() + (p2.x() - p0.x()) / 6.0,
            p1.y() + (p2.y() - p0.y()) / 6.0,
        )
        c2 = QPointF(
            p2.x() - (p3.x() - p1.x()) / 6.0,
            p2.y() - (p3.y() - p1.y()) / 6.0,
        )
        path.cubicTo(c1, c2, p2)
    path.closeSubpath()
    return path

def _cover_square_image(
    img,
    size: int = 512,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QColor

    if img is None or img.isNull():
        return img
    try:
        scale = max(1.0, min(8.0, float(scale)))
    except Exception:
        scale = 1.0
    try:
        rotation = float(rotation)
    except Exception:
        rotation = 0.0
    try:
        cx = max(-1.0, min(1.0, float(crop_x)))
    except Exception:
        cx = 0.0
    try:
        cy = max(-1.0, min(1.0, float(crop_y)))
    except Exception:
        cy = 0.0

    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor(0, 0, 0, 0))
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.translate(size / 2.0, size / 2.0)
    painter.rotate(rotation)
    iw, ih = float(img.width()), float(img.height())
    base = max(size / max(1.0, iw), size / max(1.0, ih))
    s = base * scale
    painter.scale(s, s)
    view_w = size / s
    view_h = size / s
    free_x = max(0.0, iw - view_w)
    free_y = max(0.0, ih - view_h)
    ox = (free_x / 2.0) * cx
    oy = (free_y / 2.0) * cy
    painter.drawImage(QRectF(-iw / 2.0 + ox, -ih / 2.0 + oy, iw, ih), img)
    painter.end()
    return out

def _apply_circular_alpha_mask(img):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor

    if img is None or img.isNull():
        return img
    try:
        out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(QColor(0, 0, 0, 0))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addEllipse(QRectF(0, 0, out.width(), out.height()))
        p.setClipPath(clip)
        p.drawImage(0, 0, img)
        p.end()
        return out
    except Exception:
        return img

def _dominant_bg_from_image(img, *, width: int, height: int):
    from PySide6.QtGui import QColor
    from collections import Counter, defaultdict

    if img is None or img.isNull():
        return QColor(VIDEO_BG)
    w, h = img.width(), img.height()
    step = max(1, min(w, h) // 48)
    CHROMA_MIN = 22
    HUE_BINS = 18
    hue_samples = defaultdict(list)
    hue_score = Counter()
    hue_count = Counter()
    neutral_buckets = Counter()
    chroma_samples = 0
    neutral_samples = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = img.pixelColor(x, y)
            if c.lightness() < 14 or c.lightness() > 250:
                continue
            sat = c.saturation()
            if sat >= CHROMA_MIN:
                hv, _s, _v, _a = c.getHsv()
                if hv < 0:
                    key = (c.red() >> 3, c.green() >> 3, c.blue() >> 3)
                    neutral_buckets[key] += 1
                    neutral_samples += 1
                    continue
                bin_id = int(hv) % 360 // (360 // HUE_BINS)
                hue_score[bin_id] += max(24, sat)
                hue_count[bin_id] += 1
                hue_samples[bin_id].append((sat, c.red(), c.green(), c.blue()))
                chroma_samples += 1
            else:
                key = (c.red() >> 3, c.green() >> 3, c.blue() >> 3)
                neutral_buckets[key] += 1
                neutral_samples += 1

    total = chroma_samples + neutral_samples
    use_chroma = bool(hue_score) and (
        total == 0 or chroma_samples >= max(1, int(total * 0.10))
    )
    if use_chroma:
        ranked = hue_score.most_common()
        best_bin = None
        for bin_id, _sc in ranked:
            if hue_count[bin_id] >= max(2, int(chroma_samples * 0.08)):
                best_bin = bin_id
                break
        if best_bin is None:
            best_bin = ranked[0][0]
        samples = hue_samples.get(best_bin) or []
        if not samples:
            return QColor(VIDEO_BG)
        n = len(samples)
        ar = sum(t[1] for t in samples) / n
        ag = sum(t[2] for t in samples) / n
        ab = sum(t[3] for t in samples) / n
        color = QColor(int(ar), int(ag), int(ab))
    else:
        if not neutral_buckets:
            return QColor(VIDEO_BG)
        (qr, qg, qb), _ = neutral_buckets.most_common(1)[0]
        color = QColor(int((qr << 3) + 4), int((qg << 3) + 4), int((qb << 3) + 4))

    h_val, s, v, a = color.getHsv()
    if use_chroma:
        s = int(max(48, min(165, int(s * 0.90))))
        v = int(max(60, min(158, int(v * 0.86))))
    else:
        s = int(max(0, min(40, int(s * 0.5))))
        v = int(max(44, min(110, int(v * 0.62))))
    color.setHsv(h_val, s, v, 255)
    return color

def _paint_frame(
    img,
    *,
    levels: list[float] | None = None,
    width: int = 1280,
    height: int = 720,
    center_image=None,
    bg_color=None,
    peaks: list[float] | None = None,
    progress: float = 0.0,
    current_sec: float = 0.0,
    total_sec: float = 0.0,
    prev_levels: list[float] | None = None,
) -> list[float]:
    import math
    from PySide6.QtCore import Qt, QRectF, QPointF
    from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    except Exception:
        pass
    try:
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    except Exception:
        pass

    bg = bg_color if bg_color is not None else QColor(VIDEO_BG)
    p.fillRect(0, 0, width, height, bg)

    cx = width * 0.5
    cy = height * 0.5
    base_r = min(width, height) * 0.27
    max_ext = min(width, height) * 0.12
    n = 128
    if levels is None or len(levels) < 8:
        levels = [0.0] * n
    else:
        if len(levels) != n:
            src = list(levels)
            m = len(src)
            levels = []
            for i in range(n):
                pos = (i / n) * m
                i0 = int(pos) % m
                i1 = (i0 + 1) % m
                t = pos - int(pos)
                levels.append(src[i0] * (1.0 - t) + src[i1] * t)
        else:
            levels = list(levels)

    def _soft_amp(a: float) -> float:
        a = max(0.0, float(a))
        return math.tanh(1.15 * a)

    n2 = n * 2
    amps2 = []
    for i in range(n2):
        pos = (i / n2) * n
        i0 = int(pos) % n
        i1 = (i0 + 1) % n
        frac = pos - int(pos)
        u = frac * frac * (3.0 - 2.0 * frac)
        amps2.append(levels[i0] * (1.0 - u) + levels[i1] * u)

    baseline = max_ext * 0.04
    outer_pts = []
    for i, amp in enumerate(amps2):
        ang = (2.0 * math.pi * i / n2) - math.pi / 2.0
        r_out = base_r + baseline + max_ext * _soft_amp(amp)
        outer_pts.append(QPointF(cx + math.cos(ang) * r_out, cy + math.sin(ang) * r_out))

    outer_path = _closed_catmull_rom_path(outer_pts)
    inner_rect = QRectF(cx - base_r, cy - base_r, base_r * 2.0, base_r * 2.0)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(255, 255, 255, 170)))
    p.drawPath(outer_path)
    p.setBrush(QBrush(bg))
    p.drawEllipse(inner_rect)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
    p.drawPath(outer_path)

    if center_image is not None and not center_image.isNull():
        ir = base_r * 0.96
        dest = QRectF(cx - ir, cy - ir, ir * 2, ir * 2)
        if center_image.hasAlphaChannel():
            p.drawImage(dest, center_image)
        else:
            p.save()
            clip = QPainterPath()
            clip.addEllipse(dest)
            p.setClipPath(clip)
            p.drawImage(dest, center_image)
            p.restore()

    try:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setFamily("Sans Serif")
        font.setBold(False)
        font.setPixelSize(max(16, int(height * 0.034)))
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 175))
        margin_x = max(16, int(width * 0.025))
        margin_y = max(14, int(height * 0.022))
        p.drawText(
            QRectF(0, 0, width - margin_x, height - margin_y),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
            "@Mayotter",
        )
    except Exception:
        pass

    p.end()
    return levels

def write_mayotter_audio_frame(
    path: str | Path,
    *,
    duration_seconds: float = 0.0,
    width: int = 1280,
    height: int = 720,
    title: str = "",
    subtitle: str = "",
    source_audio: str | Path | None = None,
    center_image_path: str | Path | None = None,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PySide6.QtGui import QImage, QGuiApplication
        import sys
        if QGuiApplication.instance() is None:
            _app = QGuiApplication(sys.argv[:1])
    except Exception:
        _write_ppm_fallback(path.with_suffix(".ppm"), width, height)
        return path.with_suffix(".ppm")

    samples, rate, _dur = _load_mono_pcm(source_audio) if source_audio else ([], 44100, 0.0)
    levels, _info = _spectrum_bars_at_time(
        samples, rate, max(0.0, duration_seconds * 0.5), n_bars=128
    )
    levels = _visual_map_levels(levels, rms=float((_info or {}).get("rms", 0.0) or 0.0))
    center = None
    bg = None
    if center_image_path:
        try:
            raw = QImage(str(center_image_path))
            if raw.isNull():
                center = None
            else:
                bg = _dominant_bg_from_image(raw, width=width, height=height)
                center = _cover_square_image(raw, size=512, crop_x=crop_x, crop_y=crop_y, scale=scale, rotation=rotation)
                if center is not None and not center.isNull():
                    center = _apply_circular_alpha_mask(center)
        except Exception:
            center = None
    img = QImage(width, height, QImage.Format.Format_RGB32)
    _paint_frame(
        img,
        levels=levels,
        width=width,
        height=height,
        center_image=center,
        bg_color=bg,
    )
    out = path if path.suffix.lower() == ".png" else path.with_suffix(".png")
    img.save(str(out), "PNG")
    return out

def _pick_fps(samples, rate, dur, max_fps, width, height, center_img, bg_color) -> int:
    """PCの速さに合わせてフレームレートを決める。

    数フレームだけ実測し、変換全体が動画の長さ程度（最短20秒〜最長120秒）に収まる
    最大のフレームレートを選ぶ。遅いPCでも変換が極端に長くならないようにする。
    """
    import time
    from PySide6.QtGui import QImage

    try:
        img = QImage(width, height, QImage.Format.Format_RGB888)
        levels = None
        n_try = 5
        t_an = t_fr = 0.0
        for k in range(n_try):
            t0 = time.perf_counter()
            levels, _info = _spectrum_bars_at_time(
                samples, rate, dur * (k + 0.5) / n_try, n_bars=128, fft_size=2048
            )
            t1 = time.perf_counter()
            _paint_frame(
                img, levels=_visual_map_levels(levels), width=width, height=height,
                center_image=center_img, bg_color=bg_color,
            )
            bytes(img.constBits())
            t2 = time.perf_counter()
            t_an += t1 - t0
            t_fr += t2 - t1
        t_an /= n_try
        t_fr /= n_try
    except Exception:
        return min(max_fps, 15)

    budget = max(20.0, min(120.0, dur))
    for fps in (30, 24, 15, 12):
        if fps > max_fps:
            continue
        analysis_hz = 30.0 if fps >= 24 else 20.0
        # x264 のエンコード時間は描画とほぼ同程度として 1.5 倍で見積もる
        est = dur * (analysis_hz * t_an + fps * t_fr) * 1.5
        if est <= budget:
            return fps
    return 12


def generate_waveform_mp4(
    audio_path: str | Path,
    output_path: str | Path,
    *,
    duration_seconds: float | None = None,
    width: int = 1280,
    height: int = 720,
    fps: int = 15,
    title: str = "",
    progress_cb=None,
    cancel_flag=None,
    audio_filter: str | None = None,
    center_image_path: str | Path | None = None,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
) -> Path:
    from PySide6.QtGui import QImage, QGuiApplication
    import os
    import sys

    if QGuiApplication.instance() is None:
        _app = QGuiApplication(sys.argv[:1])

    from src.media.ffmpeg_util import (
        FFmpegError,
        run_ffmpeg_pipe_stdin,
        probe_duration_seconds,
    )

    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    analysis_wav = audio_path
    temp_wav = None
    if audio_path.suffix.lower() != ".wav":
        from src.media.media_converter import media_temp_dir
        import uuid

        temp_wav = media_temp_dir() / f"ana_{uuid.uuid4().hex[:10]}.wav"
        decoded = decode_audio_to_wav(audio_path, temp_wav)
        if decoded is not None:
            analysis_wav = decoded

    samples, rate, wav_dur = _load_mono_pcm(analysis_wav)
    samples = _level_for_analysis(samples, rate)

    dur = duration_seconds
    if dur is None or dur <= 0:
        dur = wav_dur or probe_duration_seconds(audio_path) or 1.0
    dur = max(0.2, float(dur))

    center_img = None
    bg_color = None
    if center_image_path:
        try:
            pth = Path(center_image_path)
            if pth.is_file():
                raw_img = QImage(str(pth))
                if raw_img.isNull():
                    center_img = None
                else:
                    bg_color = _dominant_bg_from_image(
                        raw_img, width=width, height=height
                    )
                    center_img = _cover_square_image(raw_img, size=512, crop_x=crop_x, crop_y=crop_y, scale=scale, rotation=rotation)
                    if center_img is not None and not center_img.isNull():
                        center_img = _apply_circular_alpha_mask(center_img)
        except Exception:
            center_img = None

    fps = _pick_fps(samples, rate, dur, fps, width, height, center_img, bg_color)
    n_frames = max(1, int(round(dur * fps)))
    analysis_hz = 30.0 if fps >= 24 else 20.0
    n_analysis = max(2, int(round(dur * analysis_hz)) + 1)
    spectrum_frames: list[list[float]] = []
    rms_frames: list[float] = []
    prev_levels: list[float] | None = None
    for ai in range(n_analysis):
        if cancel_flag is not None and cancel_flag():
            raise FFmpegError("変換がキャンセルされました")
        t_a = min(dur, ai / analysis_hz)
        levels, _info = _spectrum_bars_at_time(
            samples,
            rate,
            t_a,
            n_bars=128,
            fft_size=2048,
            prev=prev_levels,
        )
        prev_levels = levels
        spectrum_frames.append(levels)
        rms_frames.append(float((_info or {}).get("rms", 0.0) or 0.0))

    af_args: list[str] = []
    if audio_filter:
        af_args = ["-af", audio_filter]

    args = [
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-i", str(audio_path),
        *af_args,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast" if fps >= 30 and (os.cpu_count() or 1) >= 6 else "veryfast",
        "-crf", "18",
        "-tune", "animation",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = run_ffmpeg_pipe_stdin(args)
    assert proc.stdin is not None
    stderr_tail: list[bytes] = []
    frame_img = None
    try:
        for fi in range(n_frames):
            if cancel_flag is not None and cancel_flag():
                proc.kill()
                raise FFmpegError("変換がキャンセルされました")
            t = fi / float(fps)
            pos = min(len(spectrum_frames) - 1.001, t * analysis_hz)
            i0 = int(pos)
            i1 = min(i0 + 1, len(spectrum_frames) - 1)
            frac = pos - i0
            u = frac * frac * (3.0 - 2.0 * frac)
            a = spectrum_frames[i0]
            b = spectrum_frames[i1]
            levels = [a[j] * (1.0 - u) + b[j] * u for j in range(len(a))]
            rms0 = rms_frames[i0] if i0 < len(rms_frames) else 0.0
            rms1 = rms_frames[i1] if i1 < len(rms_frames) else rms0
            rms_i = rms0 * (1.0 - u) + rms1 * u
            levels = _visual_map_levels(levels, rms=rms_i)
            if frame_img is None:
                frame_img = QImage(width, height, QImage.Format.Format_RGB888)
            _paint_frame(
                frame_img,
                levels=levels,
                width=width,
                height=height,
                center_image=center_img,
                bg_color=bg_color,
            )
            ptr = frame_img.constBits()
            if ptr is None:
                raise FFmpegError("frame buffer unavailable")
            try:
                buf = bytes(ptr)
            except TypeError:
                buf = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(memoryview(ptr))
            expected = width * height * 3
            if len(buf) < expected:
                bpl = frame_img.bytesPerLine()
                rows = []
                mv = memoryview(buf) if not isinstance(buf, memoryview) else buf
                for y in range(height):
                    start = y * bpl
                    rows.append(bytes(mv[start : start + width * 3]))
                buf = b"".join(rows)
            else:
                buf = buf[:expected]
            proc.stdin.write(buf)
            if progress_cb is not None:
                progress_cb(min(0.95, (fi + 1) / n_frames))
        proc.stdin.close()
        if proc.stderr:
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_tail.append(chunk)
        rc = proc.wait(timeout=max(120, int(dur * 4) + 60))
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        if temp_wav is not None:
            try:
                temp_wav.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass

    from src.media.ffmpeg_util import format_process_rc, normalize_process_rc

    rc_s = normalize_process_rc(rc)
    if rc_s != 0:
        msg = b"".join(stderr_tail[-5:]).decode("utf-8", errors="replace")[:400]
        raise FFmpegError(
            f"waveform MP4 encode failed (code {format_process_rc(rc)}): {msg}"
        )

    if not output_path.is_file() or output_path.stat().st_size < 32:
        raise FFmpegError("MP4 の生成に失敗しました（出力が空です）")
    if progress_cb is not None:
        progress_cb(1.0)
    return output_path

def _write_ppm_fallback(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = bytes([11, 17, 31]) * width
    with path.open("wb") as f:
        f.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        for _ in range(height):
            f.write(row)

def make_recording_overlay(parent=None):
    import time
    from PySide6.QtCore import Qt, QRectF, QTimer
    from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QLinearGradient
    from PySide6.QtWidgets import QWidget

    class RecordingOverlay(QWidget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setFixedSize(340, 130)
            self._seconds = 0
            self._levels: list[float] = [0.05] * 96
            self._disp: list[float] = [0.05] * 96
            self._last_push: float | None = None
            self._push_interval = 0.05
            self._anim = QTimer(self)
            self._anim.setInterval(16)
            self._anim.timeout.connect(self._on_frame)
            self._mode = "recording"
            self._status_text = ""
            self._spin_angle = 0
            self._spin_timer: QTimer | None = None

        def set_elapsed(self, seconds: int) -> None:
            self._seconds = max(0, int(seconds))
            self.update()

        def set_processing(self, message: str = "音声を処理中…") -> None:
            self._mode = "processing"
            self._status_text = message or "音声を処理中…"
            if self._spin_timer is None:
                self._spin_timer = QTimer(self)
                self._spin_timer.setInterval(40)
                self._spin_timer.timeout.connect(self._tick_spin)
            if not self._spin_timer.isActive():
                self._spin_timer.start()
            self.update()

        def set_error(self, message: str) -> None:
            self._mode = "error"
            self._status_text = message or "音声の処理に失敗しました"
            self._stop_spin()
            self.update()

        def set_recording_mode(self) -> None:
            self._mode = "recording"
            self._status_text = ""
            self._stop_spin()
            self.update()

        def _tick_spin(self) -> None:
            self._spin_angle = (self._spin_angle + 12) % 360
            self.update()

        def _stop_spin(self) -> None:
            if self._spin_timer is not None and self._spin_timer.isActive():
                self._spin_timer.stop()

        def push_level(self, peak: float, rms: float = 0.0) -> None:
            v = max(0.0, min(1.0, float(peak)))
            r = max(0.0, min(1.0, float(rms))) if rms else 0.0
            raw = max(v, r * 1.15)
            if raw <= 1e-6:
                drawn = 0.05
            else:
                drawn = min(1.0, (raw ** 0.55) * 2.4)
                drawn = max(0.05, drawn)
            now = time.perf_counter()
            if self._last_push is not None:
                # 次の入力までの間隔を、横スクロールの補間に使う
                self._push_interval = max(0.02, min(0.2, now - self._last_push))
            self._last_push = now
            self._levels = self._levels[1:] + [drawn]
            self._disp = self._disp[1:] + [self._disp[-1]]

        def showEvent(self, event) -> None:
            super().showEvent(event)
            self._anim.start()

        def hideEvent(self, event) -> None:
            self._anim.stop()
            super().hideEvent(event)

        def _on_frame(self) -> None:
            # 表示値を目標値へ近づける（立ち上がりは速く、戻りはゆっくり）
            out = []
            for cur, tgt in zip(self._disp, self._levels):
                k = 0.55 if tgt > cur else 0.18
                out.append(cur + (tgt - cur) * k)
            self._disp = out
            self.update()

        def _wave_path(self, x0: float, width: float, cy: float, max_h: float):
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QPainterPath

            n = len(self._disp)
            dx = width / (n - 1)
            interval = max(0.02, self._push_interval)
            phase = 0.0
            if self._last_push is not None:
                phase = min(1.0, (time.perf_counter() - self._last_push) / interval)
            # 最新の点は右端に固定し、全体を1点ぶんずつ左へ滑らかに流す
            shift = (1.0 - phase) * dx
            xs = [x0 + i * dx - dx + shift for i in range(n)]
            amp = [max(1.2, max_h * v) for v in self._disp]
            top = [QPointF(x, cy - a) for x, a in zip(xs, amp)]
            bot = [QPointF(x, cy + a) for x, a in zip(xs, amp)]

            def _smooth(path, pts, first_move: bool):
                if first_move:
                    path.moveTo(pts[0])
                else:
                    path.lineTo(pts[0])
                for k in range(1, len(pts) - 1):
                    mid = QPointF((pts[k].x() + pts[k + 1].x()) / 2, (pts[k].y() + pts[k + 1].y()) / 2)
                    path.quadTo(pts[k], mid)
                path.lineTo(pts[-1])

            path = QPainterPath()
            _smooth(path, top, True)
            _smooth(path, list(reversed(bot)), False)
            path.closeSubpath()
            return path

        def paintEvent(self, event) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = self.width(), self.height()
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.0, _theme_qcolor("BG"))
            grad.setColorAt(1.0, _theme_qcolor("SURFACE"))
            p.setPen(QPen(_theme_qcolor("BORDER"), 1.5))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)

            margin_x = 18
            x0 = margin_x
            width = w - margin_x * 2
            cy = h * 0.42
            max_h = h * 0.34
            base = _theme_qcolor("ACCENT_STRONG")

            p.setPen(QPen(_theme_qcolor("BORDER", 150), 1))
            p.drawLine(int(x0), int(cy), int(x0 + width), int(cy))

            # 左端は透明にフェードし、新しい音ほどはっきり見せる
            fill = QLinearGradient(x0, 0, x0 + width, 0)
            for pos, a in ((0.0, 0), (0.25, 140), (1.0, 215)):
                c = QColor(base)
                c.setAlpha(a)
                fill.setColorAt(pos, c)
            edge = QLinearGradient(x0, 0, x0 + width, 0)
            for pos, a in ((0.0, 0), (0.25, 200), (1.0, 255)):
                c = QColor(base)
                c.setAlpha(a)
                edge.setColorAt(pos, c)
            path = self._wave_path(x0, width, cy, max_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(path)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QBrush(edge), 1.4))
            p.drawPath(path)

            font2 = QFont()
            font2.setPixelSize(13)
            font2.setBold(True)
            p.setFont(font2)
            if self._mode == "processing":
                cx, cy = w / 2 - 70, h - 20
                p.setPen(QPen(_theme_qcolor("ACCENT_STRONG"), 2.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(cx - 7, cy - 7, 14, 14), int(-self._spin_angle * 16), 270 * 16)
                p.setPen(_theme_qcolor("TEXT"))
                p.drawText(
                    QRectF(0, h - 30, w, 22),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    self._status_text or "音声を処理中…",
                )
            elif self._mode == "error":
                p.setPen(_theme_qcolor("DANGER"))
                p.drawText(
                    QRectF(12, h - 30, w - 24, 22),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    self._status_text or "音声の処理に失敗しました",
                )
            else:
                m, s = divmod(self._seconds, 60)
                p.setBrush(_theme_qcolor("DANGER"))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(w / 2 - 56, h - 26, 9, 9))
                p.setPen(_theme_qcolor("TEXT"))
                p.drawText(
                    QRectF(0, h - 30, w, 22),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    f"REC  {m:02d}:{s:02d}",
                )
            p.end()

    return RecordingOverlay(parent)
