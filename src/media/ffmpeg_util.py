from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from src.core.paths import APP_BASE_DIR

class FFmpegNotFoundError(RuntimeError):
    """FFmpeg が見つからない。"""

class FFmpegError(RuntimeError):
    """FFmpeg が失敗した。"""

def _bundled_candidates() -> list[Path]:
    base = APP_BASE_DIR
    names = ("ffmpeg.exe", "ffmpeg") if sys.platform == "win32" else ("ffmpeg", "ffmpeg.exe")
    out: list[Path] = []
    for root in (
        base / "tools" / "ffmpeg",
        base / "tools",
        base,
    ):
        for name in names:
            out.append(root / name)
    return out

def find_ffmpeg() -> Path:
    env = (os.environ.get("MAYOTTER_FFMPEG") or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
        raise FFmpegNotFoundError(f"MAYOTTER_FFMPEG is set but not a file: {env}")

    for cand in _bundled_candidates():
        if cand.is_file() and (
            os.access(cand, os.X_OK) or (cand.is_file() and sys.platform == "win32")
        ):
            if cand.is_file():
                return cand.resolve()

    which = shutil.which("ffmpeg")
    if which:
        return Path(which).resolve()

    raise FFmpegNotFoundError(
        "FFmpeg が見つかりません。"
        "音声の MP4 変換には FFmpeg が必要です。"
        "Mayotter と同じ場所の tools\\ffmpeg\\ffmpeg.exe に置くか、PATH を通してください。"
    )

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

def parse_ffmpeg_time_seconds(line: str) -> float | None:
    m = _TIME_RE.search(line or "")
    if not m:
        return None
    h, mi, s = m.groups()
    try:
        return int(h) * 3600 + int(mi) * 60 + float(s)
    except ValueError:
        return None

def run_ffmpeg(
    args: list[str],
    *,
    timeout: float | None = None,
    progress_cb=None,
    duration_hint: float | None = None,
    cancel_flag=None,
) -> None:
    ffmpeg = str(find_ffmpeg())
    cmd = [ffmpeg, "-hide_banner", "-y", *args]
    popen_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": False,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        raise FFmpegError(f"FFmpeg を起動できません: {exc}") from exc

    stderr_chunks: list[str] = []
    assert proc.stderr is not None
    try:
        while True:
            if cancel_flag is not None and cancel_flag():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise FFmpegError("変換がキャンセルされました")
            line = proc.stderr.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            stderr_chunks.append(line)
            if progress_cb is not None and duration_hint and duration_hint > 0:
                t = parse_ffmpeg_time_seconds(line)
                if t is not None:
                    progress_cb(min(0.99, max(0.0, t / duration_hint)))
        rc = proc.wait(timeout=timeout if timeout else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise FFmpegError("FFmpeg がタイムアウトしました") from None
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        except Exception:
            pass

    rc_s = normalize_process_rc(rc)
    if rc_s != 0:
        tail = "".join(stderr_chunks[-20:]).strip()
        raise FFmpegError(
            f"FFmpeg failed (code {format_process_rc(rc)}): {tail[:500]}"
        )

    if progress_cb is not None:
        progress_cb(1.0)

def run_ffmpeg_pipe_stdin(args: list[str]):
    ffmpeg = str(find_ffmpeg())
    cmd = [ffmpeg, "-hide_banner", "-y", *args]
    popen_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE,
        "shell": False,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        return subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        raise FFmpegError(f"FFmpeg を起動できません: {exc}") from exc

def probe_duration_seconds(path: str | Path) -> float | None:
    path = str(path)
    ff = find_ffmpeg()
    probe = ff.with_name("ffprobe.exe" if ff.suffix.lower() == ".exe" else "ffprobe")
    if probe.is_file():
        try:
            _kw: dict = {
                "stderr": subprocess.DEVNULL,
                "text": True,
                "timeout": 30,
                "shell": False,
            }
            if sys.platform == "win32":
                _kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            out = subprocess.check_output(
                [
                    str(probe),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                **_kw,
            )
            return float(out.strip())
        except Exception:
            pass
    try:
        _rkw: dict = {
            "capture_output": True,
            "text": True,
            "timeout": 30,
            "shell": False,
        }
        if sys.platform == "win32":
            _rkw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run([str(ff), "-i", path], **_rkw)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return None

def normalize_process_rc(rc: int | None) -> int | None:
    if rc is None:
        return None
    try:
        rc = int(rc)
    except (TypeError, ValueError):
        return None
    if rc > 0x7FFFFFFF:
        return rc - 0x100000000
    return rc

def format_process_rc(rc: int | None) -> str:
    signed = normalize_process_rc(rc)
    if signed is None:
        return "None"
    if rc is not None and int(rc) != signed:
        return f"{signed} (unsigned={rc})"
    return str(signed)

def loudness_measured_usable(measured: dict | None) -> bool:
    import math
    if not measured:
        return False
    try:
        ii = float(measured["input_i"])
        tp = float(measured["input_tp"])
        lra = float(measured.get("input_lra", 0.0))
        thr = float(measured.get("input_thresh", -99.0))
    except (KeyError, TypeError, ValueError):
        return False
    for v in (ii, tp, lra, thr):
        if not math.isfinite(v):
            return False
    if ii < -70.0:
        return False
    if tp < -60.0 and ii < -50.0:
        return False
    return True

TARGET_I = -16.0
TARGET_TP = -1.5
TARGET_LRA = 11.0

MAX_LOUDNORM_GAIN_DB = 10.0
MIN_USABLE_WAV_RMS = 0.0015

def measure_loudness(path: str | Path) -> dict:
    path = str(Path(path).resolve())
    ff = str(find_ffmpeg())
    af = f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json"
    cmd = [ff, "-hide_banner", "-i", path, "-af", af, "-f", "null", "-"]
    kw: dict = {
        "capture_output": True,
        "text": True,
        "timeout": 180,
        "shell": False,
    }
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(cmd, **kw)
    except Exception:
        return {}
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return {}
    out: dict = {}
    for key in (
        "input_i",
        "input_tp",
        "input_lra",
        "input_thresh",
        "target_offset",
        "output_i",
        "output_tp",
        "output_lra",
        "output_thresh",
    ):
        if key in data:
            try:
                out[key] = float(data[key])
            except (TypeError, ValueError):
                out[key] = data[key]
    return out

def loudnorm_filter_string(
    measured: dict | None = None,
    *,
    target_i: float | None = None,
) -> str:
    import math

    ti = float(TARGET_I if target_i is None else target_i)
    if not math.isfinite(ti):
        ti = float(TARGET_I)
    base = f"loudnorm=I={ti}:TP={TARGET_TP}:LRA={TARGET_LRA}"
    if not measured or not loudness_measured_usable(measured):
        return base
    try:
        offset = float(measured.get("target_offset", 0.0))
        if not math.isfinite(offset):
            offset = 0.0
        try:
            input_i = float(measured["input_i"])
            if math.isfinite(input_i) and ti > TARGET_I:
                offset = 0.0
        except Exception:
            pass
        return (
            f"loudnorm=I={ti}:TP={TARGET_TP}:LRA={TARGET_LRA}"
            f":measured_I={float(measured['input_i'])}"
            f":measured_TP={float(measured['input_tp'])}"
            f":measured_LRA={float(measured['input_lra'])}"
            f":measured_thresh={float(measured['input_thresh'])}"
            f":offset={offset}"
            ":linear=true"
        )
    except (KeyError, TypeError, ValueError):
        return base

def plan_loudness_filter(
    measured: dict | None,
    *,
    peak_info: dict | None = None,
) -> dict:
    import math

    plan = {
        "af": loudnorm_filter_string(None),
        "mode": "single_pass",
        "input_lufs": None,
        "input_tp": None,
        "input_rms": None,
        "input_peak": None,
        "estimated_gain": None,
        "applied_gain": None,
        "gain_limited": False,
        "target_i": TARGET_I,
    }
    if peak_info:
        try:
            plan["input_rms"] = float(peak_info.get("wav_rms") or 0.0)
            plan["input_peak"] = float(peak_info.get("wav_peak") or 0.0)
        except Exception:
            pass

    try:
        rms = float(plan["input_rms"] or 0.0)
        peak = float(plan["input_peak"] or 0.0)
        if rms > 0.0 and rms < MIN_USABLE_WAV_RMS and peak < 0.02:
            plan["af"] = None
            plan["mode"] = "skip_near_silence_rms"
            plan["applied_gain"] = 0.0
            plan["estimated_gain"] = 0.0
            plan["gain_limited"] = True
            return plan
    except Exception:
        pass

    if not measured:
        plan["mode"] = "single_pass_measure_failed"
        return plan

    if not loudness_measured_usable(measured):
        plan["af"] = None
        plan["mode"] = "skip_unusable_silence"
        plan["applied_gain"] = 0.0
        plan["estimated_gain"] = 0.0
        plan["gain_limited"] = True
        try:
            plan["input_lufs"] = measured.get("input_i")
            plan["input_tp"] = measured.get("input_tp")
        except Exception:
            pass
        return plan

    try:
        input_i = float(measured["input_i"])
        input_tp = float(measured["input_tp"])
    except Exception:
        plan["af"] = None
        plan["mode"] = "skip_unusable_silence"
        plan["applied_gain"] = 0.0
        plan["gain_limited"] = True
        return plan

    plan["input_lufs"] = input_i
    plan["input_tp"] = input_tp
    estimated = TARGET_I - input_i
    plan["estimated_gain"] = estimated

    if estimated <= 0.0:
        plan["af"] = loudnorm_filter_string(measured, target_i=TARGET_I)
        plan["mode"] = "two_pass"
        plan["applied_gain"] = estimated
        plan["gain_limited"] = False
        plan["target_i"] = TARGET_I
        return plan

    if estimated <= MAX_LOUDNORM_GAIN_DB:
        plan["af"] = loudnorm_filter_string(measured, target_i=TARGET_I)
        plan["mode"] = "two_pass"
        plan["applied_gain"] = estimated
        plan["gain_limited"] = False
        plan["target_i"] = TARGET_I
        return plan

    capped_target = input_i + MAX_LOUDNORM_GAIN_DB
    if capped_target < TARGET_I:
        target_i = capped_target
    else:
        target_i = TARGET_I
    plan["af"] = loudnorm_filter_string(measured, target_i=target_i)
    plan["mode"] = "two_pass_gain_capped"
    plan["applied_gain"] = target_i - input_i
    plan["gain_limited"] = True
    plan["target_i"] = target_i
    return plan

def wav_peak_rms(path: str | Path) -> dict:
    import struct
    import wave

    path = Path(path)
    out = {"wav_peak": 0.0, "wav_rms": 0.0, "frames": 0, "channels": 0, "rate": 0}
    if path.suffix.lower() != ".wav" or not path.is_file():
        return out
    try:
        with wave.open(str(path), "rb") as w:
            nch = w.getnchannels()
            sw = w.getsampwidth()
            rate = w.getframerate()
            nframes = w.getnframes()
            raw = w.readframes(nframes)
        out["frames"] = nframes
        out["channels"] = nch
        out["rate"] = rate
        if nframes <= 0 or sw not in (1, 2) or not raw:
            return out
        if sw == 2:
            count = len(raw) // 2
            samples = struct.unpack("<" + "h" * count, raw[: count * 2])
            scale = 32768.0
        else:
            samples = [b - 128 for b in raw]
            scale = 128.0
        if not samples:
            return out
        peak = max(abs(s) for s in samples) / scale
        step = max(1, len(samples) // 200_000)
        acc = 0.0
        n = 0
        for i in range(0, len(samples), step):
            v = samples[i] / scale
            acc += v * v
            n += 1
        rms = (acc / n) ** 0.5 if n else 0.0
        out["wav_peak"] = float(peak)
        out["wav_rms"] = float(rms)
        out["sample_count"] = int(len(samples))
        out["duration_sec"] = float(nframes) / float(rate) if rate else 0.0
        try:
            out["pcm_min"] = float(min(samples))
            out["pcm_max"] = float(max(samples))
        except Exception:
            pass
    except Exception:
        pass
    return out
