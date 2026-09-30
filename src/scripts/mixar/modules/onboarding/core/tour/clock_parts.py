# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — a language pack's parts as one clock.

Split out of ``clock.py`` for size; ``clock.make_clock`` builds these when
given a parts list. See ``PartsClock``.
"""

from typing import Optional

from mixar.config.logging_config import get_logger

from .clock import AudClock, BaseClock, WallClock

logger = get_logger(__name__)


class PartsClock(BaseClock):
    """A language pack's parts as one timeline, one ``AudClock`` at a time.

    ``parts`` are ``(start_ms, end_ms, path)``; ``ready(k)`` says whether
    part ``k`` is on disk yet (it may still be downloading). Absolute time
    is ``part.start + inner position``. When the current part ends the next
    one starts if it is ready; otherwise the clock **holds** one ms before
    that part and reports ``waiting`` — the runner sees no progress and the
    session shows a loading card — until a later ``position_ms`` finds the
    part ready. Seeks land in the part they belong to (held there if that
    part is missing). Falls back to a silent wall clock for a part whose
    audio cannot open, so a broken file never strands the tour.
    """

    def __init__(self, parts, duration_ms: Optional[int] = None, rate: float = 1.0,
                 ready=None):
        super().__init__(duration_ms if duration_ms is not None else int(parts[-1][1]), rate)
        self.parts = list(parts)
        self._ready = ready or (lambda k: True)
        self._k = -1
        self._inner: Optional[BaseClock] = None
        self.waiting = False
        self.paused = True
        self._open(0)

    # -- parts -----------------------------------------------------------

    def _index_for(self, ms: int) -> int:
        for k, (start, end, _p) in enumerate(self.parts):
            if ms < end:
                return k
        return len(self.parts) - 1

    def _open(self, k: int, inner_ms: int = 0) -> bool:
        """Switch to part ``k`` at ``inner_ms`` (paused); False when the
        part is not ready, in which case the clock holds before it."""
        if not self._ready(k):
            self._close_inner()
            self._k = k
            self.waiting = True
            self._last_ms = max(self._last_ms, max(0, self.parts[k][0] - 1))
            return False
        start, end, path = self.parts[k]
        self._close_inner()
        try:
            inner = AudClock(path, end - start, rate=self.rate)
        except RuntimeError as exc:
            logger.warning("PartsClock: part %d silent (%s)", k, exc)
            inner = WallClock(end - start, rate=self.rate)
        if inner_ms > 0:
            inner.seek_ms(inner_ms)
        self._inner, self._k, self.waiting = inner, k, False
        self._last_ms = start + inner_ms
        return True

    def _close_inner(self) -> None:
        inner, self._inner = self._inner, None
        if inner is not None:
            inner.close()

    def _advance_if_ended(self) -> None:
        """Called from ``position_ms``: cross into the next part, or hold."""
        if self.waiting:
            if self._open(self._k) and not self.paused:
                self._inner.resume()
            return
        inner = self._inner
        if inner is None:
            return
        if inner.ended() and self._k + 1 < len(self.parts):
            was_paused = self.paused
            if self._open(self._k + 1) and not was_paused:
                self._inner.resume()

    # -- interface -------------------------------------------------------

    def position_ms(self) -> int:
        self._advance_if_ended()
        if self.waiting or self._inner is None:
            return self._clamp(self._last_ms)
        return self._clamp(self.parts[self._k][0] + self._inner.position_ms())

    def pause(self) -> None:
        if self.paused:
            return
        self.position_ms()
        self.paused = True
        if self._inner is not None:
            self._inner.pause()

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        if self._inner is not None and not self.waiting:
            self._inner.resume()

    def seek_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        k = self._index_for(ms)
        was_paused = self.paused
        if self._open(k, ms - self.parts[k][0]):
            self._last_ms = ms
            if not was_paused:
                self._inner.resume()
        else:
            self._last_ms = max(0, self.parts[k][0] - 1)

    def set_rate(self, rate: float) -> None:
        if not rate or rate <= 0:
            return
        self.rate = float(rate)
        if self._inner is not None:
            self._inner.set_rate(self.rate)

    def ended(self) -> bool:
        if self.waiting:
            return False
        if self._k == len(self.parts) - 1 and self._inner is not None:
            return self._inner.ended()
        return False

    def close(self) -> None:
        self.paused = True
        self._close_inner()



class SilentPartsClock(PartsClock):
    """``PartsClock`` whose parts are wall clocks (no audio device)."""

    def _open(self, k: int, inner_ms: int = 0) -> bool:
        if not self._ready(k):
            self._close_inner()
            self._k = k
            self.waiting = True
            self._last_ms = max(self._last_ms, max(0, self.parts[k][0] - 1))
            return False
        start, end, _path = self.parts[k]
        self._close_inner()
        inner = WallClock(end - start, rate=self.rate)
        if inner_ms > 0:
            inner.seek_ms(inner_ms)
        self._inner, self._k, self.waiting = inner, k, False
        self._last_ms = start + inner_ms
        return True
