# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — host-window input handling for ``TourSession``.

Split out of ``session.py`` to keep both under the file-size cap. Events
reach here only from the window the modal operator was started in; gates
that the user satisfies in the floating island window are detected by the
state predicates polled in ``session.tick`` instead, and the island's own
Escape asks for the exit dialog through ``request_exit_confirm``.

Keyboard: Escape → exit dialog, Space → pause/play, Right arrow → Next.
All three are consumed only while the pointer is over the host viewport,
so a text field elsewhere in the window keeps its keys.
"""

import time

from mixar.config.logging_config import get_logger

from . import config
from .overlays import card as card_ui

logger = get_logger(__name__)

# Input that moves the camera: the viewport gate counts these only.
_NAVIGATE_EVENTS = frozenset((
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSEZOOM", "MOUSEPAN",
))
# The Zen navigate gizmos (orbit ball, zoom, pan) are buttons in the dump.
_NAVIGATE_GIZMO_SPECS = (
    {"op": "view3d.rotate"}, {"op": "view3d.zoom"}, {"op": "view3d.move"},
)


class SessionInputMixin:
    """Mixed into ``TourSession``; relies on its attributes."""

    def handle_event(self, event) -> str:
        """Return 'RUNNING_MODAL' (consumed) or 'PASS_THROUGH'."""
        if not self.running or self._end_requested:
            return "PASS_THROUGH"
        et, val = event.type, event.value
        mx, my = event.mouse_x, event.mouse_y

        if self.exit_confirm:
            return self._handle_exit_confirm(et, val, mx, my)

        if val == "PRESS" and et in ("ESC", "SPACE", "RIGHT_ARROW") \
                and self._in_host(mx, my) and not self._host_lost:
            if et == "ESC":
                self.set_exit_confirm(True)
            elif et == "SPACE":
                self._control("pause")
            else:
                self._control("skip")
            return "RUNNING_MODAL"

        layout = self._card_layout
        hit = card_ui.hit_test(layout, mx, my) if layout else None
        if et == "MOUSEMOVE":
            self.hover = hit
            # Any part of the card (video included) reveals the controls.
            self._mouse = (mx, my)
            self._last_mouse_wall = time.monotonic()
            self.card_hovered = hit is not None
            return "PASS_THROUGH"
        if et == "LEFTMOUSE":
            if hit is not None:
                if val == "PRESS":
                    self._control(hit)
                return "RUNNING_MODAL"
            if val == "PRESS" and self._wants_viewport_input() \
                    and self._on_navigate_gizmo(mx, my):
                self.flags["viewport_interacted"] = True
            return "PASS_THROUGH"
        if et in _NAVIGATE_EVENTS and self._in_host(mx, my):
            self.flags["viewport_interacted"] = True
        return "PASS_THROUGH"

    def _handle_exit_confirm(self, et, val, mx, my) -> str:
        if et == "ESC" and val == "PRESS":
            self.set_exit_confirm(False)
            return "RUNNING_MODAL"
        if et == "LEFTMOUSE" and val == "PRESS" and self._exit_layout:
            hit = card_ui.hit_test_exit_confirm(self._exit_layout, mx, my)
            if hit == "continue":
                self.set_exit_confirm(False)
            elif hit == "exit":
                self.stop("exited")
            return "RUNNING_MODAL"
        if et == "MOUSEMOVE" and self._exit_layout:
            self._mouse = (mx, my)
            self._last_mouse_wall = time.monotonic()
            self.hover = card_ui.hit_test_exit_confirm(self._exit_layout, mx, my)
        return "RUNNING_MODAL"

    def _wants_viewport_input(self) -> bool:
        beat = self.runner.beat if self.runner else None
        return beat is not None and beat.gate is not None \
            and beat.gate.check == "viewport_interacted"

    def _on_navigate_gizmo(self, x, y) -> bool:
        """True when (x, y) is over one of the viewport navigate gizmos."""
        for spec in _NAVIGATE_GIZMO_SPECS:
            try:
                rect = self.anchor_cache.get(spec)
            except Exception:  # noqa: BLE001
                rect = None
            if rect is not None and rect.window_ptr == self._host_window_ptr \
                    and rect.contains(x, y):
                return True
        return False

    def _in_host(self, x, y) -> bool:
        xmin, ymin, xmax, ymax = self._host_rect
        return xmin <= x <= xmax and ymin <= y <= ymax

    def _control(self, name: str) -> None:
        if name in ("pause", "card"):
            # A click on the video itself toggles pause, like any player.
            self.runner.set_user_paused(not self.runner.user_paused)
        elif name == "speed":
            self._cycle_speed()
        elif name == "skip":
            self.runner.skip_beat()
        elif name == "exit":
            self.set_exit_confirm(True)

    def _cycle_speed(self) -> None:
        options = config.SPEED_OPTIONS
        try:
            i = options.index(round(self.clock.rate, 2))
        except ValueError:
            i = -1
        rate = options[(i + 1) % len(options)]
        try:
            self.clock.set_rate(rate)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: set_rate failed: %s", exc)

    def set_exit_confirm(self, shown: bool) -> None:
        """Show/hide the exit dialog; the tour pauses underneath it and
        resumes on Continue unless the user had paused it themselves."""
        if shown == self.exit_confirm:
            return
        self.exit_confirm = shown
        if shown:
            self._paused_before_confirm = self.runner.user_paused
            self.runner.set_user_paused(True)
        elif not getattr(self, "_paused_before_confirm", False):
            self.runner.set_user_paused(False)
        self.hover = None
        self.card_hovered = False
