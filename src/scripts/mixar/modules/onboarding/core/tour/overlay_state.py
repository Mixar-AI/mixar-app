# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — per-beat overlay bookkeeping.

Turns a beat's static ``Overlay`` rows plus the current video ms into
"what is visible right now, how far revealed, and where the one fake
cursor should be". Pure Python (no bpy): the session feeds it resolved
anchor rects and wall time; it never resolves anything itself.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from .beats import OVERLAY_CURSOR, OVERLAY_HINT, OVERLAY_SCRIBBLE, Beat
from .config import SCRIBBLE_REVEAL_SECONDS


@dataclass
class OverlayView:
    overlay: object                 # beats.Overlay
    rect: Optional[tuple]           # (xmin, ymin, xmax, ymax) window px, or None
    window_ptr: Optional[int]
    reveal: float                   # 0..1 since first visible


@dataclass
class CursorCommand:
    """What the session should do with the CursorAnim this tick."""
    visible: bool
    x: float = 0.0
    y: float = 0.0
    window_ptr: Optional[int] = None
    orbit: bool = False
    orbit_radius: float = 0.0
    pulse: bool = False             # trigger a click pulse now


@dataclass
class BeatOverlayState:
    beat: Optional[Beat] = None
    first_visible_wall: dict = field(default_factory=dict)   # overlay id → wall s
    clicked: set = field(default_factory=set)                # overlay ids whose click fired

    def reset(self, beat: Optional[Beat]) -> None:
        self.beat = beat
        self.first_visible_wall = {}
        self.clicked = set()

    @staticmethod
    def _is_visible(ov, ms: int) -> bool:
        if ov.appear_ms is not None and ms < ov.appear_ms:
            return False
        if ov.disappear_ms is not None and ms >= ov.disappear_ms:
            return False
        return True

    def compute(
        self,
        ms: int,
        wall: float,
        resolve: Callable[[dict], Optional[tuple]],
        host_rect: tuple,
        host_window_ptr: Optional[int],
        orbit_radius: float,
    ):
        """Return ``(views, cursor_command)``.

        ``resolve(spec)`` → ``(rect, window_ptr)`` or ``None``. ``host_rect``
        is the main window's host region rect, used for ``at_pct``
        fallbacks.
        """
        views = []
        cursor_cmd = CursorCommand(visible=False)
        beat = self.beat
        if beat is None:
            return views, cursor_cmd

        active_cursor = None
        for ov in beat.overlays:
            if not self._is_visible(ov, ms):
                self.first_visible_wall.pop(ov.id, None)
                continue
            if ov.id not in self.first_visible_wall:
                self.first_visible_wall[ov.id] = wall
            reveal = min(1.0, (wall - self.first_visible_wall[ov.id])
                         / SCRIBBLE_REVEAL_SECONDS)

            rect = None
            window_ptr = None
            if ov.anchor:
                resolved = resolve(ov.anchor)
                if resolved is not None:
                    rect, window_ptr = resolved
            if rect is None and ov.at_pct is not None:
                xmin, ymin, xmax, ymax = host_rect
                px, py = ov.at_pct
                x = xmin + (xmax - xmin) * px / 100.0
                y = ymin + (ymax - ymin) * py / 100.0
                rect = (x - 1, y - 1, x + 1, y + 1)
                window_ptr = host_window_ptr

            if ov.kind == OVERLAY_CURSOR:
                # The last visible cursor row wins: rows are authored in
                # time order, so a later "appear" supersedes an earlier one.
                active_cursor = (ov, rect, window_ptr)
                continue
            if rect is None:
                continue
            views.append(OverlayView(ov, rect, window_ptr, reveal))

        if beat.hide_cursor or active_cursor is None:
            return views, cursor_cmd

        ov, rect, window_ptr = active_cursor
        if rect is None:
            return views, cursor_cmd
        cx = (rect[0] + rect[2]) * 0.5
        cy = (rect[1] + rect[3]) * 0.5
        pulse = False
        if ov.click_ms is not None and ms >= ov.click_ms and ov.id not in self.clicked:
            self.clicked.add(ov.id)
            pulse = True
        radius = 0.0
        if ov.orbit:
            radius = max(orbit_radius,
                         min(rect[2] - rect[0], rect[3] - rect[1]) * 0.18)
        cursor_cmd = CursorCommand(
            visible=True, x=cx, y=cy, window_ptr=window_ptr,
            orbit=ov.orbit, orbit_radius=radius, pulse=pulse,
        )
        return views, cursor_cmd


def views_for_window(views, window_ptr: Optional[int]):
    return [v for v in views if v.window_ptr == window_ptr]


def scribble_views(views):
    return [v for v in views if v.overlay.kind == OVERLAY_SCRIBBLE]


def hint_views(views):
    return [v for v in views if v.overlay.kind == OVERLAY_HINT]
