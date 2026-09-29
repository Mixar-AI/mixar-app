# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — SubRip subtitles.

The bundled ``assets/tour/subtitles/<code>.srt`` files are re-timed to the
English edit by the pack tooling, so a cue's window is tour time in
milliseconds. Parsing is deliberately forgiving (BOM, CRLF, blank-line
runs, missing indices, ``.`` as the millisecond separator) because the
files come from several dubbing exports. Cue text keeps its line breaks:
the card wraps to the video width and honours them.

No ``bpy``: pure parsing plus ``cue_at``, so the fake-clock tests cover it.
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from mixar.config.logging_config import get_logger

from . import config

logger = get_logger(__name__)

_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_TIMING = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str            # lines joined with "\n"


@dataclass(frozen=True)
class Subtitles:
    code: str
    cues: tuple          # sorted by start_ms

    def cue_at(self, ms: int) -> Optional[Cue]:
        """The cue covering ``ms`` (the first one when two overlap)."""
        for cue in self.cues:
            if cue.start_ms <= ms < cue.end_ms:
                return cue
            if cue.start_ms > ms:
                break
        return None

    def text_at(self, ms: int) -> str:
        cue = self.cue_at(ms)
        return cue.text if cue is not None else ""


def _ms(h, m, s, frac) -> int:
    frac = (frac + "000")[:3]
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac)


def parse(text: str, code: str = "") -> Subtitles:
    """Parse SubRip text into ``Subtitles``; malformed blocks are skipped."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: List[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.rstrip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        # An index line is optional; the timing line is not.
        idx = 1 if len(lines) > 1 and _TIMING.match(lines[1]) else 0
        m = _TIMING.match(lines[idx])
        if m is None:
            continue
        start = _ms(*m.groups()[:4])
        end = _ms(*m.groups()[4:])
        body = "\n".join(lines[idx + 1:]).strip()
        if end <= start or not body:
            continue
        cues.append(Cue(start, end, body))
    cues.sort(key=lambda c: c.start_ms)
    return Subtitles(code, tuple(cues))


def subtitles_dir() -> str:
    return os.path.join(config.assets_dir(), config.SUBTITLES_DIR)


def path_for(code: str) -> str:
    return os.path.join(subtitles_dir(), f"{code}.srt")


def load(code: str) -> Optional[Subtitles]:
    """The bundled subtitles for ``code``, or None (missing/unreadable)."""
    path = path_for(code)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            subs = parse(fh.read(), code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tour subtitles: %s unreadable: %s", path, exc)
        return None
    if not subs.cues:
        logger.warning("tour subtitles: %s has no cues", path)
        return None
    return subs


def wrap(text: str, max_width: float, measure) -> List[str]:
    """Greedy word wrap honouring explicit line breaks. ``measure(str)``
    returns a pixel width. Scripts without spaces (Chinese, Japanese) wrap
    per character when a single "word" overflows."""
    out: List[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for word in words:
            cand = word if not line else f"{line} {word}"
            if measure(cand) <= max_width or not line and measure(word) <= max_width:
                line = cand
                continue
            if line:
                out.append(line)
                line = ""
            if measure(word) <= max_width:
                line = word
                continue
            # Break an overlong run per character.
            run = ""
            for ch in word:
                if measure(run + ch) <= max_width or not run:
                    run += ch
                else:
                    out.append(run)
                    run = ch
            line = run
        if line:
            out.append(line)
    return out or [""]
