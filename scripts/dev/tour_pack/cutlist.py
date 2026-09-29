# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recover the cut list of an edited take from the raw take.

The edit keeps runs of the raw audio and drops the rest (trimmed silences),
so edited time maps to raw time as ``raw = edited + offset`` with a constant
offset inside every kept run and a jump at each cut. Every chunk of the
edited waveform is cross-correlated (FFT) against the whole raw take; the
lag with the highest normalised peak is that chunk's offset, and the offset
track is split into runs. Chunks that are mostly silence carry no
information and inherit their neighbours' offset.
"""

from dataclasses import dataclass

import numpy as np

from audio import read_wav


@dataclass(frozen=True)
class Run:
    edited_start_ms: int
    edited_end_ms: int
    raw_offset_ms: int          # raw_ms = edited_ms + raw_offset_ms

    @property
    def raw_start_ms(self) -> int:
        return self.edited_start_ms + self.raw_offset_ms

    @property
    def raw_end_ms(self) -> int:
        return self.edited_end_ms + self.raw_offset_ms


def _bandpass(x: np.ndarray, rate: int, lo=300.0, hi=3400.0) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    spec[(freqs < lo) | (freqs > hi)] = 0.0
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


def _xcorr_peak(chunk: np.ndarray, raw_fft: np.ndarray, raw_norm: np.ndarray, n_fft: int,
                lo_lag: int, hi_lag: int) -> tuple:
    """Best lag (samples into raw) and its normalised score within [lo, hi)."""
    c = chunk - chunk.mean()
    cn = np.linalg.norm(c) + 1e-6
    cf = np.fft.rfft(c, n_fft)
    corr = np.fft.irfft(np.conj(cf) * raw_fft, n_fft)
    lo_lag = max(0, lo_lag)
    hi_lag = min(len(raw_norm), hi_lag)
    if hi_lag <= lo_lag:
        return lo_lag, 0.0
    seg = corr[lo_lag:hi_lag] / (cn * raw_norm[lo_lag:hi_lag])
    i = int(np.argmax(seg))
    return lo_lag + i, float(seg[i])


def recover(edited_wav: str, raw_wav: str, chunk_ms: int = 1500, step_ms: int = 500,
            min_score: float = 0.35, jump_tolerance_ms: int = 40) -> tuple:
    """(runs, track): runs of the edit inside the raw take, and the
    per-chunk ``(edited_ms, offset_ms, score)`` track behind them."""
    e, rate = read_wav(edited_wav)
    r, rate_r = read_wav(raw_wav)
    assert rate == rate_r
    e, r = _bandpass(e, rate), _bandpass(r, rate)
    n = int(rate * chunk_ms / 1000)
    step = int(rate * step_ms / 1000)
    n_fft = 1 << int(np.ceil(np.log2(len(r) + n)))
    raw_fft = np.fft.rfft(r, n_fft)
    # Sliding L2 norm of raw windows of length n (for normalised scores).
    csum = np.concatenate([[0.0], np.cumsum(r.astype(np.float64) ** 2)])
    raw_norm = np.sqrt(np.maximum(csum[n:] - csum[:-n], 1e-12)) + 1e-6
    max_extra = len(r) - len(e)

    track = []
    prev_lag_off = 0
    for start in range(0, len(e) - n, step):
        chunk = e[start: start + n]
        if np.sqrt(np.mean(chunk ** 2)) < 1e-3:       # silence: no information
            track.append((start, None, 0.0))
            continue
        # Offsets only grow (material is only ever removed): search from a
        # little before the previous offset to the end.
        lag, score = _xcorr_peak(chunk, raw_fft, raw_norm, n_fft,
                                 start + prev_lag_off - rate // 5, start + max_extra + 1)
        if score < min_score:
            track.append((start, None, score))
            continue
        off = lag - start
        track.append((start, off, score))
        prev_lag_off = off

    # Fill silent/uncertain chunks from the previous confident one.
    filled = []
    last = None
    for start, off, score in track:
        if off is None:
            off = last
        else:
            last = off
        filled.append((start, off, score))
    first = next(o for _, o, _ in filled if o is not None)
    filled = [(s, first if o is None else o, sc) for s, o, sc in filled]

    to_ms = lambda samples: int(round(samples * 1000.0 / rate))
    runs = []
    cur_start, cur_off = 0, filled[0][1]
    for start, off, _ in filled[1:]:
        # The edit only removes material, so the offset never shrinks: a
        # drop is correlation noise (a silent tail) and is ignored.
        if off > cur_off + rate * jump_tolerance_ms // 1000:
            runs.append(Run(to_ms(cur_start), to_ms(start), to_ms(cur_off)))
            cur_start, cur_off = start, off
    runs.append(Run(to_ms(cur_start), to_ms(len(e)), to_ms(cur_off)))
    return runs, [(to_ms(s), None if o is None else to_ms(o), sc) for s, o, sc in track]
