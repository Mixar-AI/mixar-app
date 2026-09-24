# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — overlay drawing for ``TourSession``.

Split out of ``session.py`` for size: rings, hints, the success flash, the
fake cursor, callouts, the shortcut panel and the captions under the card.
Everything here runs inside a POST_PIXEL callback and only reads state
``tick()`` prepared.
"""

import math
import time

from . import config
from .beats import OVERLAY_CAPTION
from .overlay_state import (
    callout_views, hint_views, keys_views, scribble_views, views_for_window,
)
from .overlays import callout as callout_ui
from .overlays import card as card_ui
from .overlays import keys as keys_ui
from .overlays import scribble as scribble_ui


class SessionDrawMixin:
    """Mixed into ``TourSession``; relies on its attributes."""

    def _gate_pulse(self) -> float:
        """Breathing alpha for a gated ring (1.0 when not gated)."""
        if not self._gated:
            return 1.0
        period = max(0.1, config.GATE_RING_PULSE_SECONDS)
        wave = 0.5 * (1.0 + math.sin(2.0 * math.pi * time.monotonic() / period))
        return config.GATE_RING_PULSE_MIN + (1.0 - config.GATE_RING_PULSE_MIN) * wave

    def _draw_overlays(self, window_ptr, window_rect) -> None:
        views = views_for_window(self._views, window_ptr)
        pulse = self._gate_pulse()
        for v in scribble_views(views):
            scribble_ui.draw_scribble(v.rect, v.reveal, alpha=v.alpha * pulse,
                                      ui_scale=self._ui_scale, bounds=window_rect,
                                      starburst=self._gated)
        # Hints paint in EVERY region (clipped to each), like the rings:
        # an overlapping region such as the moodboard drawer paints after
        # the viewport, so a pill drawn only by the host region would be
        # buried under it.
        for v in hint_views(views):
            scribble_ui.draw_hint(v.overlay.text, v.rect, window_rect,
                                  ui_scale=self._ui_scale,
                                  alpha=min(1.0, v.reveal * 2) * v.alpha,
                                  side=v.overlay.side, accent=self._gated)
        self._draw_panels(views, window_rect)
        flash = self._gate_flash
        if flash is not None and flash[1] == window_ptr:
            t = (time.monotonic() - flash[2]) / max(0.05, config.GATE_DONE_FLASH_SECONDS)
            if t < 1.0:
                scribble_ui.draw_success_flash(flash[0], t, ui_scale=self._ui_scale,
                                               bounds=window_rect)
        # The fake cursor is the actor of automatic beats only; while the
        # user is asked to act, their own pointer is the only cursor.
        if not self._gated:
            self.cursor.draw(window_ptr)

    def _draw_panels(self, views, window_rect) -> None:
        """Callouts (beside a row of the open Help menu) and the shortcut
        panel; like hints they paint in every region, clipped to each."""
        for v in callout_views(views):
            ov = v.overlay
            callout_ui.draw_callout(ov.title, ov.text, ov.footer, v.rect, window_rect,
                                    ui_scale=self._ui_scale,
                                    alpha=min(1.0, v.reveal * 2) * v.alpha, side=ov.side)
        ms = self.runner.last_ms
        for v in keys_views(views):
            ov = v.overlay
            center = ((v.rect[0] + v.rect[2]) * 0.5, (v.rect[1] + v.rect[3]) * 0.5)
            keys_ui.draw_keys(ov.title, ov.rows, center, self._host_rect, ms,
                              ui_scale=self._ui_scale,
                              alpha=min(1.0, v.reveal * 2) * v.alpha)

    def _draw_captions(self) -> None:
        """Anchorless ``caption`` overlays of the current beat sit centred
        under the card (``overlay_state`` ignores them: no rect)."""
        beat = self.runner.beat
        ms = self.runner.last_ms
        now = time.monotonic()
        for ov in beat.overlays:
            if ov.kind != OVERLAY_CAPTION or not ov.text:
                continue
            if ov.appear_ms is not None and ms < ov.appear_ms:
                continue
            if ov.disappear_ms is not None and ms >= ov.disappear_ms:
                continue
            first = self.overlay_state.first_visible_wall.setdefault(ov.id, now)
            reveal = min(1.0, (now - first) / max(0.05, config.SCRIBBLE_REVEAL_SECONDS))
            card_ui.draw_caption_under(self._card_layout, ov.text, self._ui_scale,
                                       min(1.0, reveal * 2) * self.card_motion.alpha)

