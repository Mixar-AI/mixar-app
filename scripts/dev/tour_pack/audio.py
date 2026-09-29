# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Speech-segment detection on a mono 16 kHz WAV (numpy only).

A segment is a run of frames whose RMS sits above ``threshold_db`` (relative
to full scale), with gaps shorter than ``min_gap_ms`` bridged and runs
shorter than ``min_speech_ms`` dropped. Times are milliseconds.
"""

import wave
from dataclasses import dataclass

import numpy as np

FRAME_MS = 10


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def read_wav(path: str):
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0, rate


def rms_db(samples: np.ndarray, rate: int, frame_ms: int = FRAME_MS) -> np.ndarray:
    hop = int(rate * frame_ms / 1000)
    n = len(samples) // hop
    frames = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1)) + 1e-9
    return 20.0 * np.log10(rms)


def segments(db: np.ndarray, threshold_db: float = -40.0, min_gap_ms: int = 300,
             min_speech_ms: int = 200, frame_ms: int = FRAME_MS) -> list:
    """Speech runs from a per-frame dB track."""
    voiced = db > threshold_db
    out = []
    start = None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([start * frame_ms, i * frame_ms])
            start = None
    if start is not None:
        out.append([start * frame_ms, len(voiced) * frame_ms])
    # Bridge short gaps.
    merged = []
    for s in out:
        if merged and s[0] - merged[-1][1] < min_gap_ms:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [Segment(s, e) for s, e in merged if e - s >= min_speech_ms]


def analyse(path: str, **kw) -> list:
    samples, rate = read_wav(path)
    return segments(rms_db(samples, rate), **kw)


def level_in(db: np.ndarray, start_ms: int, end_ms: int, frame_ms: int = FRAME_MS) -> float:
    """Peak frame level (dB) inside a window."""
    a, b = max(0, start_ms // frame_ms), max(1, end_ms // frame_ms)
    if a >= len(db):
        return -120.0
    return float(np.max(db[a:min(b, len(db))]))
