"""Keep DeepFilterNet's residual background noise from pumping during pauses.

Only the temporary denoised WAV is adjusted. Speech activity comes from the
original recording, so unpredictable residual energy cannot open the gate.
"""
from __future__ import annotations

from src.core.i18n import tr

import math
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 48000
FRAME = 960  # 20 ms
QUIET_GAIN = 10 ** (-24.0 / 20.0)
NOISE_ONLY_GAIN = 10 ** (-18.0 / 20.0)


def _raw_frame_levels(path: Path) -> np.ndarray:
    from src.media.ffmpeg_util import find_ffmpeg

    cmd = [str(find_ffmpeg()), "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
           "-f", "f32le", "pipe:1"]
    kwargs: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                    "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    proc = subprocess.Popen(cmd, **kwargs)
    blocks = []
    tail = np.zeros(0, np.float32)
    try:
        assert proc.stdout is not None
        while True:
            raw = proc.stdout.read(FRAME * 4 * 200)
            if not raw:
                break
            arr = np.frombuffer(raw[:len(raw) // 4 * 4], "<f4")
            if len(tail):
                arr = np.concatenate((tail, arr))
            n = len(arr) // FRAME
            if n:
                block = arr[:n * FRAME].reshape(n, FRAME).astype(np.float64)
                blocks.append(np.sqrt(np.mean(block * block, axis=1)).astype(np.float32))
            tail = arr[n * FRAME:].copy()
        if len(tail):
            blocks.append(np.array([np.sqrt(np.mean(tail.astype(np.float64)**2))], np.float32))
        if proc.wait() != 0:
            raise RuntimeError(tr('original audio decode failed'))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdout:
            proc.stdout.close()
    if not blocks:
        return np.zeros(0, np.float32)
    return 20 * np.log10(np.maximum(np.concatenate(blocks), 1e-7))


def activity_envelope(levels_db: np.ndarray) -> np.ndarray | None:
    """Return a slow, continuous gain envelope; None when speech is ambiguous.

    Short incidental clicks do not count as speech. Once a syllable is identified,
    open before its onset and close after its tail to avoid chopping consonants.
    """
    levels = np.asarray(levels_db, dtype=np.float32)
    n = len(levels)
    if n < 10 or not np.isfinite(levels).all():
        return None
    floor = float(np.percentile(levels, 20))
    high = float(np.percentile(levels, 95))
    spread = high - floor
    if spread < 8.0:
        # Steady *quiet* noise can be attenuated without a pumping gate.
        # A steady but audible signal might be soft speech: leave it alone.
        if high >= -53.0:
            return None
        return np.full(n, NOISE_ONLY_GAIN, np.float32)
    if spread < 14.0:
        # Cannot reliably distinguish soft voice from ambient noise.
        return None

    threshold = floor + 11.0
    above = levels >= threshold
    changes = np.diff(np.r_[False, above, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    # At least 60 ms of sustained activity (ignore isolated ticks).
    groups = [(int(a), int(b)) for a, b in zip(starts, ends) if b - a >= 3]
    if not groups:
        return None
    merged = []
    for a, b in groups:
        if merged and a - merged[-1][1] <= 14:  # bridge 280 ms pauses
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))

    env = np.full(n, QUIET_GAIN, np.float32)
    for onset, end in merged:
        pre_start = max(0, onset - 9)
        # Keep the long lead-in when it may contain a quiet consonant. Clear
        # room tone needs only a 40-ms attack, not a 180-ms noise swell.
        if np.all(levels[pre_start:onset] <= floor + 3.0):
            pre_start = max(0, onset - 2)
        fade_end = min(n, onset)
        if fade_end > pre_start:
            k = np.linspace(0, 1, fade_end - pre_start, endpoint=False, dtype=np.float32)
            up = QUIET_GAIN + (1 - QUIET_GAIN) * (0.5 - 0.5 * np.cos(np.pi * k))
            env[pre_start:fade_end] = np.maximum(env[pre_start:fade_end], up)
        # Keep output fully open through pauses shorter than 280 ms, plus 220 ms.
        release_start = min(n, end + 11)
        env[onset:release_start] = 1.0
        # Gradual 260 ms release. Do not let a prior release lower a later onset.
        release_end = min(n, release_start + 13)
        if release_end > release_start:
            k = np.linspace(0, 1, release_end - release_start, endpoint=False, dtype=np.float32)
            down = QUIET_GAIN + (1 - QUIET_GAIN) * (0.5 + 0.5 * np.cos(np.pi * k))
            env[release_start:release_end] = np.maximum(env[release_start:release_end], down)
    _guard_startup_noise(levels, env, merged[0][0], threshold)
    return env


def _guard_startup_noise(levels: np.ndarray, env: np.ndarray,
                         first_speech_frame: int, speech_threshold: float) -> None:
    """Reduce a short recorder-start burst only when speech onset is safely later.

    This acts on the temporary denoised WAV through the existing activity
    envelope, never on the original WAV. A level excursion relative to the
    following room tone must be present; ordinary recordings are unchanged.
    """
    if first_speech_frame < 50 or len(levels) < 55:  # >= 1 second quiet lead-in
        return
    early = levels[:15]  # First 300 ms
    reference = levels[20:min(60, first_speech_frame - 12)]  # 400 ms .. 1.2 s
    if len(reference) < 12:
        return
    transient = float(np.percentile(early, 90))
    baseline = float(np.median(reference))
    if transient - baseline < 6.0 or transient >= speech_threshold:
        return
    # 14 dB more suppression for the burst, tapering smoothly to the usual
    # 24 dB quiet gain by 700 ms; all later speech/gains remain untouched.
    guard_gain = 10.0 ** (-14.0 / 20.0)
    solid, end = 15, 35
    env[:solid] *= guard_gain
    p = np.linspace(0.0, 1.0, end - solid, endpoint=True, dtype=np.float32)
    blend = guard_gain + (1.0 - guard_gain) * (0.5 - 0.5 * np.cos(np.pi * p))
    env[solid:end] *= blend


def _float_wav_data(path: Path) -> tuple[int, int]:
    """Locate PCM float samples written by DeepFilterNet, without third-party WAV I/O."""
    with path.open("rb") as fh:
        if fh.read(4) != b"RIFF":
            raise ValueError(tr('not a RIFF WAV'))
        fh.seek(8)
        if fh.read(4) != b"WAVE":
            raise ValueError(tr('not a WAVE file'))
        format_ok = False
        while True:
            head = fh.read(8)
            if len(head) != 8:
                break
            kind, size = struct.unpack("<4sI", head)
            if kind == b"fmt ":
                fmt = fh.read(size)
                if len(fmt) < 16:
                    raise ValueError(tr('invalid WAV format'))
                tag, channels, rate, _bps, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
                format_ok = tag == 3 and channels == 1 and rate == RATE and bits == 32
            elif kind == b"data":
                if not format_ok or size % 4:
                    raise ValueError(tr('not mono 48kHz float32 WAV'))
                return fh.tell(), size // 4
            else:
                fh.seek(size + (size % 2), 1)
        raise ValueError(tr('WAV has no data chunk'))


def stabilize_denoised_silence(original_path: Path, enhanced_path: Path) -> bool:
    """Modify *only* the temporary AI WAV; return False if no safe adjustment."""
    levels = _raw_frame_levels(Path(original_path))
    envelope = activity_envelope(levels)
    if envelope is None:
        return False
    offset, count = _float_wav_data(Path(enhanced_path))
    if abs(math.ceil(count / FRAME) - len(envelope)) > 2:
        return False
    data = np.memmap(enhanced_path, dtype="<f4", mode="r+", offset=offset, shape=(count,))
    try:
        # 1-second blocks, no additional temp WAV or large sample arrays.
        for start in range(0, count, RATE):
            stop = min(count, start + RATE)
            centers = np.arange(start, stop, dtype=np.float64) / FRAME
            gains = np.interp(centers, np.arange(len(envelope)), envelope,
                              left=float(envelope[0]), right=float(envelope[-1]))
            data[start:stop] *= gains.astype(np.float32)
        data.flush()
    finally:
        del data
    return True
