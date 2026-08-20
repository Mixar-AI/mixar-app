# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card

Custom GPU-rendered popup that replaces ``invoke_props_dialog`` for
the onboarding flow. Each step (welcome, the five info cards, and
the completion screen) is painted by the same modal operator using
this package — only the copy and anchor change.

Public surface:

* :func:`compute_layout` — measure and position a card given a step.
* :func:`draw_card` — POST_PIXEL draw callback (region-relative).
* :func:`hit_test` — translate a window-space mouse event to a
  button id (``"primary"``, ``"skip"``, or ``None``).
"""

from .layout import CardLayout, compute_layout, hit_test
from .renderer import draw_card, draw_dismiss_hint

__all__ = (
    "CardLayout",
    "compute_layout",
    "draw_card",
    "draw_dismiss_hint",
    "hit_test",
)
