# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SubRip helpers for the pack builder: read a dub's cue times, and re-time
its cues onto the English edit for the bundled English-timed subtitles.

A subtitle shown while the tour waits at a gate must be the gated line,
never the next one: English playback freezes at the gate's clip end, so a
cue covering that moment stays on screen for the whole pause.
``gate_safe`` moves such a cue to the side of the gate it mostly belongs to.
"""

import re

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
MIN_CUE_MS = 300


def _srt_ms(m) -> int:
    h, mi, s, f = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + int((f + "000")[:3])


def fmt(ms: int) -> str:
    ms = max(0, int(ms))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def read_blocks(path: str) -> list:
    """[[start_ms, end_ms, [text lines]]] in file order."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        text = fh.read().replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        ti = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ti is None:
            continue
        times = list(_SRT_TIME.finditer(lines[ti]))
        if len(times) >= 2:
            out.append([_srt_ms(times[0]), _srt_ms(times[1]), lines[ti + 1:]])
    return out


def write_blocks(path: str, blocks: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(f"{i}\n{fmt(a)} --> {fmt(b)}\n" + "\n".join(text)
                             for i, (a, b, text) in enumerate(blocks, 1)) + "\n")


def read_srt_cues(path: str) -> list:
    """[(start_ms, end_ms)] from a SubRip file, sorted."""
    return sorted((a, b) for a, b, _text in read_blocks(path))


def gates_of(tour) -> list:
    """[(clip_end_ms, next_enter_ms)] of every gated beat."""
    beats = tour.beats
    return [(b.clip_end_ms, beats[i + 1].enter_ms)
            for i, b in enumerate(beats[:-1]) if b.gate is not None]


def gate_safe(blocks: list, gates: list) -> list:
    """No cue may cover a gate's clip end. A cue mostly after it starts at
    the next beat's entry; one mostly before it ends at the clip end."""
    for clip_end, next_enter in gates:
        for cue in blocks:
            a, b = cue[0], cue[1]
            if not a <= clip_end < b:
                continue
            if b - clip_end > clip_end - a and b - max(a, next_enter) >= MIN_CUE_MS:
                cue[0] = max(a, next_enter)
            else:
                cue[1] = clip_end
    return [c for c in blocks if c[1] - c[0] >= MIN_CUE_MS]


def retime_srt(src: str, dst: str, to_founder, gates: list = ()) -> int:
    """Rewrite cue times through ``to_founder(raw_dub_ms) -> founder_ms``;
    cues that collapse into a cut are dropped, and none is left covering a
    gate (``gate_safe``). Returns the cue count."""
    blocks = [[to_founder(a), to_founder(b), text] for a, b, text in read_blocks(src)]
    blocks = gate_safe([c for c in blocks if c[1] - c[0] >= MIN_CUE_MS], gates)
    write_blocks(dst, blocks)
    return len(blocks)
