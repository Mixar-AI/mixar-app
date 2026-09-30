# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — a language pack's video, played as one timeline.

A pack is eight ``part-<k>.mp4`` files cut at act boundaries. ``PartsMovie``
presents them with the ``MovieTexture`` interface the session already
uses: ``texture_for_ms(ms)`` in absolute pack time, ``duration_ms``,
``close()``. It keeps at most two ``MovieTexture`` objects alive: the part
being shown and the next one, opened a little before its boundary.

``prepare(ms)`` — called from the session's TICK, never from a draw
callback — opens/closes parts (``bpy.data.images.load`` is a data write).
``texture_for_ms`` only ever touches parts ``prepare`` already opened, so a
draw between the boundary and the next tick shows the previous part's last
frame rather than failing.

The narration is not segmented: ``clock.AudClock`` joins the parts' audio
into one sound, so absolute pack time is the audio handle's time.
"""

import bisect
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger

from .video import MovieTexture

logger = get_logger(__name__)

PREOPEN_AHEAD_MS = 1500


class PartsMovie:
    def __init__(self, parts: List[Tuple[int, int, str]], ready=None):
        """``parts``: ``(start_ms, end_ms, path)`` contiguous, in order;
        ``ready(k)`` says whether part ``k`` is on disk yet (a pack may still
        be downloading; a missing part is simply not opened until it is)."""
        if not parts:
            raise RuntimeError("no parts")
        self.parts = list(parts)
        self._ready = ready or (lambda k: True)
        self.starts = [p[0] for p in self.parts]
        self.duration_ms = int(self.parts[-1][1])
        self.width = self.height = 0
        self._open = {}          # part index -> MovieTexture
        self._current = None     # index whose texture was last returned

    def _index(self, ms: int) -> int:
        i = bisect.bisect_right(self.starts, max(0, int(ms))) - 1
        return max(0, min(i, len(self.parts) - 1))

    def _ensure(self, i: int) -> Optional[MovieTexture]:
        tex = self._open.get(i)
        if tex is None:
            if not self._ready(i):
                return None
            try:
                tex = MovieTexture(self.parts[i][2])
            except Exception as exc:  # noqa: BLE001
                logger.warning("PartsMovie: part %d failed to open: %s", i, exc)
                return None
            self._open[i] = tex
            if not self.width:
                self.width, self.height = tex.width, tex.height
        return tex

    def prepare(self, ms: int) -> None:
        """Open the part for ``ms`` (and the next one when close), close the rest."""
        i = self._index(ms)
        wanted = {i}
        if i + 1 < len(self.parts) and self.parts[i][1] - ms <= PREOPEN_AHEAD_MS:
            wanted.add(i + 1)
        if not self._ready(i):
            # Holding for a part still downloading: keep whatever is open so
            # the card shows a held frame under the loading line, not black.
            return
        for j in list(self._open):
            if j not in wanted:
                self._open.pop(j).close()
        for j in sorted(wanted):
            self._ensure(j)

    def texture_for_ms(self, ms: int):
        i = self._index(ms)
        tex = self._open.get(i)
        if tex is None:
            # Not prepared yet: hold the last shown part's frame.
            if self._current is not None and self._current in self._open:
                prev = self._open[self._current]
                return prev.texture_for_ms(prev.duration_ms)
            return None
        self._current = i
        return tex.texture_for_ms(int(ms) - self.parts[i][0])

    def close(self) -> None:
        for tex in self._open.values():
            tex.close()
        self._open.clear()
        self._current = None
