# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the video card's motion state.

Pure Python (no bpy): the session hands ``step`` the *target* card rect
from ``card.compute_card_layout`` every tick and reads back the animated
rect, the controls-strip reveal and the start fade. Placement or variant
changes therefore glide instead of jumping, the controls fade in on hover
/ pause / exit dialog, the whole card fades in on tour start and, once
``fade_out`` is called at the end, eases back to nothing (``faded_out``).

Easing is the same exponential style as the fake cursor:
``k = 1 - exp(-dt * rate)``; rects snap once within ``CARD_MOVE_SNAP_PX``
so the layout is exact at rest.
"""

import math
from typing import Optional

from . import config

_ALPHA_SNAP = 0.005


def _ease_k(dt: float, rate: float) -> float:
    return 1.0 - math.exp(-max(0.0, dt) * rate)


_FADED_OUT_ALPHA = 0.01


class CardMotion:
    """Animated card rect + controls reveal + start/end fades. Advance with ``step``."""

    def __init__(self) -> None:
        self.rect: Optional[tuple] = None      # animated (xmin, ymin, xmax, ymax)
        self.target: Optional[tuple] = None
        self.controls_alpha = 0.0
        self.alpha = 0.0                        # card fade-in, 0 -> 1 after start
        self._fading_out = False

    def reset(self) -> None:
        self.rect = None
        self.target = None
        self.controls_alpha = 0.0
        self.alpha = 0.0
        self._fading_out = False

    @property
    def settled(self) -> bool:
        return self.rect is not None and self.rect == self.target

    @property
    def fading_out(self) -> bool:
        return self._fading_out

    @property
    def faded_out(self) -> bool:
        """True once ``fade_out`` has eased the card to nothing."""
        return self._fading_out and self.alpha <= _FADED_OUT_ALPHA

    def fade_out(self) -> None:
        """Ease ``alpha`` to 0 from here on (the tour's ending); the fade-in
        stops competing. Idempotent."""
        self._fading_out = True

    def step(self, dt: float, target: Optional[tuple], reveal_controls: bool) -> bool:
        """Advance by ``dt`` toward ``target``; True when anything changed."""
        changed = False
        if target is not None:
            target = tuple(float(v) for v in target)
            self.target = target
            if self.rect is None:
                self.rect = target          # first layout: no glide from nowhere
                changed = True
            elif self.rect != target:
                k = _ease_k(dt, config.CARD_MOVE_RATE)
                snap = config.CARD_MOVE_SNAP_PX
                moved = []
                done = True
                for cur, tgt in zip(self.rect, target):
                    d = tgt - cur
                    if abs(d) <= snap:
                        moved.append(tgt)
                    else:
                        moved.append(cur + d * k)
                        done = False
                self.rect = target if done else tuple(moved)
                changed = True

        goal = 1.0 if reveal_controls else 0.0
        if self.controls_alpha != goal:
            k = _ease_k(dt, config.CONTROL_REVEAL_RATE)
            self.controls_alpha += (goal - self.controls_alpha) * k
            if abs(goal - self.controls_alpha) <= _ALPHA_SNAP:
                self.controls_alpha = goal
            changed = True

        if self._fading_out:
            if self.alpha > 0.0:
                fade = config.CARD_FADE_OUT_SECONDS
                self.alpha = 0.0 if fade <= 0.0 else max(0.0, self.alpha - dt / fade)
                if self.alpha <= _FADED_OUT_ALPHA:
                    self.alpha = 0.0
                changed = True
        elif self.alpha < 1.0:
            fade = config.CARD_FADE_SECONDS
            self.alpha = 1.0 if fade <= 0.0 else min(1.0, self.alpha + dt / fade)
            changed = True
        return changed
