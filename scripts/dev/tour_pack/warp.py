# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Time warp between the raw English take and a lip-synced dub.

The dub is the English footage re-timed per sentence (the mouth is
regenerated, everything else is the same frames played faster or slower),
so a monotonic frame alignment of the two videos gives the mapping
``english_ms -> dub_ms`` independent of language. Frames are tiny
grayscale tracks (``ffmpeg -vf fps=10,scale=48:27,format=gray``) and the
alignment is plain dynamic time warping on frame difference with a
Sakoe-Chiba band, so a 3-minute take aligns in seconds.
"""

from dataclasses import dataclass

import numpy as np

W, H, FPS = 48, 27, 10


def load_track(path: str, w: int = W, h: int = H) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    n = len(data) // (w * h)
    frames = data[: n * w * h].reshape(n, h * w).astype(np.float32) / 255.0
    # Per-frame normalisation removes the dub's global grade differences.
    frames -= frames.mean(axis=1, keepdims=True)
    frames /= (np.linalg.norm(frames, axis=1, keepdims=True) + 1e-6)
    return frames


@dataclass
class Warp:
    """Piecewise-linear ``english_ms -> dub_ms`` through alignment anchors."""
    english_ms: np.ndarray
    dub_ms: np.ndarray

    def to_dub(self, english_ms) -> float:
        return float(np.interp(english_ms, self.english_ms, self.dub_ms))

    def to_english(self, dub_ms) -> float:
        return float(np.interp(dub_ms, self.dub_ms, self.english_ms))


def dtw_path(a: np.ndarray, b: np.ndarray, band: int = 150) -> list:
    """Monotonic path of (i, j) pairs minimising summed frame distance.
    ``band`` is the max |i*len(b)/len(a) - j| in frames (15 s at 10 fps)."""
    n, m = len(a), len(b)
    sim = a @ b.T                          # cosine similarity in [-1, 1]
    cost = 1.0 - sim
    INF = np.inf
    D = np.full((n + 1, m + 1), INF, dtype=np.float64)
    D[0, 0] = 0.0
    slope = m / n
    for i in range(1, n + 1):
        jc = int(i * slope)
        lo, hi = max(1, jc - band), min(m, jc + band)
        ci = cost[i - 1, lo - 1:hi]
        prev_diag = D[i - 1, lo - 1:hi]
        prev_up = D[i - 1, lo:hi + 1]
        best = np.minimum(prev_diag, prev_up)
        row = best + ci
        # Left moves (repeat an English frame) need a sequential pass.
        for k in range(len(row)):
            j = lo + k
            left = D[i, j - 1] + ci[k]
            D[i, j] = row[k] if row[k] <= left else left
    # Backtrack.
    i, j = n, m
    path = []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        cands = ((D[i - 1, j - 1], i - 1, j - 1), (D[i - 1, j], i - 1, j), (D[i, j - 1], i, j - 1))
        _, i, j = min(cands)
    path.reverse()
    return path, float(D[n, m] / len(path))


def warp_from_path(path: list, fps: int = FPS, anchor_every: int = 5) -> Warp:
    """Thin the path to anchors (median dub frame per English frame)."""
    by_i = {}
    for i, j in path:
        by_i.setdefault(i, []).append(j)
    xs, ys = [], []
    for i in sorted(by_i):
        if i % anchor_every == 0 or i == max(by_i):
            xs.append(i * 1000.0 / fps)
            ys.append(float(np.median(by_i[i])) * 1000.0 / fps)
    return Warp(np.array(xs), np.array(ys))


def align(english_track: str, dub_track: str, band: int = 150) -> tuple:
    a, b = load_track(english_track), load_track(dub_track)
    path, mean_cost = dtw_path(a, b, band=band)
    return warp_from_path(path), mean_cost
