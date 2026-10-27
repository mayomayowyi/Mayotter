"""音声投稿用の AI ノイズ除去（DeepFilterNet3、完全ローカル・CPU）。

- 推論は onnxruntime、前後処理（STFT / ERB 特徴量 / Deep Filtering / 逆 STFT）は numpy で
  DeepFilterNet（libdf）と同じ計算を行う。48 kHz・フルバンド。
- Mayotter 本体とは別プロセスで実行する（`run_denoise_subprocess`）。本体へ onnxruntime や
  モデルを常駐させず、ネイティブ処理の異常終了やキャンセルからも本体を守るため。
- 長時間の録音でもメモリが増えないよう、約 10 秒ずつ逐次処理する。正規化の状態は引き継ぎ、
  モデルには前後の文脈を付けて実行してつなぎ目を消す。
- 処理遅延（STFT の n_fft - hop = 480 サンプル）は補正し、出力は入力と同じ長さ・同じ時刻。

モデルは公式の `DeepFilterNet3_onnx.tar.gz` を使い、SHA-256 で公式ファイルと照合する。Windows 配布版は
`tools/denoise/` に同梱する（packaging/stage_third_party.py）。公開重みの再配布条件は上流で未確定
（Rikorose/DeepFilterNet issue #697 / #712。packaging/licenses/README.md に記録）。
"""
from __future__ import annotations
from src.core.i18n import tr

import hashlib
import json
import os
import struct
import subprocess
import sys
import tarfile
import time
from pathlib import Path

SR = 48000
FFT_SIZE = 960
HOP = 480
NB_ERB = 32
NB_DF = 96
DF_ORDER = 5
DF_LOOKAHEAD = 2
CONV_LOOKAHEAD = 2
NORM_ALPHA = 0.99          # exp(-hop/sr / tau=1) を libdf と同じ桁で丸めた値
DELAY = FFT_SIZE - HOP     # STFT/ISTFT の遅延（サンプル）

MODEL_FILENAME = "DeepFilterNet3_onnx.tar.gz"
# 公式リポジトリ models/DeepFilterNet3_onnx.tar.gz（2023-05-23 版）の SHA-256
MODEL_SHA256 = "c94d91f70911001c946e0fabb4aa9adc37045f45a03b56008cb0c8244cb63616"
MODEL_URL = "https://github.com/Rikorose/DeepFilterNet/raw/main/models/DeepFilterNet3_onnx.tar.gz"
MODEL_NAME = "DeepFilterNet3"

# 遅延補正済みの原音を混ぜて減衰の上限を設定する。
STRENGTHS = {"weak": 12.0, "standard": 20.0, "strong": None}
DEFAULT_STRENGTH = "strong"

# 1 回の推論で出力するフレーム数（10 秒）と、その前に流す文脈（4 秒）。文脈で GRU とたたみ込みの
# 状態をなじませ、一括処理との差を -40 dB 程度に抑える。作業メモリは録音の長さによらず約 300 MB。
CHUNK_FRAMES = 1000
CONTEXT_FRAMES = 400
FUTURE_FRAMES = CONV_LOOKAHEAD + DF_LOOKAHEAD
# Offline processing: prime feature normalization and model context from a quiet
# section of this recording before processing its first audible sample.
# This is discarded completely: neither duration nor timestamp may change.
PREROLL_SCAN_SECONDS = 16
PREROLL_SECONDS = 8
PREROLL_NOISE_WINDOW_MS = 800
PREROLL_SPEECH_SECONDS = 8
PREROLL_SETTLE_MS = 800



class DenoiseError(RuntimeError):
    """ノイズ除去に失敗した（モデル無し・処理失敗・出力異常）。元の録音は変更されない。"""


class DenoiseCancelled(DenoiseError):
    """ノイズ除去がキャンセルされた。"""



def model_search_paths() -> list[Path]:
    from src.core import paths
    out: list[Path] = []
    env = (os.environ.get("MAYOTTER_DENOISE_MODEL") or "").strip()
    if env:
        out.append(Path(env))
    out.append(paths.APP_BASE_DIR / "tools" / "denoise" / MODEL_FILENAME)
    out.append(paths.DATA_DIR / "models" / MODEL_FILENAME)
    return out


_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def _sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), int(st.st_size), int(st.st_mtime_ns))
    if key not in _HASH_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        _HASH_CACHE[key] = h.hexdigest()
    return _HASH_CACHE[key]


def find_model() -> Path | None:
    for cand in model_search_paths():
        if cand.is_file():
            return cand
    return None


def engine_status() -> dict:
    """AI ノイズ除去を使えるか。onnxruntime は読み込まず、存在だけを確かめる（本体の常駐を増やさない）。"""
    import importlib.util
    if importlib.util.find_spec("numpy") is None or importlib.util.find_spec("onnxruntime") is None:
        return {"available": False, "reason": tr('AI処理用のランタイム（onnxruntime）がありません'), "model": None}
    model = find_model()
    if model is None:
        return {"available": False,
                "reason": tr('モデル（{v0}）が見つかりません', v0=MODEL_FILENAME), "model": None}
    try:
        digest = _sha256(model)
    except OSError as exc:
        return {"available": False, "reason": tr('モデルを読めません: {v0}', v0=exc), "model": str(model)}
    if digest != MODEL_SHA256:
        return {"available": False, "reason": tr('モデルの検証に失敗しました（公式ファイルと一致しません）'),
                "model": str(model)}
    return {"available": True, "reason": tr('{v0}（ローカル処理）', v0=MODEL_NAME), "model": str(model)}



def _np():
    import numpy as np
    return np


def vorbis_window():
    np = _np()
    i = np.arange(FFT_SIZE)
    s = np.sin(0.5 * np.pi * (i + 0.5) / (FFT_SIZE // 2))
    return np.sin(0.5 * np.pi * s * s).astype(np.float32)


def erb_widths(sr: int = SR, fft_size: int = FFT_SIZE, nb_bands: int = NB_ERB, min_nb_freqs: int = 2):
    import math
    def f2e(f):
        return 9.265 * math.log1p(f / (24.7 * 9.265))

    def e2f(e):
        return 24.7 * 9.265 * (math.exp(e / 9.265) - 1.0)

    freq_width = sr / fft_size
    lo, hi = f2e(0.0), f2e(sr / 2)
    step = (hi - lo) / nb_bands
    widths, prev, over = [], 0, 0
    for i in range(1, nb_bands + 1):
        fb = int(round(e2f(lo + i * step) / freq_width))
        nb = fb - prev - over
        if nb < min_nb_freqs:
            over = min_nb_freqs - nb
            nb = min_nb_freqs
        else:
            over = 0
        widths.append(nb)
        prev = fb
    widths[-1] += 1
    too_large = sum(widths) - (fft_size // 2 + 1)
    if too_large > 0:
        widths[-1] -= too_large
    return _np().array(widths, dtype=_np().int64)


class _Model:
    def __init__(self, model_path: Path, threads: int | None = None) -> None:
        import onnxruntime as ort
        blobs: dict[str, bytes] = {}
        with tarfile.open(model_path, "r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                if name in ("enc.onnx", "erb_dec.onnx", "df_dec.onnx") and member.isfile():
                    fh = tar.extractfile(member)
                    if fh is not None:
                        blobs[name] = fh.read()
        if len(blobs) != 3:
            raise DenoiseError(tr('モデルファイルの中身が想定と異なります'))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(threads or min(4, os.cpu_count() or 2)))
        opts.inter_op_num_threads = 1
        # 推論ごとの作業領域を保持し続けない（別プロセスのピークメモリを抑える）
        opts.enable_cpu_mem_arena = False
        prov = ["CPUExecutionProvider"]
        self.enc = ort.InferenceSession(blobs["enc.onnx"], opts, providers=prov)
        self.erb_dec = ort.InferenceSession(blobs["erb_dec.onnx"], opts, providers=prov)
        self.df_dec = ort.InferenceSession(blobs["df_dec.onnx"], opts, providers=prov)

    def run(self, feat_erb, feat_spec):
        """feat_erb [T,32], feat_spec [T,96] complex（先読み分ずらし済み） → mask [T,32], coefs [T,96,5] complex"""
        np = _np()
        spec = np.stack([feat_spec.real, feat_spec.imag])[None].astype(np.float32)
        e0, e1, e2, e3, emb, c0, _lsnr = self.enc.run(
            None, {"feat_erb": feat_erb[None, None].astype(np.float32), "feat_spec": spec})
        mask = self.erb_dec.run(None, {"emb": emb, "e3": e3, "e2": e2, "e1": e1, "e0": e0})[0][0, 0]
        coefs = self.df_dec.run(None, {"emb": emb, "c0": c0})[0][0]
        coefs = coefs.reshape(coefs.shape[0], NB_DF, DF_ORDER, 2)
        return mask, coefs[..., 0] + 1j * coefs[..., 1]


class StreamingDenoiser:
    """48 kHz モノラルの float32 を順に受け取り、遅延補正済みの強調音声を順に返す。"""

    def __init__(self, model: _Model, atten_lim_db: float | None = None) -> None:
        np = _np()
        self.np = np
        self.model = model
        self.window = vorbis_window()
        self.wnorm = 1.0 / (FFT_SIZE * FFT_SIZE / (2 * HOP))
        self.widths = erb_widths()
        self.band_idx = np.repeat(np.arange(NB_ERB), self.widths)
        self.mix = 0.0 if atten_lim_db is None else 10 ** (-abs(float(atten_lim_db)) / 20.0)
        self.in_buf = np.zeros(0, np.float32)         # まだフレームにしていない入力
        self.ana_mem = np.zeros(FFT_SIZE - HOP, np.float32)
        self.erb_state = np.linspace(-60.0, -90.0, NB_ERB)
        self.df_state = np.linspace(0.001, 0.0001, NB_DF)
        # 推論待ちのフレーム（スペクトル・特徴量）。先頭 base が frame 番号
        self.spec = np.zeros((0, FFT_SIZE // 2 + 1), np.complex64)
        self.fe = np.zeros((0, NB_ERB), np.float32)
        self.fs = np.zeros((0, NB_DF), np.complex64)
        self.base = 0              # self.spec[0] のフレーム番号
        self.done = 0              # 出力済みフレーム数
        self.syn_mem = np.zeros(FFT_SIZE - HOP, np.float32)
        self.dry = np.zeros(0, np.float32)            # 原音（混合用。出力と同じ時刻にそろえる）
        self.to_drop = DELAY                          # 先頭の遅延分を捨てる
        self.total_in = 0
        self.total_out = 0

    # --- 分析（STFT と特徴量） ---
    def _analyze(self, samples) -> None:
        np = self.np
        self.in_buf = np.concatenate([self.in_buf, samples])
        n = len(self.in_buf) // HOP
        if n == 0:
            return
        block = self.in_buf[: n * HOP]
        self.in_buf = self.in_buf[n * HOP:]
        x = np.concatenate([self.ana_mem, block])
        self.ana_mem = x[-(FFT_SIZE - HOP):].copy()
        frames = np.lib.stride_tricks.sliding_window_view(x, FFT_SIZE)[::HOP][:n]
        X = (np.fft.rfft(frames * self.window, axis=1) * self.wnorm).astype(np.complex64)
        power = np.abs(X) ** 2
        band = np.zeros((n, NB_ERB))
        np.add.at(band.T, self.band_idx, power.T)
        db = 10.0 * np.log10(band / self.widths + 1e-10)
        fe = np.empty((n, NB_ERB), np.float32)
        fs = np.empty((n, NB_DF), np.complex64)
        s, s2, a = self.erb_state, self.df_state, NORM_ALPHA
        mag = np.abs(X[:, :NB_DF])
        for t in range(n):
            s = db[t] * (1 - a) + s * a
            fe[t] = (db[t] - s) / 40.0
            s2 = mag[t] * (1 - a) + s2 * a
            fs[t] = X[t, :NB_DF] / np.sqrt(s2)
        self.erb_state, self.df_state = s, s2
        self.spec = np.concatenate([self.spec, X])
        self.fe = np.concatenate([self.fe, fe])
        self.fs = np.concatenate([self.fs, fs])

    # --- 強調（推論・マスク・Deep Filtering・逆 STFT） ---
    def _enhance(self, count: int, final: bool):
        """フレーム done .. done+count を確定させて時間波形を返す。"""
        np = self.np
        start = self.done
        ctx0 = max(self.base, start - CONTEXT_FRAMES)
        avail_end = self.base + len(self.spec)
        stop = start + count
        feat_end = min(avail_end, stop + FUTURE_FRAMES + CONV_LOOKAHEAD)
        lo, hi = ctx0 - self.base, feat_end - self.base
        fe, fs = self.fe[lo:hi], self.fs[lo:hi]
        # 先読み分ずらす（pad_feat）: 入力 t は特徴量 t+2 を使う。末尾はゼロ。
        sh = CONV_LOOKAHEAD
        fe = np.concatenate([fe[sh:], np.zeros((sh, NB_ERB), np.float32)])
        fs = np.concatenate([fs[sh:], np.zeros((sh, NB_DF), np.complex64)])
        mask, coefs = self.model.run(fe, fs)
        o0 = start - ctx0
        X = self.spec[start - self.base: stop - self.base]
        gain = np.repeat(mask[o0:o0 + count], self.widths, axis=1)
        Y = X * gain
        # Deep Filtering（低域 96 ビン）: 雑音入りスペクトル t-2..t+2 にフィルタ係数を掛ける
        k0 = start - (DF_ORDER - 1 - DF_LOOKAHEAD)
        k1 = stop + DF_LOOKAHEAD
        src = np.zeros((k1 - k0, NB_DF), np.complex64)
        a, b = max(k0, self.base), min(k1, avail_end)
        src[a - k0: b - k0] = self.spec[a - self.base: b - self.base, :NB_DF]
        c = coefs[o0:o0 + count]
        acc = np.zeros((count, NB_DF), np.complex64)
        for k in range(DF_ORDER):
            acc += c[:, :, k] * src[k:k + count]
        Y[:, :NB_DF] = acc
        # 逆 STFT（窓掛け重ね合わせ）
        frames = np.fft.irfft(Y, n=FFT_SIZE, axis=1).astype(np.float32) * FFT_SIZE * self.window
        out = np.empty(count * HOP, np.float32)
        mem = self.syn_mem
        for t in range(count):
            out[t * HOP:(t + 1) * HOP] = frames[t, :HOP] + mem
            mem = frames[t, HOP:]
        self.syn_mem = mem.copy()
        self.done = stop
        # 不要になった過去フレームを捨てる（文脈と DF の過去分は残す）
        keep_from = max(self.base, self.done - max(CONTEXT_FRAMES, DF_ORDER))
        cut = keep_from - self.base
        if cut > 0:
            self.spec, self.fe, self.fs = self.spec[cut:], self.fe[cut:], self.fs[cut:]
            self.base = keep_from
        return out

    def _emit(self, wet):
        np = self.np
        if self.to_drop:
            d = min(self.to_drop, len(wet))
            wet = wet[d:]
            self.to_drop -= d
        n = min(len(wet), len(self.dry))
        wet, dry = wet[:n], self.dry[:n]
        self.dry = self.dry[n:]
        if self.mix > 0.0:
            wet = wet * (1.0 - self.mix) + dry * self.mix
        self.total_out += n
        return wet.astype(np.float32)

    def push(self, samples):
        """入力を追加し、確定した出力（無ければ空配列）を返す。"""
        np = self.np
        samples = np.asarray(samples, dtype=np.float32)
        self.total_in += len(samples)
        self.dry = np.concatenate([self.dry, samples])
        self._analyze(samples)
        outs = []
        need = FUTURE_FRAMES + CONV_LOOKAHEAD
        while self.base + len(self.spec) - self.done >= CHUNK_FRAMES + need:
            outs.append(self._emit(self._enhance(CHUNK_FRAMES, final=False)))
        return np.concatenate(outs) if outs else np.zeros(0, np.float32)

    def finish(self):
        """残りを処理し、入力と同じ長さになるまでの出力を返す。"""
        np = self.np
        # 遅延と先読み分の無音を流し込んで最後のフレームまで確定させる
        pad = DELAY + HOP * (FUTURE_FRAMES + CONV_LOOKAHEAD + 2)
        self._analyze(np.zeros(pad, np.float32))
        outs = []
        while self.total_out < self.total_in:
            remaining = self.base + len(self.spec) - self.done
            if remaining <= 0:
                break
            outs.append(self._emit(self._enhance(min(CHUNK_FRAMES, remaining), final=True)))
        out = np.concatenate(outs) if outs else np.zeros(0, np.float32)
        return out


def _noise_preroll(samples):
    """Return repeated room tone for offline priming, or empty when unsafe.

    Selection is based on the quietest continuous 800-ms interval, not on the
    first seconds (which may contain speech). Guard against training on speech,
    clicks, digital silence or NaNs. Only the initial bounded 16-s buffer is
    inspected; long recordings never need to be loaded in memory.
    """
    np = _np()
    x = np.asarray(samples, dtype=np.float32)
    window = PREROLL_NOISE_WINDOW_MS * SR // 1000
    if len(x) < window or not np.isfinite(x).all():
        return np.zeros(0, np.float32)
    # Non-overlapping 20-ms RMS windows, scanned in 100-ms steps.
    frame = HOP * 2
    n = len(x) // frame
    if n < window // frame:
        return np.zeros(0, np.float32)
    powers = np.mean(x[:n * frame].reshape(n, frame).astype(np.float64) ** 2, axis=1)
    k = window // frame
    avg = np.convolve(powers, np.ones(k, dtype=np.float64) / k, mode="valid")
    candidates = np.arange(0, len(avg), 5, dtype=np.int64)
    if not len(candidates):
        return np.zeros(0, np.float32)
    ranked = candidates[np.argsort(avg[candidates])]
    noise = None
    for idx in ranked[:min(20, len(ranked))]:
        seg = x[int(idx) * frame:int(idx) * frame + window]
        rms = float(np.sqrt(avg[idx]))
        # -110 .. -40 dBFS; a louder candidate could contain soft speech.
        if not (3.2e-6 <= rms <= 0.01):
            continue
        if float(np.max(np.abs(seg))) > 0.035:
            continue
        noise = seg.copy()
        break
    if noise is None:
        return np.zeros(0, np.float32)
    # Overlap-add each repetition to avoid periodic seam clicks. The crossfade
    # is 40 ms, much shorter than the selected 800-ms noise sample.
    overlap = min(SR * 40 // 1000, len(noise) // 8)
    total = PREROLL_SECONDS * SR
    loop = noise
    fade = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
    while len(loop) < total:
        tail = loop[-overlap:] * (1.0 - fade) + noise[:overlap] * fade
        loop = np.concatenate((loop[:-overlap], tail, noise[overlap:]))
    out = np.asarray(loop[:total], dtype=np.float32).copy()
    # End at digital silence to avoid room-tone bleed at time zero.
    end = SR * 40 // 1000
    out[-end:] *= np.linspace(1.0, 0.0, end, dtype=np.float32)
    return out



def _conditioned_preroll(samples):
    """Prime normalization on a real utterance as well as the background noise.

    Quiet-only priming steadies the room tone, but cannot settle the feature
    statistics under speech. Offline conversion can inspect the initial audio
    twice without moving its timestamp. Never apply if a distinct voice and a
    usable room-tone reference cannot be established.
    """
    np = _np()
    noise = _noise_preroll(samples)
    if not len(noise):
        return noise
    if os.environ.get("MAYOTTER_DENOISE_SPEECH_PRIME", "1").strip().lower() in ("0", "off", "false"):
        return noise
    x = np.asarray(samples, np.float32)
    length = min(len(x), PREROLL_SPEECH_SECONDS * SR)
    if length < 3 * SR:
        return noise
    preview = x[:length]
    frame = HOP * 2
    count = len(preview) // frame
    z = preview[:count * frame].reshape(count, frame).astype(np.float64)
    db = 20 * np.log10(np.maximum(np.sqrt(np.mean(z * z, axis=1)), 1e-8))
    floor = float(np.percentile(db, 20))
    upper = float(np.percentile(db, 95))
    if floor > -45.0 or upper - floor < 14.0:
        return noise

    # Smooth the two discarded joins. After preview, a short room-tone tail
    # restores the immediate acoustic context without resetting speech stats.
    preview = preview.copy()
    fade = min(SR // 20, len(preview) // 4)  # 50 ms
    if fade:
        cross = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        preview[:fade] = noise[-fade:] * (1.0 - cross) + preview[:fade] * cross
        preview[-fade:] *= 1.0 - cross
    settle = noise[:PREROLL_SETTLE_MS * SR // 1000].copy()
    if len(settle):
        ramp = min(SR // 20, len(settle))
        settle[:ramp] *= np.linspace(0.0, 1.0, ramp, dtype=np.float32)
        settle[-ramp:] *= np.linspace(1.0, 0.0, ramp, dtype=np.float32)
    return np.concatenate((noise, preview, settle))


def _iter_decoded_pcm(stdout, *, initial_seconds=PREROLL_SCAN_SECONDS):
    """Read bounded look-ahead while retaining sequential decoding afterward."""
    np = _np()
    chunk_bytes = HOP * 4 * 400
    # Emergency opt-out without reinstalling: MAYOTTER_DENOISE_WARMUP=0.
    if os.environ.get("MAYOTTER_DENOISE_WARMUP", "1").lower() in ("0", "false", "off"):
        initial_seconds = 0
    target = initial_seconds * SR
    head = []
    count = 0
    while count < target:
        raw = stdout.read(min(chunk_bytes, (target - count) * 4))
        if not raw:
            break
        chunk = np.frombuffer(raw[:len(raw) // 4 * 4], dtype="<f4").copy()
        if len(chunk):
            head.append(chunk)
            count += len(chunk)
    buffered = np.concatenate(head) if head else np.zeros(0, np.float32)
    yield buffered, _conditioned_preroll(buffered)
    while True:
        raw = stdout.read(chunk_bytes)
        if not raw:
            break
        chunk = np.frombuffer(raw[:len(raw) // 4 * 4], dtype="<f4")
        if len(chunk):
            yield chunk, None



class _FloatWavWriter:
    def __init__(self, path: Path, rate: int = SR) -> None:
        self.fh = open(path, "wb")
        self.rate = rate
        self.frames = 0
        self._write_header()

    def _write_header(self) -> None:
        data_bytes = self.frames * 4
        self.fh.seek(0)
        self.fh.write(b"RIFF" + struct.pack("<I", 4 + 26 + 12 + 8 + data_bytes) + b"WAVE")
        # fmt: WAVE_FORMAT_IEEE_FLOAT, mono, 32bit
        self.fh.write(b"fmt " + struct.pack("<IHHIIHHH", 18, 3, 1, self.rate, self.rate * 4, 4, 32, 0))
        self.fh.write(b"fact" + struct.pack("<II", 4, self.frames))
        self.fh.write(b"data" + struct.pack("<I", data_bytes))

    def write(self, samples) -> None:
        self.fh.write(samples.astype("<f4").tobytes())
        self.frames += len(samples)

    def close(self) -> None:
        self._write_header()
        self.fh.close()



def _decode_cmd(src: Path, declick: bool) -> list[str]:
    from src.media.ffmpeg_util import DECLICK_FILTER, find_ffmpeg, resampler_filter
    filters = [DECLICK_FILTER] if declick else []
    filters.append(resampler_filter(SR))
    return [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(src),
            "-vn", "-ac", "1", "-af", ",".join(filters), "-ar", str(SR), "-f", "f32le", "-"]


def _check_output(stats: dict) -> None:
    if stats["frames"] <= 0:
        raise DenoiseError(tr('ノイズ除去の出力が空です'))
    if not stats["finite"]:
        raise DenoiseError(tr('ノイズ除去の出力に異常な値が含まれています'))
    if abs(stats["frames"] - stats["in_frames"]) > 1:
        raise DenoiseError(tr('ノイズ除去の出力の長さが録音と一致しません'))


def denoise_file(src: Path, dst: Path, *, strength: str = DEFAULT_STRENGTH, declick: bool = False,
                 duration: float | None = None, model_path: Path | None = None, progress=None,
                 threads: int | None = None) -> dict:
    """src を 48 kHz で読み、ノイズ除去した 32bit float WAV を dst に書く。統計を返す。"""
    np = _np()
    model_path = model_path or find_model()
    if model_path is None:
        raise DenoiseError(tr('モデル（{v0}）が見つかりません', v0=MODEL_FILENAME))
    if _sha256(model_path) != MODEL_SHA256:
        raise DenoiseError(tr('モデルの検証に失敗しました（公式ファイルと一致しません）'))
    t0 = time.monotonic()
    model = _Model(model_path, threads=threads)
    strength = strength if strength in STRENGTHS else DEFAULT_STRENGTH
    lim = STRENGTHS[strength]
    den = StreamingDenoiser(model, atten_lim_db=lim)
    kw: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(_decode_cmd(src, declick), **kw)
    writer = _FloatWavWriter(dst)
    stats = {"frames": 0, "in_frames": 0, "in_peak": 0.0, "out_peak": 0.0, "finite": True}
    expected = int((duration or 0) * SR)
    primed = False
    primed_samples = 0
    try:
        assert proc.stdout is not None
        discard = 0
        def _write_real_audio(y):
            nonlocal discard
            if discard:
                skipped = min(discard, len(y))
                y = y[skipped:]
                discard -= skipped
            if len(y):
                stats["finite"] &= bool(np.isfinite(y).all())
                stats["out_peak"] = max(stats["out_peak"], float(np.max(np.abs(y))))
                writer.write(y)
                stats["frames"] += len(y)

        for x, priming in _iter_decoded_pcm(proc.stdout):
            if priming is not None and len(priming):
                discard = len(priming)
                primed = True
                primed_samples = discard
                # The priming samples are never written and do not count as
                # input duration; processing them stabilizes feature history.
                _write_real_audio(den.push(priming))
            if not len(x):
                continue
            stats["in_frames"] += len(x)
            stats["in_peak"] = max(stats["in_peak"], float(np.max(np.abs(x))))
            _write_real_audio(den.push(x))
            if progress and expected:
                progress(min(0.99, stats["frames"] / expected))
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        if proc.wait() != 0:
            raise DenoiseError(tr('音声の読み込みに失敗しました: {v0}', v0=err.strip()[:300]))
        _write_real_audio(den.finish())
        if discard:
            raise DenoiseError(tr('ノイズ除去の事前処理を完了できませんでした'))
    finally:
        writer.close()
        if proc.poll() is None:
            proc.kill()
    _check_output(stats)
    stats.update(seconds=round(time.monotonic() - t0, 3), strength=strength, atten_lim_db=lim,
                 model=MODEL_NAME, rate=SR, peak_rss_mb=peak_rss_mb(),
                 primed_seconds=round(primed_samples / SR, 3) if primed else 0)
    return stats


def peak_rss_mb() -> float | None:
    """このプロセスのピークメモリ（MB）。測れなければ None（診断用）。"""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            pmc = _PMC()
            pmc.cb = ctypes.sizeof(pmc)
            k32 = ctypes.WinDLL("kernel32")
            psapi = ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return round(pmc.PeakWorkingSetSize / 2**20, 1)
            return None
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        return None


def cli_main(argv: list[str]) -> int:
    """別プロセスの入口。進行状況を `PROGRESS <0..1>`、結果を `RESULT <json>` で標準出力へ書く。"""
    import argparse
    p = argparse.ArgumentParser(prog="mayotter-denoise")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--strength", default=DEFAULT_STRENGTH, choices=sorted(STRENGTHS))
    p.add_argument("--declick", action="store_true")
    p.add_argument("--duration", type=float, default=0.0)
    p.add_argument("--model", default="")
    from src.core.i18n import LANGUAGES
    p.add_argument('--language', choices=LANGUAGES, default='ja')
    args = p.parse_args(argv)
    from src.core.i18n import set_language
    set_language(args.language)
    if sys.stdout is None:  # 窓のみの実行ファイルで出力先が無い（本体からの起動ではない）
        return 4
    last = [0.0]

    def progress(f: float) -> None:
        if f - last[0] >= 0.01:
            last[0] = f
            print(f"PROGRESS {f:.3f}", flush=True)

    try:
        stats = denoise_file(Path(args.src), Path(args.dst), strength=args.strength,
                             declick=args.declick, duration=args.duration,
                             model_path=Path(args.model) if args.model else None, progress=progress)
    except DenoiseError as exc:
        print("ERROR " + json.dumps({"message": str(exc)}, ensure_ascii=False), flush=True)
        return 2
    except Exception as exc:  # 想定外の失敗も本体へ伝える
        print("ERROR " + json.dumps({"message": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
              flush=True)
        return 3
    print("RESULT " + json.dumps(stats, ensure_ascii=False), flush=True)
    return 0



WORKER_FLAG = "--mayotter-denoise"


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    return [sys.executable, "-m", "src.media.denoise"]


def run_denoise_subprocess(src: Path, dst: Path, *, strength: str = DEFAULT_STRENGTH,
                           declick: bool = False, duration: float | None = None,
                           progress_cb=None, cancel_flag=None, timeout: float | None = None) -> dict:
    """別プロセスでノイズ除去する。失敗・キャンセルは DenoiseError（元の録音は変更しない）。"""
    status = engine_status()
    if not status["available"]:
        raise DenoiseError(status["reason"])
    from src.core import paths
    # 別プロセスは作業ディレクトリが異なるため、絶対パスで渡す
    src, dst = Path(src).resolve(), Path(dst).resolve()
    cmd = _worker_command() + [str(src), str(dst), "--strength", strength,
                               "--duration", f"{float(duration or 0.0):.3f}", "--model", status["model"]]
    from src.core.i18n import get_language
    cmd += ['--language', get_language()]
    if declick:
        cmd.append("--declick")
    kw: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL,
                "text": True, "encoding": "utf-8", "errors": "replace", "cwd": str(paths.APP_BASE_DIR)}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    kw["env"] = env
    try:
        proc = subprocess.Popen(cmd, **kw)
    except OSError as exc:
        raise DenoiseError(tr('ノイズ除去を起動できません: {v0}', v0=exc)) from exc
    deadline = time.monotonic() + (timeout or max(300.0, float(duration or 60.0) * 6 + 120))
    result: dict | None = None
    error: str | None = None
    import threading
    lines: list[str] = []
    done = threading.Event()

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))
        done.set()

    err_tail: list[str] = []

    def _err_reader() -> None:
        # 標準エラーを読み続けないと、パイプが詰まって別プロセスが止まる。末尾だけ保持する
        assert proc.stderr is not None
        for line in proc.stderr:
            err_tail.append(line)
            if len(err_tail) > 40:
                del err_tail[0]

    threading.Thread(target=_reader, daemon=True).start()
    err_thread = threading.Thread(target=_err_reader, daemon=True)
    err_thread.start()
    seen = 0
    try:
        while True:
            if cancel_flag is not None and cancel_flag():
                raise DenoiseCancelled(tr('変換がキャンセルされました'))
            if time.monotonic() > deadline:
                raise DenoiseError(tr('ノイズ除去がタイムアウトしました'))
            while seen < len(lines):
                line = lines[seen]
                seen += 1
                if line.startswith("PROGRESS ") and progress_cb:
                    try:
                        progress_cb(float(line.split()[1]))
                    except ValueError:
                        pass
                elif line.startswith("RESULT "):
                    result = json.loads(line[7:])
                elif line.startswith("ERROR "):
                    error = json.loads(line[6:]).get("message")
            if done.is_set() and proc.poll() is not None and seen >= len(lines):
                break
            time.sleep(0.05)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        _remove(dst)
        raise
    rc = proc.wait()
    err_thread.join(timeout=2.0)
    tail = "".join(err_tail)[-400:]
    if rc != 0 or result is None:
        _remove(dst)
        raise DenoiseError(error or tr('ノイズ除去が異常終了しました（code {v0}）: {v1}', v0=rc, v1=tail.strip()))
    if not dst.is_file() or dst.stat().st_size <= 64:
        _remove(dst)
        raise DenoiseError(tr('ノイズ除去の出力ファイルがありません'))
    return result


def _remove(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(cli_main(sys.argv[1:]))
