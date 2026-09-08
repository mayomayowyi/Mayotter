
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from src.media.ffmpeg_util import (
    FFmpegError,
    FFmpegNotFoundError,
    TARGET_I,
    TARGET_TP,
    find_ffmpeg,
    loudnorm_filter_string,
    loudness_measured_usable,
    measure_loudness,
    plan_loudness_filter,
    probe_duration_seconds,
    run_ffmpeg,
    wav_peak_rms,
)
from src.media.visual import generate_waveform_mp4, write_mayotter_audio_frame

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"}
)

MAX_DURATION_SECONDS = 140 * 60
MAX_OUTPUT_BYTES = 512 * 1024 * 1024

def is_audio_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS

def media_temp_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "Mayotter" / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root

def _unique_mp4_path(stem: str = "audio") -> Path:
    safe = "".join(c for c in stem if c.isalnum() or c in ("-", "_"))[:40] or "audio"
    return media_temp_dir() / f"{safe}_{uuid.uuid4().hex[:12]}.mp4"

def _media_debug(msg: str) -> None:
    if os.environ.get("MAYOTTER_MEDIA_DEBUG"):
        import sys

        print(f"[MAYOTTER MEDIA] {msg}", file=sys.stderr, flush=True)

def audio_file_to_mp4(
    source_path: str | Path,
    output_path: str | Path | None = None,
    *,
    progress_cb=None,
    cancel_flag=None,
    width: int = 1280,
    height: int = 720,
    normalize: bool = True,
    center_image_path: str | Path | None = None,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
) -> Path:
    src = Path(source_path).resolve()
    _media_debug(f"audio_file_to_mp4 enter src={src}")
    if not src.is_file():
        raise ValueError(f"音声ファイルが見つかりません: {src}")
    if not is_audio_path(src):
        raise ValueError(f"未対応の音声形式です: {src.suffix}")

    out = Path(output_path).resolve() if output_path else _unique_mp4_path(src.stem)
    if output_path:
        out.parent.mkdir(parents=True, exist_ok=True)

    try:
        ff = find_ffmpeg()
        _media_debug(f"ffmpeg_found path={ff}")
    except Exception as ff_exc:
        _media_debug(f"ffmpeg_find_failed {ff_exc!r}")
        raise

    duration = probe_duration_seconds(src) or 0.0
    if duration > MAX_DURATION_SECONDS:
        raise ValueError(
            f"音声が長すぎます（{int(duration)}秒）。X投稿向け上限を超えています。"
        )

    peak_info = wav_peak_rms(src) if src.suffix.lower() == ".wav" else {}
    if peak_info:
        _media_debug(
            f"wav_peak={peak_info.get('wav_peak', 0):.4f} "
            f"wav_rms={peak_info.get('wav_rms', 0):.4f} "
            f"frames={peak_info.get('frames')} "
            f"channels={peak_info.get('channels')} "
            f"rate={peak_info.get('rate')} "
            f"duration_sec={peak_info.get('duration_sec')} "
            f"sample_count={peak_info.get('sample_count')} "
            f"pcm_min={peak_info.get('pcm_min')} pcm_max={peak_info.get('pcm_max')}"
        )

    measured: dict = {}
    af: str | None = None
    plan: dict = {}
    if normalize:
        if progress_cb:
            progress_cb(0.02)
        measured = measure_loudness(src)
        plan = plan_loudness_filter(measured if measured else None, peak_info=peak_info or None)
        af = plan.get("af")
        if af is None and plan.get("mode") == "single_pass_measure_failed":
            af = loudnorm_filter_string(None)
            plan["af"] = af
        _media_debug(
            f"input_lufs={plan.get('input_lufs')} "
            f"target_lufs={plan.get('target_i')} "
            f"normalization_gain={plan.get('applied_gain')} "
            f"estimated_gain={plan.get('estimated_gain')} "
            f"gain_limited={plan.get('gain_limited')} "
            f"input_tp={plan.get('input_tp')} "
            f"true_peak_ceiling={TARGET_TP} "
            f"input_rms={plan.get('input_rms')} "
            f"input_peak={plan.get('input_peak')} "
            f"normalization_mode={plan.get('mode')} "
            f"measured_usable={loudness_measured_usable(measured) if measured else False}"
        )
    else:
        _media_debug("normalize=OFF")

    def _prog(f: float) -> None:
        if progress_cb:
            progress_cb(0.05 + 0.95 * float(f))

    try:
        _media_debug(f"ffmpeg_encode_start out={out}")
        generate_waveform_mp4(
            src,
            out,
            duration_seconds=duration if duration > 0 else None,
            width=width,
            height=height,
            fps=15,
            title="",
            progress_cb=_prog,
            cancel_flag=cancel_flag,
            audio_filter=af,
            center_image_path=center_image_path,
            crop_x=crop_x,
            crop_y=crop_y,
            scale=scale,
            rotation=rotation,
        )
    except Exception as wave_exc:
        _media_debug(f"waveform stream failed → stillimage fallback ({wave_exc!r})")
        fb_af = af
        if fb_af and "measured_I" in fb_af:
            if not loudness_measured_usable(measured):
                fb_af = loudnorm_filter_string(None)
                _media_debug("fallback af sanitized to single-pass loudnorm")
        visual = media_temp_dir() / f"vis_{uuid.uuid4().hex[:10]}.png"
        try:
            visual = write_mayotter_audio_frame(
                visual,
                duration_seconds=duration,
                width=width,
                height=height,
                subtitle="",
                title="",
                source_audio=src,
                center_image_path=center_image_path,
            )
            args = [
                "-loop",
                "1",
                "-i",
                str(visual),
                "-i",
                str(src),
            ]
            if fb_af:
                args.extend(["-af", fb_af])
            args.extend(
                [
                    "-c:v",
                    "libx264",
                    "-tune",
                    "stillimage",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "44100",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(out),
                ]
            )
            run_ffmpeg(
                args,
                timeout=max(120.0, (duration or 60) * 4 + 60),
                progress_cb=progress_cb,
                duration_hint=duration if duration > 0 else None,
                cancel_flag=cancel_flag,
            )
        finally:
            try:
                if visual.is_file():
                    visual.unlink()
            except OSError:
                pass

    if not out.is_file() or out.stat().st_size < 32:
        raise FFmpegError("MP4 の生成に失敗しました（出力が空です）")
    if out.stat().st_size > MAX_OUTPUT_BYTES:
        try:
            out.unlink()
        except OSError:
            pass
        raise ValueError("生成MP4が大きすぎます")

    if os.environ.get("MAYOTTER_MEDIA_DEBUG"):
        try:
            out_m = measure_loudness(out)
            if out_m:
                _media_debug(
                    f"output_lufs={out_m.get('input_i')} "
                    f"true_peak={out_m.get('input_tp')} "
                    f"target_lufs={plan.get('target_i', TARGET_I) if plan else TARGET_I} "
                    f"normalization_gain={plan.get('applied_gain') if plan else None}"
                )
        except Exception:
            pass
    _media_debug(f"mp4_created={out}")
    return out

def cleanup_temp_media(path: str | Path | None) -> None:
    if not path:
        return
    try:
        p = Path(path).resolve()
        root = media_temp_dir().resolve()
        if root in p.parents or p.parent == root:
            if p.is_file():
                p.unlink()
    except OSError:
        pass

def _qt_worker_types():
    from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

    class _ConversionSignals(QObject):
        progress = Signal(float)
        finished = Signal(str, str)
        failed = Signal(str, str)

    class MediaConversionWorker(QRunnable):

        def __init__(
            self,
            source_path: str,
            output_path: str | None = None,
            *,
            normalize: bool = True,
            center_image_path: str | None = None,
            crop_x: float = 0.0,
            crop_y: float = 0.0,
            scale: float = 1.0,
            rotation: float = 0.0,
        ) -> None:
            super().__init__()
            self.source_path = source_path
            self.output_path = output_path
            self.normalize = bool(normalize)
            self.center_image_path = center_image_path
            self.crop_x = float(crop_x or 0.0)
            self.crop_y = float(crop_y or 0.0)
            self.scale = float(scale or 1.0)
            self.rotation = float(rotation or 0.0)
            self.signals = _ConversionSignals()
            self._cancel = False
            self.setAutoDelete(True)

        def cancel(self) -> None:
            self._cancel = True

        @Slot()
        def run(self) -> None:
            def _wlog(msg: str) -> None:
                try:
                    import sys
                    print(f"[DND_AUDIO] worker {msg}", file=sys.stderr, flush=True)
                except Exception:
                    pass
                try:
                    _media_debug(f"worker {msg}")
                except Exception:
                    pass

            _wlog(f"run_start src={self.source_path!r}")
            try:
                _wlog("calling audio_file_to_mp4")
                out = audio_file_to_mp4(
                    self.source_path,
                    self.output_path,
                    progress_cb=lambda f: self.signals.progress.emit(float(f)),
                    cancel_flag=lambda: self._cancel,
                    normalize=self.normalize,
                    center_image_path=self.center_image_path,
                    crop_x=self.crop_x,
                    crop_y=self.crop_y,
                    scale=self.scale,
                    rotation=self.rotation,
                )
                try:
                    from pathlib import Path as _P
                    exists = _P(out).is_file()
                    size = _P(out).stat().st_size if exists else -1
                except Exception:
                    exists, size = False, -1
                _wlog(
                    f"audio_file_to_mp4 returned out={out!r} exists={exists} size={size}"
                )
                self.signals.finished.emit(self.source_path, str(out))
                _wlog("finished signal emitted")
            except Exception as exc:
                _wlog(f"run_exception {type(exc).__name__}: {exc}")
                try:
                    self.signals.failed.emit(self.source_path, str(exc))
                    _wlog("failed signal emitted")
                except Exception as emit_exc:
                    _wlog(f"failed_emit_exception {emit_exc!r}")

    return MediaConversionWorker, QThreadPool

def start_conversion(
    source_path: str,
    output_path: str | None = None,
    *,
    normalize: bool = True,
    center_image_path: str | None = None,
    crop_x: float = 0.0,
    crop_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    start: bool = True,
):
    MediaConversionWorker, QThreadPool = _qt_worker_types()
    worker = MediaConversionWorker(
        source_path,
        output_path,
        normalize=normalize,
        center_image_path=center_image_path,
        crop_x=crop_x,
        crop_y=crop_y,
        scale=scale,
        rotation=rotation,
    )
    worker.setAutoDelete(False)
    if start:
        QThreadPool.globalInstance().start(worker)
    return worker

def MediaConversionWorker(*args, **kwargs):
    cls, _ = _qt_worker_types()
    return cls(*args, **kwargs)
