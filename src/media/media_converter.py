
from __future__ import annotations
from src.core.i18n import tr

import os
import tempfile
import uuid
from pathlib import Path

from src.media.ffmpeg_util import (
    FFmpegError,
    resampler_filter,
    TARGET_I,
    TARGET_TP,
    analyze_dynamics,
    find_ffmpeg,
    DECLICK_FILTER,
    loudness_measured_usable,
    measure_loudness,
    plan_loudness_filter,
    speech_pause_expander_filter,
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

def save_recording_wav(source: Path, directory: Path) -> Path:
    import shutil
    from datetime import datetime

    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = directory / f"voice_{stamp}_{source.stem}_{uuid.uuid4().hex[:8]}.wav"
    try:
        os.link(source, dest)
    except FileExistsError:
        raise
    except OSError:
        # 別ドライブ等ではハードリンクを作れない。GUI スレッド外で元のバイト列を保存する。
        with dest.open("xb") as target:
            try:
                with source.open("rb") as original:
                    shutil.copyfileobj(original, target)
            except BaseException:
                target.close()
                dest.unlink()
                raise
    return dest


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
    declick: bool = False,
    denoise: bool = False,
    denoise_strength: str = "strong",
) -> Path:
    """音声を投稿用 MP4（AAC 192 kbps・映像は波形）にする。

    中間処理は PCM / 32bit float のまま行い、不可逆エンコードは最後の 1 回だけ。
    denoise=True のときは AI ノイズ除去（DeepFilterNet3、別プロセス、48 kHz）を通した音声で作る。元の音声は変更しない。
    ノイズ除去に失敗したら DenoiseError を送出する（ノイズ未除去の音声を黙って使わない）。
    """
    src = Path(source_path).resolve()
    _media_debug(f"audio_file_to_mp4 enter src={src}")
    if not src.is_file():
        raise ValueError(tr('音声ファイルが見つかりません: {v0}', v0=src))
    if not is_audio_path(src):
        raise ValueError(tr('未対応の音声形式です: {v0}', v0=src.suffix))

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
            tr('音声が長すぎます（{v0}秒）。X投稿向け上限を超えています。', v0=int(duration))
        )

    enhanced: Path | None = None
    guard_info: dict | None = None
    reference_dynamics: dict | None = None
    silence_stabilized = False
    try:
        if denoise:
            # 無音判定とゲート閾値は、AI処理で変化する前の録音も参照する。
            guard_info = wav_peak_rms(src) if src.suffix.lower() == ".wav" else {}
            reference_dynamics = analyze_dynamics(
                src, pre_filter=DECLICK_FILTER if declick else None
            ) or None
            from src.media.denoise import DenoiseCancelled, run_denoise_subprocess
            enhanced = media_temp_dir() / f"dn_{uuid.uuid4().hex[:12]}.wav"
            try:
                stats = run_denoise_subprocess(
                    src, enhanced, strength=denoise_strength, declick=declick,
                    duration=duration,
                    progress_cb=(lambda f: progress_cb(0.6 * float(f))) if progress_cb else None,
                    cancel_flag=cancel_flag,
                )
            except DenoiseCancelled:
                raise FFmpegError(tr('変換がキャンセルされました')) from None
            _media_debug(f"denoise done stats={stats}")
            try:
                from src.media.silence_stabilizer import stabilize_denoised_silence
                silence_stabilized = stabilize_denoised_silence(src, enhanced)
            except (OSError, ValueError, RuntimeError) as exc:
                # 元のAI出力を壊さず、従来のゲートへフォールバックする。
                _media_debug(f"silence_stabilizer skipped: {exc!r}")
            _media_debug(f"silence_stabilized={silence_stabilized}")
            src = enhanced
            declick = False  # ノイズ除去の前段（48 kHz 化の前）で適用済み
        return _encode_post_mp4(
            src, out, duration=duration,
            progress_cb=(lambda f: progress_cb(0.6 + 0.4 * float(f))) if (progress_cb and denoise) else progress_cb,
            cancel_flag=cancel_flag, width=width, height=height, normalize=normalize,
            center_image_path=center_image_path, crop_x=crop_x, crop_y=crop_y, scale=scale,
            rotation=rotation, declick=declick, guard_info=guard_info,
            reference_dynamics=reference_dynamics, silence_stabilized=silence_stabilized,
        )
    finally:
        if enhanced is not None:
            try:
                if enhanced.is_file():
                    enhanced.unlink()
            except OSError:
                pass


def _source_rate(path: Path, peak_info: dict) -> int:
    try:
        rate = int(peak_info.get("rate") or 0)
    except (TypeError, ValueError):
        rate = 0
    if rate <= 0 and path.suffix.lower() == ".wav":
        try:
            with open(path, "rb") as fh:
                head = fh.read(64)
            if head[:4] == b"RIFF" and head[12:16] == b"fmt ":
                import struct
                rate = struct.unpack("<I", head[24:28])[0]
        except OSError:
            rate = 0
    return rate


def _encode_post_mp4(
    src: Path,
    out: Path,
    *,
    duration: float,
    progress_cb,
    cancel_flag,
    width: int,
    height: int,
    normalize: bool,
    center_image_path,
    crop_x: float,
    crop_y: float,
    scale: float,
    rotation: float,
    declick: bool,
    guard_info: dict | None = None,
    reference_dynamics: dict | None = None,
    silence_stabilized: bool = False,
) -> Path:
    peak_info = wav_peak_rms(src) if src.suffix.lower() == ".wav" else {}
    # 44.1 / 48 kHz の録音はそのままの周波数でエンコードし、不要なリサンプリングをしない
    rate = _source_rate(src, peak_info)
    out_rate = rate if rate in (44100, 48000) else 44100
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
        # 測定も変換と同じ入力（declick 後）で行う
        pre = DECLICK_FILTER if declick else None
        measured = measure_loudness(src, pre_filter=pre)
        dynamics = analyze_dynamics(src, pre_filter=pre)
        plan = plan_loudness_filter(
            measured if measured else None,
            peak_info=(peak_info if guard_info is None else guard_info) or None,
            dynamics=dynamics,
        )
        af = plan.get("af")
        pause_filter = None if silence_stabilized else speech_pause_expander_filter(
            dynamics, plan, reference_dynamics=reference_dynamics
        )
        if pause_filter:
            af = f"{pause_filter},{af}" if af else pause_filter
        _media_debug(f"pause_expander={'ON' if pause_filter else 'OFF'}")
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
            f"gain_class={plan.get('gain_class')} spread_db={plan.get('spread_db')} "
            f"measured_usable={loudness_measured_usable(measured) if measured else False}"
        )
    else:
        _media_debug("normalize=OFF")

    if declick:
        af = f"{DECLICK_FILTER},{af}" if af else DECLICK_FILTER
    if af or rate != out_rate:
        # リミッター用の 192 kHz 化や入力の周波数から、高品質リサンプラーで出力周波数へ戻す
        af = f"{af},{resampler_filter(out_rate)}" if af else resampler_filter(out_rate)

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
            fps=30,
            title="",
            progress_cb=_prog,
            cancel_flag=cancel_flag,
            audio_filter=af,
            center_image_path=center_image_path,
            crop_x=crop_x,
            crop_y=crop_y,
            scale=scale,
            rotation=rotation,
            audio_rate=out_rate,
        )
    except Exception as wave_exc:
        _media_debug(f"waveform stream failed → stillimage fallback ({wave_exc!r})")
        fb_af = af
        if fb_af and "measured_I" in fb_af:
            if not loudness_measured_usable(measured):
                fb_af = None  # 解析失敗時に無音ノイズを増幅しない
                if declick:
                    fb_af = f"{DECLICK_FILTER},{fb_af}"
                _media_debug("fallback af sanitized to no normalization")
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
                    str(out_rate),
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
        raise FFmpegError(tr('MP4 の生成に失敗しました（出力が空です）'))
    if out.stat().st_size > MAX_OUTPUT_BYTES:
        try:
            out.unlink()
        except OSError:
            pass
        raise ValueError(tr('生成MP4が大きすぎます'))
    if duration > 1.0:
        out_dur = probe_duration_seconds(out) or 0.0
        if out_dur < duration - max(0.5, duration * 0.02):
            try:
                out.unlink()
            except OSError:
                pass
            raise FFmpegError(
                tr('変換後の音声が短くなりました（{v0:.1f}秒 / 元 {v1:.1f}秒）', v0=out_dur, v1=duration))

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
            declick: bool = False,
            denoise: bool = False,
            denoise_strength: str = "strong",
            recording_wav_dir: str | None = None,
        ) -> None:
            super().__init__()
            self.denoise = bool(denoise)
            self.denoise_strength = denoise_strength
            self.recording_wav_dir = recording_wav_dir
            self.recording_wav_path: Path | None = None
            self.wav_save_error = ""
            # 失敗の種類（"denoise" ならノイズ除去の失敗。画面側で「ノイズ除去なしで変換」を提案する）
            self.error_kind = ""
            self.source_path = source_path
            self.output_path = output_path
            self.normalize = bool(normalize)
            self.center_image_path = center_image_path
            self.crop_x = float(crop_x or 0.0)
            self.crop_y = float(crop_y or 0.0)
            self.scale = float(scale or 1.0)
            self.rotation = float(rotation or 0.0)
            self.declick = bool(declick)
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
            if self.recording_wav_dir:
                try:
                    self.recording_wav_path = save_recording_wav(
                        Path(self.source_path), Path(self.recording_wav_dir))
                except OSError as exc:
                    self.wav_save_error = str(exc)
                    _wlog(f"original WAV save failed; keeping temporary source: {exc}")
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
                    declick=self.declick,
                    denoise=self.denoise,
                    denoise_strength=self.denoise_strength,
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
                    from src.media.denoise import DenoiseError
                    if isinstance(exc, DenoiseError):
                        self.error_kind = "denoise"
                except Exception:
                    pass
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
    declick: bool = False,
    denoise: bool = False,
    denoise_strength: str = "strong",
    recording_wav_dir: str | None = None,
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
        declick=declick,
        denoise=denoise,
        denoise_strength=denoise_strength,
        recording_wav_dir=recording_wav_dir,
    )
    worker.setAutoDelete(False)
    if start:
        QThreadPool.globalInstance().start(worker)
    return worker

def MediaConversionWorker(*args, **kwargs):
    cls, _ = _qt_worker_types()
    return cls(*args, **kwargs)
