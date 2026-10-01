# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-language tour plan: the dub's cut list and its beat timing table.

Every number in ``script.py`` is *founder time* (the edited English take).
A dub is the same footage re-timed per sentence with translated speech, so
founder time reaches dub time through three maps:

    founder ──cut list──▶ raw English ──video warp──▶ raw dub ──dub cut──▶ edited dub

* The **cut list** (``cutlist.recover``) says which runs of the raw English
  take the edit kept.
* The **video warp** (``warp.align``) maps raw English to raw dub frames.
* The **dub cut** keeps, for every English run, the dub material around the
  same speech with the same silent lead/tail the English edit kept, so the
  gates land in the same kind of pause. Beat boundaries snap to the dub's
  own speech onsets/ends (the warp is frame-accurate for the picture, the
  audio decides where a word actually starts).

The English take ends on the Mixar logo card, which the dubs lack; the
plan appends the English card after the dub's last line, freezing the last
dub frame if the dub has less presenter tail than the English take.
"""

import json
import sys
from dataclasses import dataclass, asdict

import numpy as np

import audio
import cutlist
import warp as warp_mod

SNAP_MS = 600          # how far a beat boundary may move to meet a dub speech edge
NEAR_MS = 400          # how close a founder time must be to an English speech edge to count as one
THRESHOLD_DB = -40.0
MIN_GAP_MS = 250
FADE_MS = 25


def _snap_ms(ms: float, fps: float) -> int:
    """Nearest source frame boundary."""
    frame = 1000.0 / fps
    return int(round(round(ms / frame) * frame))


@dataclass
class Run:
    src_start_ms: int      # in raw dub time
    src_end_ms: int
    out_start_ms: int      # in edited dub time
    freeze_ms: int = 0     # tpad after this run (presenter tail shorter than English)

    @property
    def duration_ms(self) -> int:
        return self.src_end_ms - self.src_start_ms + self.freeze_ms


class Founder:
    """The English edit: cut list + speech segments in both time bases."""

    def __init__(self, founder_wav: str, english_wav: str):
        runs, _ = cutlist.recover(founder_wav, english_wav, step_ms=100)
        self.speech = audio.analyse(founder_wav, threshold_db=THRESHOLD_DB, min_gap_ms=MIN_GAP_MS)
        self.duration_ms = runs[-1].edited_end_ms
        self.runs = self._snap_cuts_to_pauses(runs)

    def _snap_cuts_to_pauses(self, runs, within_ms: int = 1500):
        """The correlation places a cut within a chunk of the truth; the
        real cut is inside the pause between two lines. Move each boundary
        to the middle of the nearest speech gap."""
        gaps = [(a.end_ms, b.start_ms) for a, b in zip(self.speech, self.speech[1:])]
        out = []
        for a, b in zip(runs, runs[1:]):
            boundary = a.edited_end_ms
            best = min(gaps, key=lambda g: abs((g[0] + g[1]) * 0.5 - boundary))
            mid = int((best[0] + best[1]) * 0.5)
            if abs(mid - boundary) <= within_ms:
                boundary = mid
            start = out[-1].edited_end_ms if out else a.edited_start_ms
            out.append(cutlist.Run(start, boundary, a.raw_offset_ms))
        last = runs[-1]
        start = out[-1].edited_end_ms if out else last.edited_start_ms
        out.append(cutlist.Run(start, last.edited_end_ms, last.raw_offset_ms))
        return out

    def to_raw(self, founder_ms: float) -> float:
        for r in self.runs:
            if r.edited_start_ms <= founder_ms < r.edited_end_ms or r is self.runs[-1]:
                return founder_ms + r.raw_offset_ms
        return founder_ms + self.runs[0].raw_offset_ms

    def to_founder(self, raw_ms: float) -> float:
        for r in self.runs:
            if r.raw_start_ms <= raw_ms < r.raw_end_ms:
                return raw_ms - r.raw_offset_ms
            if raw_ms < r.raw_start_ms:          # in dropped material: clamp to the cut
                return r.edited_start_ms
        return self.duration_ms

    def speech_edge_near(self, founder_ms: float, kind: str):
        """The onset (kind='start') or end (kind='end') of an English speech
        segment within NEAR_MS of ``founder_ms``, or None."""
        best, best_d = None, NEAR_MS + 1
        for s in self.speech:
            edge = s.start_ms if kind == "start" else s.end_ms
            d = abs(edge - founder_ms)
            if d < best_d:
                best, best_d = edge, d
        return best


class Dub:
    def __init__(self, code: str, wav: str, track: str, english_track: str, fps: float,
                 duration_ms: int):
        self.code = code
        self.fps = fps
        self.duration_ms = duration_ms
        self.warp, self.warp_cost = warp_mod.align(english_track, track)
        self.speech = audio.analyse(wav, threshold_db=THRESHOLD_DB, min_gap_ms=MIN_GAP_MS)
        samples, rate = audio.read_wav(wav)
        self.db = audio.rms_db(samples, rate)

    def speech_edge_near(self, dub_ms: float, kind: str, within: int = SNAP_MS):
        best, best_d = None, within + 1
        for s in self.speech:
            edge = s.start_ms if kind == "start" else s.end_ms
            d = abs(edge - dub_ms)
            if d < best_d:
                best, best_d = edge, d
        return best

    def last_speech_end(self) -> int:
        return self.speech[-1].end_ms

    def gaps(self, min_ms: int = 150) -> list:
        """Silences between consecutive speech segments: (start_ms, end_ms)."""
        out = []
        for a, b in zip(self.speech, self.speech[1:]):
            if b.start_ms - a.end_ms >= min_ms:
                out.append((a.end_ms, b.start_ms))
        return out

    def choose_gap(self, center_ms: float, after_ms: float, window_ms: int = 700,
                   raw_english_gap=None, slack_ms: int = 350):
        """The silence that corresponds to an English cut whose warped
        centre is ``center_ms``: the longest gap overlapping the window
        (penalised by distance), strictly after ``after_ms`` so the runs
        stay in order. A candidate must also map back through the picture
        warp into the English silence ``raw_english_gap`` (± slack): a dub
        that pauses one phrase later than English must not have that pause
        mistaken for this cut. None when the dub has no pause here."""
        best, best_score = None, None
        for g in self.gaps():
            if g[0] <= after_ms:
                continue
            gc = (g[0] + g[1]) * 0.5
            if g[1] < center_ms - window_ms or g[0] > center_ms + window_ms:
                continue
            if raw_english_gap is not None:
                back = self.warp.to_english(gc)
                if not (raw_english_gap[0] - slack_ms <= back <= raw_english_gap[1] + slack_ms):
                    continue
            score = (g[1] - g[0]) - 0.4 * abs(gc - center_ms)
            if best_score is None or score > best_score:
                best, best_score = g, score
        return best



# ---------------------------------------------------------------------------
# Cue-based planning.
#
# The dubs do not pause where the English take paused (a dubbing voice runs
# two English lines into one phrase, or breaks one line in two), so the
# English cut list cannot be replayed. The dub's own subtitle cues are its
# line structure; each cue is assigned to the English beat whose window its
# midpoint warps back into (monotonically), and the pause rules the English
# edit followed are applied to the dub's own silences.
# ---------------------------------------------------------------------------

PAUSE_TRIM_MS = 900        # silences longer than this are trimmed…
PAUSE_KEEP_MS = 750        # …to this,
GATE_PAUSE_MS = 1100       # or this after a line the tour waits on
GATE_CLIP_TAIL_MS = 500    # script rule: a gated beat ends last word + 500 ms
ENTER_LEAD_MS = 150        # script rule: a beat enters 150 ms before its first word
FADE_MS = 25


def read_srt_cues(path: str) -> list:
    """[(start_ms, end_ms)] from a SubRip file, sorted."""
    import re
    t = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
    with open(path, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    cues = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if "-->" not in line:
            continue
        m = list(t.finditer(line))
        if len(m) < 2:
            continue
        def ms(mm):
            h, mi, se, fr = mm.groups()
            return ((int(h) * 60 + int(mi)) * 60 + int(se)) * 1000 + int((fr + "000")[:3])
        cues.append((ms(m[0]), ms(m[1])))
    return sorted(cues)


def assign_cues(tour, founder: Founder, dub: Dub, cues: list) -> dict:
    """beat id -> [cue index, ...], every cue to exactly one beat, in order.

    A cue belongs to the beat whose founder window contains its back-warped
    midpoint; the assignment is forced monotonic (a cue never goes to an
    earlier beat than its predecessor) and every beat gets at least one cue
    by stealing the boundary cue from an over-full neighbour.
    """
    beats = tour.beats
    windows = [(b.enter_ms, b.clip_end_ms) for b in beats]
    idx_of = []
    last = 0
    for (cs, ce) in cues:
        mid_f = founder.to_founder(dub.warp.to_english((cs + ce) * 0.5))
        k = next((i for i, (a, z) in enumerate(windows) if a <= mid_f < z), None)
        if k is None:
            k = min(range(len(windows)), key=lambda i: min(abs(windows[i][0] - mid_f), abs(windows[i][1] - mid_f)))
        k = max(k, last)
        idx_of.append(k)
        last = k
    # Give an empty beat the nearest cue from a neighbour with more than one.
    changed = True
    while changed:
        changed = False
        for k in range(len(beats)):
            if k in idx_of:
                continue
            after = [i for i, v in enumerate(idx_of) if v > k]
            before = [i for i, v in enumerate(idx_of) if v < k]
            if after and idx_of.count(idx_of[after[0]]) > 1:
                idx_of[after[0]] = k
                changed = True
            elif before and idx_of.count(idx_of[before[-1]]) > 1:
                idx_of[before[-1]] = k
                changed = True
    out = {b.id: [] for b in beats}
    for i, k in enumerate(idx_of):
        out[beats[k].id].append(i)
    return out


def _founder_line_end(founder: Founder, b) -> int:
    """Last English word of the beat's line (founder time)."""
    inside = [sg.end_ms for sg in founder.speech if b.enter_ms < sg.end_ms <= b.clip_end_ms]
    return max(inside) if inside else b.clip_end_ms - GATE_CLIP_TAIL_MS


def _founder_line_start(founder: Founder, b) -> int:
    inside = [sg.start_ms for sg in founder.speech if b.enter_ms <= sg.start_ms < b.clip_end_ms]
    return min(inside) if inside else b.enter_ms + ENTER_LEAD_MS


def plan_dub(tour, founder: Founder, dub: Dub, cues: list, card_start_raw_en_ms: int):
    """Everything the renderer and the timing table need for one dub.

    Returns (runs, fn, total_ms, to_founder, lines) where ``fn`` maps
    founder ms → edited dub ms, ``to_founder`` maps raw dub ms → founder ms
    (for the subtitles), ``lines`` is the per-beat dub line table.
    """
    assigned = assign_cues(tour, founder, dub, cues)
    beats = tour.beats
    lines = []      # per beat: (onset_d, end_d) in raw dub time
    for b in beats:
        ids = assigned[b.id]
        cs = cues[ids[0]][0]
        ce = cues[ids[-1]][1]
        onset = dub.speech_edge_near(cs, "start", within=400) or cs
        end = dub.speech_edge_near(ce, "end", within=400) or ce
        if lines and onset < lines[-1][1]:
            onset = lines[-1][1]
        if end <= onset:
            end = onset + 200
        lines.append((int(onset), int(end)))
    gated = {b.id for b in beats if b.gate is not None}

    # Kept material: from the first line's lead to the last line's end plus
    # the English presenter tail; every silence between lines trimmed by
    # the rules. Silences INSIDE a beat's line (between its cues) are kept
    # unless longer than PAUSE_TRIM_MS, then trimmed like any other.
    first_lead = _founder_line_start(founder, beats[0]) - beats[0].enter_ms
    start = max(0, lines[0][0] - first_lead)
    runs = []
    cursor = _snap_ms(start, dub.fps)
    speech = [sg for sg in dub.speech if sg.end_ms > start]
    last_end_needed = lines[-1][1]
    # Pauses to enforce after each beat's line end.
    want_after = {}
    for b, (on, en) in zip(beats, lines):
        want_after[en] = GATE_PAUSE_MS if b.id in gated else None
    gate_ends = {en for b, (on, en) in zip(beats, lines) if b.id in gated}

    gaps = [(a.end_ms, b2.start_ms) for a, b2 in zip(speech, speech[1:])
            if b2.start_ms <= last_end_needed + 1]
    for g0, g1 in gaps:
        length = g1 - g0
        is_gate = any(abs(g0 - ge) <= 120 for ge in gate_ends)
        keep = GATE_PAUSE_MS if is_gate else PAUSE_KEEP_MS
        if length > PAUSE_TRIM_MS or (is_gate and length > keep):
            # Cut the middle: keep half the pause on each side.
            keep = min(keep, length)
            cut_a = _snap_ms(g0 + keep * 0.5, dub.fps)
            cut_b = _snap_ms(g1 - keep * 0.5, dub.fps)
            if cut_b > cut_a:
                runs.append(Run(cursor, cut_a, 0, 0))
                cursor = cut_b
        elif is_gate and length < keep:
            # Too short a pause after a gated line: hold the frame.
            mid = _snap_ms(g0 + length * 0.5, dub.fps)
            runs.append(Run(cursor, mid, 0, int(keep - length)))
            cursor = mid
    # Last run: presenter tail as in English, frozen if the dub is shorter.
    presenter_tail = founder.to_founder(card_start_raw_en_ms) - _founder_line_end(founder, beats[-1])
    want_end = lines[-1][1] + presenter_tail
    have_end = min(dub.duration_ms, want_end)
    runs.append(Run(cursor, _snap_ms(have_end, dub.fps), 0, int(max(0, want_end - have_end))))
    total = layout_runs(runs)
    card_f = founder.to_founder(card_start_raw_en_ms)
    card_len = founder.duration_ms - card_f

    # Anchors founder → edited dub: each beat's line start and end.
    pts = [(0, 0)]
    for b, (on, en) in zip(beats, lines):
        pts.append((_founder_line_start(founder, b), src_to_out(runs, on)))
        pts.append((_founder_line_end(founder, b), src_to_out(runs, en)))
    pts.append((card_f, total))
    pts.append((founder.duration_ms, total + card_len))
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], np.maximum.accumulate(ys[order])

    def fn(founder_ms: float) -> int:
        return int(round(float(np.interp(founder_ms, xs, ys))))

    # Raw dub → founder for the subtitles: the inverse of the same anchors,
    # expressed in raw dub time.
    rx = np.array([0] + [v for on, en in lines for v in (on, en)] + [dub.duration_ms], dtype=float)
    ry = np.array([0] + [v for b in beats for v in (_founder_line_start(founder, b), _founder_line_end(founder, b))]
                  + [founder.duration_ms], dtype=float)
    ry = np.maximum.accumulate(ry)

    def to_founder(raw_dub_ms: float) -> int:
        return int(round(float(np.interp(raw_dub_ms, rx, ry))))

    return runs, fn, int(total + card_len), to_founder, lines


def layout_runs(runs) -> int:
    out = 0
    for r in runs:
        r.out_start_ms = out
        out += r.duration_ms
    return out


def src_to_out(runs, src_ms: float) -> int:
    """Raw dub ms → edited ms (a dropped instant maps to the cut after it)."""
    for r in runs:
        if src_ms <= r.src_end_ms:
            return int(r.out_start_ms + max(0, src_ms - r.src_start_ms))
    last = runs[-1]
    return int(last.out_start_ms + (last.src_end_ms - last.src_start_ms))


def detect_card_start(english_track: str, after_ms: int, fps: int = warp_mod.FPS,
                      dark: float = 0.06) -> int:
    """First frame after ``after_ms`` whose mean luma stays dark: the fade
    into the Mixar logo card at the end of the English take."""
    data = np.fromfile(english_track, dtype=np.uint8)
    n = len(data) // (warp_mod.W * warp_mod.H)
    frames = data[: n * warp_mod.W * warp_mod.H].reshape(n, -1).astype(np.float32) / 255.0
    luma = frames.mean(axis=1)
    start = int(after_ms * fps / 1000)
    for i in range(start, n):
        if luma[i] < dark and (i + 5 >= n or luma[i:i + 5].max() < dark * 2):
            return int(i * 1000 / fps)
    return int(n * 1000 / fps)


def build_timing(tour, fn, total_ms: int, code: str, pack_version: int) -> dict:
    """The pack's ``timing.json``: every time in the beat table mapped
    through ``fn`` (founder → edited dub), monotonic per beat, the terminal
    beat ending where the English one does relative to the clip's end."""
    beats = {}
    prev_end = 0
    for i, b in enumerate(tour.beats):
        enter = max(prev_end, fn(b.enter_ms))
        terminal = i == len(tour.beats) - 1
        clip_end = total_ms - 50 if terminal else max(enter + 200, fn(b.clip_end_ms))
        lo, hi = enter, clip_end

        def inner(ms):
            if ms is None:
                return None
            return int(min(hi, max(lo, fn(ms))))

        entry = {"enter_ms": int(enter), "clip_end_ms": int(clip_end),
                 "actions": [inner(at) for at, _n, _a in b.actions],
                 "overlays": {}}
        for ov in b.overlays:
            o = {"appear_ms": inner(ov.appear_ms), "disappear_ms": inner(ov.disappear_ms),
                 "click_ms": inner(ov.click_ms)}
            if ov.rows:
                o["rows_ms"] = [inner(r[2]) if len(r) > 2 else None for r in ov.rows]
            entry["overlays"][ov.id] = o
        beats[b.id] = entry
        prev_end = clip_end
    return {"pack_version": pack_version, "code": code, "duration_ms": int(total_ms),
            "script_hash": script_hash(tour), "beats": beats}


def script_hash(tour) -> str:
    import hashlib
    ids = "|".join(b.id for b in tour.beats)
    return hashlib.sha256(ids.encode("utf-8")).hexdigest()[:16]


def act_boundaries(tour, timing: dict) -> list:
    """Edited-dub ms where each act starts (a new caption label)."""
    out, last = [], None
    for b in tour.beats:
        if b.label != last:
            out.append(timing["beats"][b.id]["enter_ms"])
            last = b.label
    return out


def gate_silence_report(tour, timing: dict, dub_db, runs, dub_fps, card_ms: int) -> list:
    """For every gated beat: peak dB of the dub audio inside the pause window
    around its clip_end (edited time). Frozen-frame padding and the logo
    card are silent by construction and count as -120 dB."""
    def src_at(edited_ms):
        for r in runs:
            if r.out_start_ms <= edited_ms < r.out_start_ms + (r.src_end_ms - r.src_start_ms):
                return r.src_start_ms + (edited_ms - r.out_start_ms)
        return None                          # inside a freeze or the card
    report = []
    for b in tour.beats:
        if b.gate is None:
            continue
        ce = timing["beats"][b.id]["clip_end_ms"]
        peak = -120.0
        for t in range(ce - 200, ce + 300, audio.FRAME_MS):
            src = src_at(t)
            if src is None:
                continue
            peak = max(peak, audio.level_in(dub_db, src, src + audio.FRAME_MS))
        report.append((b.id, ce, peak))
    return report
