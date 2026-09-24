# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — text measurement and drawing.

One place that talks to ``blf`` so every overlay measures the same way and
layout code keeps working under the test mocks (where ``blf.dimensions``
returns a MagicMock): measurement falls back to a glyph-width estimate.
"""

import math

import blf

FONT_ID = 0

# Average glyph width as a fraction of the font size; the fallback only.
_GLYPH_W = 0.55
_LINE_H = 1.15


def text_width(text: str, px: float) -> float:
    """Width of ``text`` at ``px`` in pixels; always a finite float."""
    if not text:
        return 0.0
    try:
        blf.size(FONT_ID, int(px))
        w, _h = blf.dimensions(FONT_ID, text)
        w = float(w)
        if math.isfinite(w) and w > 0.0:
            return w
    except Exception:
        pass
    return len(text) * float(px) * _GLYPH_W


def text_height(px: float, sample: str = "Ag") -> float:
    """Cap-to-descender height at ``px``; never below ``px``."""
    try:
        blf.size(FONT_ID, int(px))
        _w, h = blf.dimensions(FONT_ID, sample)
        h = float(h)
        if math.isfinite(h) and h > 0.0:
            return max(h, float(px))
    except Exception:
        pass
    return float(px) * _LINE_H


def draw_text(x: float, y: float, text: str, px: float, color: tuple) -> None:
    """Draw ``text`` with its baseline at ``(x, y)``."""
    blf.size(FONT_ID, int(px))
    blf.color(FONT_ID, *color)
    blf.position(FONT_ID, float(x), float(y), 0.0)
    blf.draw(FONT_ID, text)


def draw_text_centered(rect: tuple, text: str, px: float, color: tuple) -> None:
    """Draw ``text`` centred inside ``rect`` ``(xmin, ymin, xmax, ymax)``."""
    xmin, ymin, xmax, ymax = rect
    w = text_width(text, px)
    # blf draws from the baseline: centre the x-height band, not the
    # descender box, so labels sit optically centred.
    x = (xmin + xmax) * 0.5 - w * 0.5
    y = (ymin + ymax) * 0.5 - px * 0.36
    draw_text(x, y, text, px, color)
