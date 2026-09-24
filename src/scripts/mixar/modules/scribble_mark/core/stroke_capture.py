# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The strokes under the pen — capture rules, with no ``bpy`` in sight.

The mark modal owns the freeze, the overlay and the reporting; this owns
what a pointer sample does to the ink. Keeping the two apart is what lets
the sampling and grouping rules — the ones that decide how faithfully a
drawn line survives — be exercised by the standalone suite instead of only
by hand on a tablet.

Three rules live here:

- **Samples are decimated by DISTANCE, radially.** A per-axis box test
  accepts a 2 px step along an axis and rejects a 2.8 px step across the
  diagonal, so the same hand speed left a different density of ink depending
  on which way the stroke ran. The handwriting canvas measures the same
  threshold radially (``INK_MIN_SAMPLE_DIST``), so the two halves of one
  mode now agree about what "2 px apart" means.
- **A full stroke is HALVED, never truncated.** Dropping the tail loses the
  end of a long line with nothing on screen to say so. Halving in place
  keeps the whole path at half the sample density — still finer than
  anything downstream keeps — and the buffer never grows.
- **Strokes group by pen-up pause.** The buffer only records when the pen
  last lifted; the modal decides what to do about it.

The point lists are handed out by reference (the overlay draws them and the
halving mutates them in place), which is why every mutation here is in
place rather than by rebinding.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]


class StrokeBuffer:
    """The ink of the mark being drawn."""

    def __init__(self, max_strokes: int, max_points: int):
        self._max_strokes = max(1, int(max_strokes))
        self._max_points = max(2, int(max_points))
        self._strokes: List[List[Point]] = []
        self._live: Optional[List[Point]] = None
        self._last_up = 0.0

    # -- state -----------------------------------------------------------

    @property
    def strokes(self) -> List[List[Point]]:
        """The strokes drawn so far, by reference — the overlay draws these."""
        return self._strokes

    @property
    def drawing(self) -> bool:
        """True while the pen is down on a stroke."""
        return self._live is not None

    @property
    def empty(self) -> bool:
        return not self._strokes

    @property
    def full(self) -> bool:
        """True when another stroke would not fit — the caller commits the
        group and starts a new one rather than dropping ink."""
        return len(self._strokes) >= self._max_strokes

    def idle_for(self, now: float) -> float:
        """Seconds since the pen last lifted."""
        return now - self._last_up

    # -- capture ---------------------------------------------------------

    def begin(self, point: Point) -> None:
        """Start a stroke at *point*. Check ``full`` first."""
        self._live = [point]
        self._strokes.append(self._live)

    def extend(self, point: Point, min_distance: float) -> bool:
        """Add *point* to the live stroke. False when it was too close to the
        last sample to carry any new shape (or the pen is up)."""
        stroke = self._live
        if stroke is None:
            return False
        last = stroke[-1]
        dx = point[0] - last[0]
        dy = point[1] - last[1]
        if dx * dx + dy * dy < min_distance * min_distance:
            return False
        if len(stroke) >= self._max_points:
            # In place: the overlay holds this list by reference.
            stroke[:] = stroke[::2]
        stroke.append(point)
        return True

    def end(self, now: float) -> None:
        """Lift the pen. Idempotent — a release with nothing live still
        restarts the grouping clock, which is what a missed release needs."""
        self._live = None
        self._last_up = now

    # -- handover --------------------------------------------------------

    def take(self) -> List[List[Point]]:
        """Hand the group over and start an empty one.

        The returned lists are the same objects the caller has been drawing,
        so nothing is copied on the commit path.
        """
        strokes = self._strokes
        self._strokes = []
        self._live = None
        return strokes

    def clear(self) -> None:
        """Drop the ink drawn so far (undo of a half-finished gesture)."""
        self._strokes = []
        self._live = None


def stroke_points(strokes: Sequence[Sequence[Point]]) -> int:
    """Total samples across *strokes* — for budgets and diagnostics."""
    return sum(len(stroke) for stroke in strokes)
