from __future__ import annotations
from src.core.i18n import tr

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
        raise FFmpegNotFoundError(tr('MAYOTTER_FFMPEG is set but not a file: {v0}', v0=env))

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
        tr('FFmpeg が見つかりません。音声の MP4 変換には FFmpeg が必要です。Mayotter と同じ場所の tools\\ffmpeg\\ffmpeg.exe に置くか、PATH を通してください。')
    )

_SOXR_AVAILABLE: bool | None = None


def soxr_available() -> bool:
    """FFmpeg が高品質リサンプラー（soxr）付きでビルドされているか。結果は保持する。"""
    global _SOXR_AVAILABLE
    if _SOXR_AVAILABLE is None:
        try:
            kw: dict = {"capture_output": True, "timeout": 20, "shell": False}
            if sys.platform == "win32":
                kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            proc = subprocess.run(
                [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "anullsrc=r=44100:cl=mono", "-t", "0.05", "-af",
                 "aresample=48000:resampler=soxr", "-f", "null", "-"], **kw)
            _SOXR_AVAILABLE = proc.returncode == 0
        except Exception:
            _SOXR_AVAILABLE = False
    return bool(_SOXR_AVAILABLE)


_ALIMITER_LATENCY: bool | None = None


def alimiter_latency_supported() -> bool:
    """alimiter の遅延補正（latency, FFmpeg 5.1+）が使えるか。"""
    global _ALIMITER_LATENCY
    if _ALIMITER_LATENCY is None:
        try:
            kw: dict = {"capture_output": True, "timeout": 20, "shell": False}
            if sys.platform == "win32":
                kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            proc = subprocess.run(
                [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "anullsrc=r=48000:cl=mono", "-t", "0.05", "-af",
                 "alimiter=latency=1", "-f", "null", "-"], **kw)
            _ALIMITER_LATENCY = proc.returncode == 0
        except Exception:
            _ALIMITER_LATENCY = False
    return bool(_ALIMITER_LATENCY)


def resampler_filter(rate: int) -> str:
    """rate へ変換する aresample。soxr があれば高精度、無ければ標準リサンプラーを高品質設定で使う。"""
    if soxr_available():
        return f"aresample={int(rate)}:resampler=soxr:precision=28"
    return f"aresample={int(rate)}:filter_size=64:phase_shift=10:cutoff=0.97"


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
        raise FFmpegError(tr('FFmpeg を起動できません: {v0}', v0=exc)) from exc

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
                raise FFmpegError(tr('変換がキャンセルされました'))
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
        raise FFmpegError(tr('FFmpeg がタイムアウトしました')) from None
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
            tr('FFmpeg failed (code {v0}): {v1}', v0=format_process_rc(rc), v1=tail[:500])
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
        raise FFmpegError(tr('FFmpeg を起動できません: {v0}', v0=exc)) from exc

def probe_duration_seconds(path: str | Path) -> float | None:
    path = str(path)
    ff = find_ffmpeg()
    probe = ff.with_name("ffprobe.exe" if ff.suffix.lower() == ".exe" else "ffprobe")
    if probe.is_file():
        try:
            _kw: dict = {
                "stderr": subprocess.DEVNULL,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
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
            "encoding": "utf-8",
            "errors": "replace",
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
TARGET_TP = -2.5
TARGET_LRA = 11.0

# 増幅量の上限。発話かどうか判定できないとき・ノイズらしいときは小さく、
# 発話と判断できるときだけ大きく許す（極端に小さい声を -16 LUFS 付近へ上げるため）
MAX_LOUDNORM_GAIN_DB = 10.0
MAX_SPEECH_GAIN_DB = 30.0
NOISE_LIKE_GAIN_DB = 0.0
# 25ms 区間の音量の（上位95% - 下位20%）がこれ未満なら、起伏の無いノイズとみなす
SPEECH_SPREAD_DB = 8.0
# 極端に小さい音量（LUFS）では、より明確な起伏がある場合だけ発話とみなす
VERY_LOW_LUFS = -60.0
VERY_LOW_SPREAD_DB = 12.0
MIN_DYNAMICS_SECONDS = 0.5
MIN_ACTIVE_RATIO = 0.08
ALREADY_NORMALIZED_LU = 1.0

# 録音時のサンプル欠落で出るプチノイズを、音量調整の前に除く
DECLICK_FILTER = "adeclick=w=55:o=75:a=2:t=2:b=2:m=a"
MIN_USABLE_WAV_RMS = 0.0015

# リミッターでピークを削る量の上限（dB）。これを超える分は目標音量を下げ、声を潰さない。
MAX_LIMITER_DB = 6.0
LIMITER_OVERSAMPLE_RATE = 192000

# loudnorm は大きな増幅やクリックの多い音声でピークを取りこぼすことがある。
# 最終段でサンプルピークを TARGET_TP に揃え、AAC 変換後も -2 dBTP 以下に収める
_PEAK_LIMITER = f",alimiter=limit={10 ** (TARGET_TP / 20):.4f}:level=disabled:attack=3:release=60"

def measure_loudness(path: str | Path, pre_filter: str | None = None) -> dict:
    """loudnorm の測定値を返す。pre_filter は変換時に loudnorm の前へ入るフィルタ（declick 等）。"""
    path = str(Path(path).resolve())
    ff = str(find_ffmpeg())
    af = f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json"
    if pre_filter:
        af = f"{pre_filter},{af}"
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

def analyze_dynamics(path: str | Path, pre_filter: str | None = None) -> dict:
    """音量の起伏を調べる（発話かノイズかの判定用）。

    48kHz モノラルで 25ms ごとの RMS を求め、上位95%と下位20%の差（dB）と、
    最大付近の音量が続く割合を返す。
    解析できないときは空の dict。
    """
    out: dict = {}
    try:
        import numpy as np

        cmd = [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-i",
               str(Path(path).resolve()), "-vn"]
        if pre_filter:
            cmd += ["-af", pre_filter]
        # ゲートの閾値に使うため、実際の変換音声と同じ帯域で計測する。
        # 8kHzへ間引くと広帯域のヒスノイズが過小評価され、ゲートが効かなくなる。
        cmd += ["-ac", "1", "-ar", "48000", "-t", "300", "-f", "s16le", "-"]
        kw: dict = {"capture_output": True, "timeout": 120, "shell": False}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(cmd, **kw)
        if proc.returncode != 0:
            return out
        data = np.frombuffer(proc.stdout or b"", dtype="<i2")
        frame = 1200  # 25ms @48kHz
        n = len(data) // frame
        if n < 2:
            return out
        # 300秒録音でも巨大な float 配列を作らないよう、少量ずつ RMS を集計。
        rms = np.empty(n, dtype=np.float32)
        for start in range(0, n, 128):
            stop = min(n, start + 128)
            chunk = data[start * frame:stop * frame].astype(np.float32).reshape(-1, frame) / 32768.0
            rms[start:stop] = np.sqrt(np.mean(chunk * chunk, axis=1))
        db = 20.0 * np.log10(np.maximum(rms, 1e-7))
        out["frames"] = int(n)
        out["seconds"] = n * frame / 48000.0
        out["p95_db"] = float(np.percentile(db, 95))
        out["p20_db"] = float(np.percentile(db, 20))
        out["spread_db"] = float(out["p95_db"] - out["p20_db"])
        # 最大付近の音量が続く時間の割合。クリック等の短い音だけの録音は小さくなる
        out["active_ratio"] = float(np.mean(db >= np.percentile(db, 95) - 15.0))
    except Exception:
        return {}
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
        return base + _PEAK_LIMITER
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
        ) + _PEAK_LIMITER
    except (KeyError, TypeError, ValueError):
        return base + _PEAK_LIMITER

def speech_pause_expander_filter(
    dynamics: dict | None,
    plan: dict | None,
    *,
    reference_dynamics: dict | None = None,
) -> str | None:
    """声のある録音だけ、発話間の定常ノイズを穏やかに減衰させる。

    録音の生音量（正規化前）でしきい値を決め、ゲイン処理の前に適用する。
    信号の起伏が小さい、解析に失敗した、発話と環境音が分離できないときは
    誤って小声を削るよりも何も適用しない方を優先する。
    """
    import math

    if not dynamics or not plan:
        return None
    try:
        gain = float(plan.get("applied_gain") or 0.0)
        floor_db = float(dynamics["p20_db"])
        voiced_db = float(dynamics["p95_db"])
        active = float(dynamics["active_ratio"])
        duration = float(dynamics["seconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (gain, floor_db, voiced_db, active, duration)):
        return None
    if (gain <= 0 or duration < MIN_DYNAMICS_SECONDS or active < MIN_ACTIVE_RATIO
            or voiced_db - floor_db < 14.0):
        return None

    # 無音側の20パーセンタイルから +8〜12dB、声の上位音量より12dB以上低く置く。
    # 強い床ノイズで声との分離が困難な場合にはゲートを動かさない。
    offset_db = min(12.0, max(8.0, 8.0 + (gain - 10.0) / 10.0))
    threshold_db = max(-62.0, min(floor_db + offset_db, voiced_db - 12.0))

    # AI処理後は無音区間のp20が大きく下がるため、たまたま残った環境音が
    # 閾値(-62dBFS付近)を超えてゲートを開くことがある。元WAVの定常ノイズ床を
    # 下限として使い、同じノイズが「無音→+20dB増幅」を行き来しないようにする。
    # 元音声で声とノイズの差が十分ない場合、無理なゲートは小声を切るため使わない。
    if reference_dynamics is not None:
        try:
            raw_floor_db = float(reference_dynamics["p20_db"])
            raw_voice_db = float(reference_dynamics["p95_db"])
            raw_active = float(reference_dynamics["active_ratio"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in (raw_floor_db, raw_voice_db, raw_active)):
            return None
        if raw_voice_db - raw_floor_db < 14.0 or raw_active < MIN_ACTIVE_RATIO:
            return None
        # 元音声ノイズ床+10dBを基準にしつつ、発話上位音量より12dB低く抑える。
        threshold_db = max(threshold_db, raw_floor_db + 10.0)
        threshold_db = min(threshold_db, raw_voice_db - 12.0, voiced_db - 12.0)

    if threshold_db >= voiced_db - 8.0:
        return None
    threshold = 10.0 ** (threshold_db / 20.0)
    return (
        f"agate=threshold={threshold:.8f}:ratio=6:range=0.02"
        ":attack=10:release=260:knee=3:detection=rms"
    )


def gain_filter_string(gain_db: float, input_tp: float | None) -> str:
    """一定ゲイン（音色・抑揚を変えない）と、必要なときだけトゥルーピーク近似のリミッター。

    loudnorm の 2 パス目は、増幅後のピークが上限を超えると黙って動的圧縮（dynamic）へ切り替わり、
    声の抑揚が潰れる。ここでは音量は一定のゲインだけで合わせ、はみ出した瞬間的なピークだけを
    4 倍オーバーサンプリングしたリミッターで抑える。
    """
    import math
    g = float(gain_db) if math.isfinite(float(gain_db)) else 0.0
    parts = [f"volume={g:.2f}dB"]
    try:
        peak_after = float(input_tp) + g
    except (TypeError, ValueError):
        peak_after = 0.0
    if not math.isfinite(peak_after) or peak_after > TARGET_TP - 0.1:
        lim = f"alimiter=limit={10 ** (TARGET_TP / 20):.4f}:attack=5:release=60:level=disabled"
        if alimiter_latency_supported():
            lim += ":latency=1"
        parts += [resampler_filter(LIMITER_OVERSAMPLE_RATE), lim]
    return ",".join(parts)


def _apply_gain_plan(plan: dict, input_i: float, input_tp: float, target_i: float,
                     mode: str, gain_limited: bool) -> dict:
    gain = target_i - input_i
    # ピークを MAX_LIMITER_DB より多く削る必要があるなら、その分だけ目標音量を下げる
    over = (input_tp + gain) - (TARGET_TP + MAX_LIMITER_DB)
    if over > 0.0:
        gain -= over
        target_i = input_i + gain
        mode = "two_pass_peak_capped"
        gain_limited = True
    plan["af"] = gain_filter_string(gain, input_tp)
    plan["mode"] = mode
    plan["applied_gain"] = gain
    plan["gain_limited"] = gain_limited
    plan["target_i"] = target_i
    plan["limiter_db"] = max(0.0, input_tp + gain - TARGET_TP)
    return plan


def plan_loudness_filter(
    measured: dict | None,
    *,
    peak_info: dict | None = None,
    dynamics: dict | None = None,
) -> dict:
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
        # 測定失敗時に 1-pass loudnorm へ進むと、無音や故障した録音が極端に増幅される。
        plan["af"] = None
        plan["mode"] = "skip_measure_failed"
        plan["applied_gain"] = 0.0
        plan["gain_limited"] = True
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

    # 定常ノイズ・短いクリックなど、発話と判断できない録音は正方向へ増幅しない。
    # 従来は必要ゲインが +10dB 以内ならノイズ判定より先に増幅してしまっていた。
    if dynamics and float(dynamics.get("seconds") or 0.0) >= MIN_DYNAMICS_SECONDS:
        spread = float(dynamics.get("spread_db") or 0.0)
        active = float(dynamics.get("active_ratio", 1.0))
        need = VERY_LOW_SPREAD_DB if input_i < VERY_LOW_LUFS else SPEECH_SPREAD_DB
        if (spread < max(need, 14.0) or active < MIN_ACTIVE_RATIO) and estimated > 0.0:
            plan["af"] = None
            plan["mode"] = "skip_noise_like_gain"
            plan["gain_class"] = "noise_like" if spread < need else "ambiguous"
            plan["applied_gain"] = 0.0
            plan["gain_limited"] = True
            return plan

    # すでに目標付近でピークも収まっている音声は加工しない
    if abs(estimated) <= ALREADY_NORMALIZED_LU and input_tp <= TARGET_TP:
        plan["af"] = None
        plan["mode"] = "skip_already_normalized"
        plan["applied_gain"] = 0.0
        plan["gain_limited"] = False
        return plan

    if estimated <= MAX_LOUDNORM_GAIN_DB:
        return _apply_gain_plan(plan, input_i, input_tp, TARGET_I, "two_pass", False)

    # 大きな増幅が必要。解析不能の音声は安全側に倒し、無音ノイズを持ち上げない。
    max_gain = 0.0 if not dynamics else MAX_LOUDNORM_GAIN_DB
    plan["gain_class"] = "unknown"
    if dynamics and float(dynamics.get("seconds") or 0.0) >= MIN_DYNAMICS_SECONDS:
        spread = float(dynamics.get("spread_db") or 0.0)
        need = VERY_LOW_SPREAD_DB if input_i < VERY_LOW_LUFS else SPEECH_SPREAD_DB
        plan["spread_db"] = spread
        active = float(dynamics.get("active_ratio", 1.0))
        plan["active_ratio"] = active
        if spread >= need and active >= MIN_ACTIVE_RATIO:
            # 声と背景音の差が小さいと、長い無音区間も大幅に増幅される。
            # 十分な音量差がある録音だけ高ゲインを許す。
            max_gain = MAX_SPEECH_GAIN_DB if spread >= 14.0 else NOISE_LIKE_GAIN_DB
            plan["gain_class"] = "speech" if spread >= 14.0 else "ambiguous"
        else:
            max_gain = NOISE_LIKE_GAIN_DB
            plan["gain_class"] = "noise_like"

    if estimated <= max_gain:
        return _apply_gain_plan(plan, input_i, input_tp, TARGET_I, "two_pass", False)
    return _apply_gain_plan(plan, input_i, input_tp, input_i + max_gain, "two_pass_gain_capped", True)

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
        # wave は 32bit float（AI ノイズ除去の出力）を読めないため、自前で読む
        try:
            out.update(_float_wav_peak_rms(path))
        except Exception:
            pass
    return out


def _float_wav_peak_rms(path: Path) -> dict:
    """WAVE_FORMAT_IEEE_FLOAT（32bit）の WAV のピークと RMS。対応外なら空の dict。"""
    import struct
    import numpy as np

    with open(path, "rb") as fh:
        head = fh.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return {}
        fmt = None
        while True:
            hdr = fh.read(8)
            if len(hdr) < 8:
                return {}
            cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
            if cid == b"fmt ":
                body = fh.read(size)
                fmt = struct.unpack("<HHIIHH", body[:16])
                fh.read(size & 1)
            elif cid == b"data":
                if fmt is None or fmt[0] != 3 or fmt[5] != 32:
                    return {}
                nch, rate = fmt[1], fmt[2]
                x = np.fromfile(fh, dtype="<f4", count=size // 4)
                break
            else:
                fh.seek(size + (size & 1), 1)
    nframes = len(x) // max(1, nch)
    if not len(x):
        return {"frames": 0, "channels": nch, "rate": rate}
    step = max(1, len(x) // 200_000)
    return {
        "wav_peak": float(np.max(np.abs(x))),
        "wav_rms": float(np.sqrt(np.mean(np.square(x[::step], dtype=np.float64)))),
        "frames": nframes, "channels": nch, "rate": rate,
        "sample_count": int(len(x)),
        "duration_sec": float(nframes) / float(rate) if rate else 0.0,
    }
