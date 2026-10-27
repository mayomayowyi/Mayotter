"""配布物の自己診断（`Mayotter.exe --mayotter-selftest <出力フォルダ>`）。

配布フォルダだけで、同梱の FFmpeg と DeepFilterNet3 / ONNX Runtime を使った音声投稿用の変換が
できるかを確かめる。合成音声を使い、利用者のデータ・設定・録音には触れない。
結果は <出力フォルダ>/selftest.json に書き、すべて成功なら終了コード 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path


def _say(msg: str) -> None:
    if sys.stdout is not None:  # 窓のみの実行ファイルでは出力先が無いことがある
        print(msg, flush=True)


def _write_input(path: Path, seconds: float, rate: int = 44100) -> None:
    """前半は声に近い倍音、後半 2 秒は雑音だけ。全体に白色雑音（約 -40 dBFS）。"""
    import numpy as np
    t = np.arange(int(rate * seconds)) / rate
    voice = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((160, 320, 480, 1100, 2400)))
    voice = 0.25 * voice / np.max(np.abs(voice)) * (0.6 + 0.4 * np.sin(2 * np.pi * 3.5 * t))
    voice[t >= seconds - 2.0] = 0.0
    noise = np.random.default_rng(7).standard_normal(len(t)) * 0.01
    pcm = np.clip((voice + noise) * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio_info(path: Path) -> dict:
    from src.media.ffmpeg_util import find_ffmpeg, probe_duration_seconds
    kw: dict = {"capture_output": True, "text": True, "timeout": 60, "errors": "replace"}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    err = subprocess.run([str(find_ffmpeg()), "-hide_banner", "-i", str(path)], check=False, **kw).stderr
    m = re.search(r"Audio: (\w+).*?(\d+) Hz", err)
    return {"duration": probe_duration_seconds(path), "codec": m.group(1) if m else None,
            "rate": int(m.group(2)) if m else None, "video": "Video:" in err}


def _tail_db(path: Path, seconds: float) -> float:
    """float WAV の末尾（雑音だけの区間）の音量 dBFS。"""
    import numpy as np
    raw = path.read_bytes()
    x = np.frombuffer(raw[raw.index(b"data") + 8:], "<f4")
    seg = x[-int(48000 * (seconds - 0.2)):]
    return float(20 * np.log10(np.sqrt(np.mean(seg.astype(np.float64) ** 2)) + 1e-12))


def run(out_dir: Path) -> dict:
    from src.core import paths
    from src.media import denoise
    from src.media.ffmpeg_util import FFmpegError, find_ffmpeg
    from src.media.media_converter import audio_file_to_mp4

    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"frozen": bool(getattr(sys, "frozen", False)), "app_dir": str(paths.APP_BASE_DIR),
                    "python": sys.version.split()[0], "checks": {}}
    checks = report["checks"]

    def check(name: str, fn) -> None:
        t0 = time.monotonic()
        try:
            detail = fn()
            checks[name] = {"ok": True, "seconds": round(time.monotonic() - t0, 2), **(detail or {})}
        except Exception as exc:
            checks[name] = {"ok": False, "seconds": round(time.monotonic() - t0, 2),
                            "error": f"{type(exc).__name__}: {exc}"}
        _say(f"[selftest] {name}: {'OK' if checks[name]['ok'] else 'FAILED ' + checks[name]['error']}")

    def bundled() -> dict:
        ff = find_ffmpeg()
        st = denoise.engine_status()
        import numpy
        import onnxruntime
        info = {"ffmpeg": str(ff), "model": st.get("model"), "numpy": numpy.__version__,
                "onnxruntime": onnxruntime.__version__}
        if report["frozen"]:
            base = paths.APP_BASE_DIR.resolve()
            if base not in ff.resolve().parents:
                raise RuntimeError(f"ffmpeg is not the bundled one: {ff}")
            if not st["available"] or base not in Path(st["model"]).resolve().parents:
                raise RuntimeError(f"bundled model not used: {st}")
        elif not st["available"]:
            raise RuntimeError(st["reason"])
        return info

    work = Path(tempfile.mkdtemp(prefix="mayotter_selftest_"))
    src = work / "input.wav"
    _write_input(src, 6.0)
    original = _sha(src)
    check("bundled_components", bundled)

    def convert(name: str, **kw) -> None:
        def _do() -> dict:
            dst = out_dir / f"{name}.mp4"
            dst.unlink(missing_ok=True)
            audio_file_to_mp4(src, dst, normalize=True, declick=True, **kw)
            info = _audio_info(dst)
            if not info["duration"] or abs(info["duration"] - 6.0) > 0.15:
                raise RuntimeError(f"duration {info['duration']}")
            want = 48000 if kw.get("denoise") else 44100
            if info["codec"] != "aac" or info["rate"] != want or not info["video"]:
                raise RuntimeError(f"unexpected streams {info}")
            if _sha(src) != original:
                raise RuntimeError("the original audio was modified")
            return {"output": str(dst), **info, "size": dst.stat().st_size}
        check(name, _do)

    convert("convert_ai_off")
    convert("convert_ai_on", denoise=True, denoise_strength="standard")
    convert("convert_ai_weak", denoise=True, denoise_strength="weak")
    convert("convert_ai_strong", denoise=True, denoise_strength="strong")

    def reduction() -> dict:
        import numpy as np
        dst = work / "dn.wav"
        stats = denoise.run_denoise_subprocess(src, dst, strength="standard", duration=6.0)
        with wave.open(str(src)) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
        noisy_db = float(20 * np.log10(np.sqrt(np.mean(x[-int(44100 * 1.8):] ** 2))))
        tail = _tail_db(dst, 2.0)
        res = {"noisy_tail_db": round(noisy_db, 1), "tail_db": round(tail, 1),
               "reduction_db": round(noisy_db - tail, 1), "seconds": stats.get("seconds"),
               "worker_peak_rss_mb": stats.get("peak_rss_mb")}
        if stats.get("frames") != 6 * 48000 or res["reduction_db"] < 10:
            raise RuntimeError(f"noise was not reduced as expected: {res}")
        levels = {"standard": res["reduction_db"]}
        for strength in ("weak", "strong"):
            stats = denoise.run_denoise_subprocess(src, dst, strength=strength, duration=6.0)
            levels[strength] = round(noisy_db - _tail_db(dst, 2.0), 1)
            if stats["frames"] != 6 * 48000 or stats["strength"] != strength:
                raise RuntimeError(f"unexpected strength output: {stats}")
        if not (6 < levels["weak"] <= 12.5 and
                levels["weak"] < levels["standard"] <= 20.5 and
                levels["strong"] > levels["standard"]):
            raise RuntimeError(f"strength levels not applied: {levels}")
        return {**res, "strength_levels_db": levels}
    check("ai_noise_reduction", reduction)

    def failure() -> dict:
        saved = denoise.model_search_paths
        denoise.model_search_paths = lambda: [work / "missing" / denoise.MODEL_FILENAME]
        try:
            dst = out_dir / "convert_ai_failure.mp4"
            dst.unlink(missing_ok=True)
            try:
                audio_file_to_mp4(src, dst, normalize=True, denoise=True)
            except denoise.DenoiseError as exc:
                if dst.exists():
                    raise RuntimeError("an output was written despite the failure") from exc
                if _sha(src) != original:
                    raise RuntimeError("the original audio was modified") from exc
                return {"error_shown": str(exc)}
            raise RuntimeError("conversion did not fail without the DeepFilterNet3 model")
        finally:
            denoise.model_search_paths = saved
    check("ai_failure_is_reported", failure)

    def cancel() -> dict:
        long_src = work / "long.wav"
        _write_input(long_src, 60.0)
        dst = work / "cancel.wav"
        started = threading.Event()
        try:
            denoise.run_denoise_subprocess(long_src, dst, duration=60.0,
                                           progress_cb=lambda f: started.set(),
                                           cancel_flag=started.is_set)
        except denoise.DenoiseCancelled:
            if dst.exists():
                raise RuntimeError("partial output left after cancel")
            return {}
        raise RuntimeError("cancel did not stop the worker")
    check("ai_cancel", cancel)

    def cancel_conversion() -> dict:
        dst = out_dir / "convert_cancelled.mp4"
        dst.unlink(missing_ok=True)
        try:
            audio_file_to_mp4(src, dst, normalize=True, denoise=True, cancel_flag=lambda: True)
        except FFmpegError as exc:
            if dst.exists():
                raise RuntimeError("output left after cancel") from exc
            return {"message": str(exc)}
        raise RuntimeError("conversion was not cancelled")
    check("conversion_cancel", cancel_conversion)

    report["ok"] = all(c["ok"] for c in checks.values())
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return report


def cli_main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else Path(tempfile.gettempdir()) / "mayotter_selftest"
    if not os.environ.get("QT_QPA_PLATFORM") and sys.platform.startswith("linux") \
            and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"  # 波形映像の描画用（画面は出さない）
    try:
        report = run(out_dir.resolve())
    except Exception as exc:
        report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "selftest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    _say(f"[selftest] {'PASSED' if report.get('ok') else 'FAILED'}: {out_dir / 'selftest.json'}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(cli_main(sys.argv[1:]))
