
from __future__ import annotations

import os
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QIODevice, Signal, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices, QAudio

from src.media.media_converter import media_temp_dir
import uuid

def _rec_log(msg: str) -> None:
    try:
        from src.media.debug_log import media_debug
        media_debug("REC", msg)
    except Exception:
        pass

def _sample_format_name(fmt: QAudioFormat.SampleFormat) -> str:
    try:
        mapping = {
            QAudioFormat.SampleFormat.Unknown: "Unknown",
            QAudioFormat.SampleFormat.UInt8: "UInt8",
            QAudioFormat.SampleFormat.Int16: "Int16",
            QAudioFormat.SampleFormat.Int32: "Int32",
            QAudioFormat.SampleFormat.Float: "Float",
        }
        return mapping.get(fmt, str(fmt))
    except Exception:
        return str(fmt)

def _qt_enum_members(enum_cls):
    out = {}
    if enum_cls is None:
        return out
    try:
        for name in ("ActiveState", "SuspendedState", "StoppedState", "IdleState",
                     "NoError", "OpenError", "IOError", "UnderrunError", "FatalError"):
            if hasattr(enum_cls, name):
                out[getattr(enum_cls, name)] = name
    except Exception:
        pass
    return out

def _state_name(state) -> str:
    try:
        mapping = {}
        mapping.update(_qt_enum_members(getattr(QAudio, "State", None)))
        for name in ("ActiveState", "SuspendedState", "StoppedState", "IdleState"):
            if hasattr(QAudio, name):
                mapping[getattr(QAudio, name)] = name
        return mapping.get(state, str(state))
    except Exception:
        return str(state)

def _error_name(err) -> str:
    try:
        mapping = {}
        mapping.update(_qt_enum_members(getattr(QAudio, "Error", None)))
        for name in ("NoError", "OpenError", "IOError", "UnderrunError", "FatalError"):
            if hasattr(QAudio, name):
                mapping[getattr(QAudio, name)] = name
        return mapping.get(err, str(err))
    except Exception:
        return str(err)

def _no_error_value():
    try:
        if hasattr(QAudio, "Error") and hasattr(QAudio.Error, "NoError"):
            return QAudio.Error.NoError
        if hasattr(QAudio, "NoError"):
            return QAudio.NoError
    except Exception:
        pass
    return 0

def _is_no_error(err) -> bool:
    if err is None:
        return True
    try:
        if err == _no_error_value():
            return True
    except Exception:
        pass
    try:
        if int(err) == 0:
            return True
    except Exception:
        pass
    name = _error_name(err)
    return name in ("NoError", "Error.NoError", "0") or str(err).endswith("NoError")

def _is_fatal_error(err) -> bool:
    if _is_no_error(err):
        return False
    name = _error_name(err)
    if name in ("UnderrunError", "Error.UnderrunError"):
        return False
    return True

class AudioRecorder(QObject):

    started = Signal()
    stopped = Signal(str)
    failed = Signal(str)
    elapsed = Signal(int)
    level = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._io: QIODevice | None = None
        self._path: Path | None = None
        self._wave: wave.Wave_write | None = None
        self._seconds = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        self._active = False
        self._sample_format = QAudioFormat.SampleFormat.Int16
        self._channels = 1
        self._rate = 44100
        self._bytes_written = 0
        self._ready_count = 0
        self._pcm_watch = QTimer(self)
        self._pcm_watch.setSingleShot(True)
        self._pcm_watch.setInterval(2500)
        self._pcm_watch.timeout.connect(self._on_pcm_timeout)
        self._last_level_emit_ms = 0
        self._level_min_interval_ms = 50
        self._t0_mono: float | None = None
        self._last_ready_mono: float | None = None
        self._ready_interval_sum_ms = 0.0
        self._ready_interval_max_ms = 0.0
        self._ready_interval_count = 0
        self._ready_delay_count = 0
        self._ready_critical_count = 0
        self._bytes_per_read_min = 0
        self._bytes_per_read_max = 0
        self._buffer_size_requested = 0
        self._buffer_size_actual = 0
        self._bytes_per_sample = 2
        self._capture_bytes_per_sample = 2
        self._ready_delay_warn_ms = 100.0
        self._ready_delay_crit_ms = 250.0
        self._crit_log_budget = 8

    @property
    def is_recording(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            _rec_log("start ignored (already active)")
            return
        try:
            devices = QMediaDevices.audioInputs()
            _rec_log(f"audioInputs count={len(devices)}")
            for i, d in enumerate(devices):
                try:
                    _rec_log(
                        f"input_device[{i}] id={d.id()!r} description={d.description()!r}"
                    )
                except Exception:
                    pass

            device = QMediaDevices.defaultAudioInput()
            if device.isNull():
                _rec_log("default_input=null")
                self.failed.emit("録音デバイスが見つかりません")
                return

            try:
                desc = device.description()
                dev_id = device.id()
            except Exception:
                desc, dev_id = "?", "?"
            _rec_log(f"default_input={desc!r}")
            _rec_log(f"device_description={desc!r}")
            _rec_log(f"device_id={dev_id!r}")

            fmt = QAudioFormat()
            fmt.setSampleRate(44100)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            if not device.isFormatSupported(fmt):
                _rec_log("requested 44100/mono/Int16 not supported → preferredFormat")
                fmt = device.preferredFormat()
                if fmt.sampleFormat() not in (
                    QAudioFormat.SampleFormat.Int16,
                    QAudioFormat.SampleFormat.UInt8,
                    QAudioFormat.SampleFormat.Int32,
                    QAudioFormat.SampleFormat.Float,
                ):
                    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                if fmt.channelCount() < 1:
                    fmt.setChannelCount(1)
                if fmt.sampleRate() < 8000:
                    fmt.setSampleRate(44100)

            self._sample_format = fmt.sampleFormat()
            self._channels = max(1, fmt.channelCount())
            self._rate = fmt.sampleRate()
            _rec_log(
                f"QAudioFormat sampleRate={self._rate} "
                f"channelCount={self._channels} "
                f"sampleFormat={_sample_format_name(self._sample_format)}"
            )

            self._source = QAudioSource(device, fmt, self)
            try:
                sf = self._sample_format
                if sf == QAudioFormat.SampleFormat.Float or sf == QAudioFormat.SampleFormat.Int32:
                    self._capture_bytes_per_sample = 4
                elif sf == QAudioFormat.SampleFormat.UInt8:
                    self._capture_bytes_per_sample = 1
                else:
                    self._capture_bytes_per_sample = 2
            except Exception:
                self._capture_bytes_per_sample = 2
            self._bytes_per_sample = 2
            try:
                bytes_per_sec = max(1, self._rate * self._channels * 2)
                req_buf = max(16384, bytes_per_sec // 2)
                self._buffer_size_requested = req_buf
                self._source.setBufferSize(req_buf)
                try:
                    self._buffer_size_actual = int(self._source.bufferSize())
                except Exception:
                    self._buffer_size_actual = 0
                _rec_log(
                    f"buffer_size_requested={req_buf} "
                    f"buffer_size_actual={self._buffer_size_actual} "
                    f"capture_bytes_per_sample={self._capture_bytes_per_sample} "
                    f"wav_bytes_per_sample={self._bytes_per_sample}"
                )
            except Exception as exc:
                _rec_log(f"setBufferSize skipped: {exc}")

            try:
                self._source.stateChanged.connect(self._on_state_changed)
            except Exception:
                pass

            self._path = media_temp_dir() / f"rec_{uuid.uuid4().hex[:12]}.wav"
            self._wave = wave.open(str(self._path), "wb")
            self._wave.setnchannels(self._channels)
            self._wave.setsampwidth(2)
            self._wave.setframerate(self._rate)

            self._bytes_written = 0
            self._ready_count = 0
            self._last_ready_mono = None
            self._ready_interval_sum_ms = 0.0
            self._ready_interval_max_ms = 0.0
            self._ready_interval_count = 0
            self._ready_delay_count = 0
            self._ready_critical_count = 0
            self._bytes_per_read_min = 0
            self._bytes_per_read_max = 0
            self._crit_log_budget = 8

            self._io = self._source.start()
            err = self._source.error()
            state = self._source.state()
            _rec_log(
                f"after start: state={_state_name(state)} error={_error_name(err)} "
                f"io={'ok' if self._io is not None else 'None'}"
            )

            if self._io is None:
                self.failed.emit("録音を開始できませんでした（入力ストリームなし）")
                self._cleanup_partial()
                return

            if not _is_no_error(err):
                self.failed.emit(f"録音を開始できませんでした（{_error_name(err)}）")
                self._cleanup_partial()
                return

            self._io.readyRead.connect(self._on_ready_read)

            self._seconds = 0
            self._active = True
            try:
                import time as _time
                self._t0_mono = _time.monotonic()
            except Exception:
                self._t0_mono = None
            self._timer.start()
            self._pcm_watch.start()
            _rec_log(
                f"start_result=ok initial_state={_state_name(state)} "
                f"initial_error={_error_name(err)} waiting_for_audio=true"
            )
            self.started.emit()
            self.elapsed.emit(0)
            self.level.emit(0.0, 0.0)
        except Exception as exc:
            _rec_log(f"start exception: {exc!r}")
            self._cleanup_partial()
            self.failed.emit(f"録音を開始できませんでした: {exc}")

    def stop(self) -> None:
        if not self._active:
            _rec_log("stop ignored (not active)")
            return
        self._active = False
        self._timer.stop()
        self._pcm_watch.stop()
        path = self._path
        try:
            if self._source is not None:
                self._source.stop()
        except Exception as exc:
            _rec_log(f"source.stop: {exc}")
        try:
            if self._io is not None and self._io.bytesAvailable() > 0:
                self._on_ready_read()
        except Exception:
            pass
        try:
            if self._wave is not None:
                self._wave.close()
        except Exception as exc:
            _rec_log(f"wave.close: {exc}")
        self._wave = None
        self._source = None
        self._io = None
        self._path = None
        size = 0
        if path is not None and path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
        pcm_sec = None
        wall_sec = None
        sample_count = None
        try:
            if path is not None and path.is_file() and self._rate > 0 and self._channels > 0:
                frame_bytes = max(1, self._channels * 2)
                sample_count = self._bytes_written // frame_bytes
                pcm_sec = self._bytes_written / float(frame_bytes) / float(self._rate)
            if self._t0_mono is not None:
                import time as _time
                wall_sec = max(0.0, _time.monotonic() - float(self._t0_mono))
        except Exception:
            pass
        delta = None
        try:
            if pcm_sec is not None and wall_sec is not None:
                delta = pcm_sec - wall_sec
        except Exception:
            pass
        mean_interval = None
        try:
            if self._ready_interval_count > 0:
                mean_interval = self._ready_interval_sum_ms / float(self._ready_interval_count)
        except Exception:
            pass
        _rec_log(
            f"stopped wav_path={path} wav_size={size} bytes_written={self._bytes_written} "
            f"ready_count={self._ready_count} rate={self._rate} channels={self._channels} "
            f"sample_format={_sample_format_name(self._sample_format)} "
            f"capture_bytes_per_sample={self._capture_bytes_per_sample} "
            f"wav_bytes_per_sample={self._bytes_per_sample} "
            f"buffer_requested={self._buffer_size_requested} "
            f"buffer_actual={self._buffer_size_actual} "
            f"sample_count={sample_count!r} "
            f"pcm_sec={pcm_sec!r} wall_sec={wall_sec!r} pcm_minus_wall={delta!r}"
        )
        _rec_log(
            f"readyRead_stats count={self._ready_count} "
            f"interval_mean_ms={mean_interval!r} interval_max_ms={self._ready_interval_max_ms!r} "
            f"delay_count_ge_{int(self._ready_delay_warn_ms)}ms={self._ready_delay_count} "
            f"critical_count_ge_{int(self._ready_delay_crit_ms)}ms={self._ready_critical_count} "
            f"read_bytes_min={self._bytes_per_read_min} read_bytes_max={self._bytes_per_read_max}"
        )
        if delta is not None and abs(float(delta)) >= 0.05:
            _rec_log(
                f"duration_MISMATCH pcm_minus_wall={delta:.4f}s "
                f"(negative ≈ PCM shorter than wall → possible capture drop)"
            )
        if self._ready_critical_count > 0 or self._ready_delay_count > 0:
            _rec_log(
                f"readyRead_DELAY_SUMMARY delays={self._ready_delay_count} "
                f"critical={self._ready_critical_count} max_ms={self._ready_interval_max_ms:.1f}"
            )
        try:
            import os
            keep_on = bool(
                os.environ.get("MAYOTTER_KEEP_REC_WAV")
                or os.environ.get("MAYOTTER_MEDIA_DEBUG")
            )
            if path is not None and path.is_file() and size > 44 and keep_on:
                import shutil
                from datetime import datetime as _dt
                from src.media.media_converter import media_temp_dir
                stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
                dest = media_temp_dir() / f"keep_{stamp}_{path.name}"
                shutil.copy2(str(path), str(dest))
                _rec_log(
                    f"kept_rec_wav={dest} "
                    f"pcm_sec={pcm_sec!r} sample_count={sample_count!r} "
                    f"rate={self._rate} channels={self._channels}"
                )
                try:
                    side = dest.with_suffix(".diag.txt")
                    side.write_text(
                        "\n".join(
                            [
                                f"wav={dest}",
                                f"source_temp={path}",
                                f"rate={self._rate}",
                                f"channels={self._channels}",
                                f"sample_format={_sample_format_name(self._sample_format)}",
                                f"capture_bytes_per_sample={self._capture_bytes_per_sample}",
                                f"wav_bytes_per_sample={self._bytes_per_sample}",
                                f"buffer_requested={self._buffer_size_requested}",
                                f"buffer_actual={self._buffer_size_actual}",
                                f"bytes_written={self._bytes_written}",
                                f"sample_count={sample_count}",
                                f"ready_count={self._ready_count}",
                                f"pcm_sec={pcm_sec}",
                                f"wall_sec={wall_sec}",
                                f"pcm_minus_wall={delta}",
                                f"interval_mean_ms={mean_interval}",
                                f"interval_max_ms={self._ready_interval_max_ms}",
                                f"delay_count={self._ready_delay_count}",
                                f"critical_count={self._ready_critical_count}",
                                f"read_bytes_min={self._bytes_per_read_min}",
                                f"read_bytes_max={self._bytes_per_read_max}",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    _rec_log(f"kept_rec_diag={side}")
                except Exception as side_exc:
                    _rec_log(f"kept_rec_diag_failed={side_exc!r}")
        except Exception as exc:
            _rec_log(f"keep_rec_wav_failed={exc!r}")
        if path is not None and path.is_file() and size > 44:
            self.stopped.emit(str(path))
        else:
            self.failed.emit("録音ファイルを保存できませんでした（データなし）")

    def cancel(self) -> None:
        if not self._active and self._path is None:
            return
        self._active = False
        self._timer.stop()
        self._pcm_watch.stop()
        try:
            if self._source is not None:
                self._source.stop()
        except Exception:
            pass
        try:
            if self._wave is not None:
                self._wave.close()
        except Exception:
            pass
        path = self._path
        self._wave = None
        self._source = None
        self._io = None
        self._path = None
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except TypeError:
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass
        _rec_log("cancelled")

    def _on_state_changed(self, state) -> None:
        err = _no_error_value()
        try:
            if self._source is not None:
                err = self._source.error()
        except Exception:
            pass
        _rec_log(f"stateChanged={_state_name(state)} error={_error_name(err)}")
        if not self._active:
            return
        if _is_fatal_error(err):
            self._active = False
            self._timer.stop()
            self._pcm_watch.stop()
            self.failed.emit(f"録音エラー: {_error_name(err)}")
            self._cleanup_partial()

    def _on_pcm_timeout(self) -> None:
        if not self._active:
            return
        if self._ready_count > 0 and self._bytes_written > 0:
            return
        _rec_log(
            f"pcm_timeout ready_count={self._ready_count} bytes_written={self._bytes_written}"
        )
        self._active = False
        self._timer.stop()
        try:
            if self._source is not None:
                err = self._source.error()
                state = self._source.state()
                _rec_log(f"pcm_timeout state={_state_name(state)} error={_error_name(err)}")
                self._source.stop()
        except Exception:
            pass
        self._cleanup_partial()
        self.failed.emit(
            "録音データが取得できませんでした（マイク権限または入力デバイスを確認してください）"
        )

    def _on_ready_read(self) -> None:
        if self._io is None or self._wave is None:
            return
        try:
            import time as _time
            now_mono = _time.monotonic()
            interval_ms = None
            if self._last_ready_mono is not None:
                interval_ms = (now_mono - float(self._last_ready_mono)) * 1000.0
            self._last_ready_mono = now_mono

            data = self._io.readAll()
            if not data:
                return
            raw = bytes(data)
            pcm16 = self._to_int16_pcm(raw)
            if not pcm16:
                return
            self._wave.writeframes(pcm16)
            self._bytes_written += len(pcm16)
            self._ready_count += 1

            nbytes = len(raw)
            if self._bytes_per_read_min == 0 or nbytes < self._bytes_per_read_min:
                self._bytes_per_read_min = nbytes
            if nbytes > self._bytes_per_read_max:
                self._bytes_per_read_max = nbytes
            if interval_ms is not None and interval_ms >= 0.0:
                self._ready_interval_sum_ms += interval_ms
                self._ready_interval_count += 1
                if interval_ms > self._ready_interval_max_ms:
                    self._ready_interval_max_ms = interval_ms
                if interval_ms >= self._ready_delay_warn_ms:
                    self._ready_delay_count += 1
                if interval_ms >= self._ready_delay_crit_ms:
                    self._ready_critical_count += 1
                    if self._crit_log_budget > 0:
                        self._crit_log_budget -= 1
                        approx_pcm_sec = 0.0
                        try:
                            frame_bytes = max(1, self._channels * 2)
                            approx_pcm_sec = self._bytes_written / float(frame_bytes) / float(
                                max(1, self._rate)
                            )
                        except Exception:
                            pass
                        _rec_log(
                            f"readyRead_DELAY_CRIT interval_ms={interval_ms:.1f} "
                            f"read_bytes={nbytes} written={len(pcm16)} "
                            f"total_bytes={self._bytes_written} approx_pcm_sec={approx_pcm_sec:.3f} "
                            f"ready_count={self._ready_count}"
                        )

            if self._ready_count % 40 == 0:
                try:
                    self._wave._file.flush()
                except Exception:
                    try:
                        import os as _os
                        fobj = getattr(self._wave, "_file", None)
                        if fobj is not None:
                            fobj.flush()
                            _os.fsync(fobj.fileno())
                    except Exception:
                        pass
            if self._ready_count == 1:
                _rec_log(
                    f"first_pcm_received=true readyRead bytes={len(raw)} "
                    f"written={len(pcm16)} recording_active=true"
                )
            elif self._ready_count <= 3 or self._ready_count % 50 == 0:
                _rec_log(
                    f"readyRead bytes={len(raw)} written={len(pcm16)} "
                    f"total={self._bytes_written} count={self._ready_count}"
                )
            if self._pcm_watch.isActive() and self._bytes_written > 0:
                self._pcm_watch.stop()
            try:
                from PySide6.QtCore import QDateTime
                now = int(QDateTime.currentMSecsSinceEpoch())
            except Exception:
                now = 0
            if (
                now == 0
                or (now - int(getattr(self, "_last_level_emit_ms", 0)))
                >= int(getattr(self, "_level_min_interval_ms", 50))
            ):
                self._last_level_emit_ms = now
                peak, rms = self._meter_int16(pcm16)
                self.level.emit(peak, rms)
        except Exception as exc:
            _rec_log(f"readyRead error: {exc!r}")

    def _to_int16_pcm(self, raw: bytes) -> bytes:
        nch = self._channels
        sf = self._sample_format
        try:
            if sf == QAudioFormat.SampleFormat.Int16:
                return raw
            if sf == QAudioFormat.SampleFormat.UInt8:
                out = bytearray()
                for b in raw:
                    v = (b - 128) * 256
                    out += struct.pack("<h", max(-32767, min(32767, v)))
                return bytes(out)
            if sf == QAudioFormat.SampleFormat.Int32:
                n = len(raw) // 4
                if n <= 0:
                    return b""
                samples = struct.unpack("<" + "i" * n, raw[: n * 4])
                return struct.pack(
                    "<" + "h" * n,
                    *[max(-32767, min(32767, s >> 16)) for s in samples],
                )
            if sf == QAudioFormat.SampleFormat.Float:
                n = len(raw) // 4
                if n <= 0:
                    return b""
                samples = struct.unpack("<" + "f" * n, raw[: n * 4])
                out_s = []
                for s in samples:
                    v = int(round(s * 32767.0))
                    if v > 32767:
                        v = 32767
                    elif v < -32767:
                        v = -32767
                    out_s.append(v)
                return struct.pack("<" + "h" * n, *out_s)
            if len(raw) % 2 == 0:
                return raw
        except Exception as exc:
            _rec_log(f"to_int16: {exc!r}")
        return b""

    def _meter_int16(self, raw: bytes) -> tuple[float, float]:
        try:
            n = len(raw) // 2
            if n <= 0:
                return 0.0, 0.0
            samples = struct.unpack("<" + "h" * n, raw[: n * 2])
            vals = [s / 32768.0 for s in samples]
            peak = max(abs(v) for v in vals)
            step = max(1, len(vals) // 512)
            acc = 0.0
            c = 0
            for i in range(0, len(vals), step):
                v = vals[i]
                acc += v * v
                c += 1
            rms = (acc / c) ** 0.5 if c else 0.0
            return float(min(1.0, peak)), float(min(1.0, rms))
        except Exception:
            return 0.0, 0.0

    def _on_tick(self) -> None:
        self._seconds += 1
        self.elapsed.emit(self._seconds)

    def _cleanup_partial(self) -> None:
        self._active = False
        self._timer.stop()
        self._pcm_watch.stop()
        try:
            if self._source is not None:
                try:
                    self._source.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self._wave is not None:
                self._wave.close()
        except Exception:
            pass
        if self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except Exception:
                pass
        self._wave = None
        self._source = None
        self._io = None
        self._path = None
