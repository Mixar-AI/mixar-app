# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Where a workflow template puts its cards. Pure arithmetic, no bpy.

Positions are relative to the workflow's top-left corner (0, 0), with y
increasing UP like the canvas, and each position is a card's bottom-left
corner (the canvas convention for ``position_x`` / ``position_y``).

Rows are lanes (body on top), columns are pipeline stages: reference image,
3D, rig, assemble. An image result grows its card UPWARD from a fixed
``position_y``, so the row pitch leaves room for a portrait result; the body
row may grow into the frame header, which the frame absorbs as it grows.
"""

from __future__ import annotations

import math

CARD_W = 700.0
CARD_H = 560.0
COL_PITCH = 920.0
ROW_PITCH = 1000.0
# Between the sheet's right edge and the workflow's left edge.
SHEET_GAP = 200.0
# Between the last lane and the note below it.
NOTE_GAP = 120.0


def note_height(text: str, font: int, width: float) -> float:
    """A text box tall enough for *text* wrapped at *width* (a generous estimate)."""
    chars_per_line = max(1, math.floor((float(width) - 20.0) / (0.55 * float(font))))
    lines = max(1, math.ceil(len(text) / chars_per_line))
    return lines * 1.3 * float(font) + 20.0


def plan_layout(lane_count: int, has_rig: bool, note_h: float, note_w: float = 0.0) -> dict:
    """Bottom-left corners of every card, the note, and the overall bounds.

    Returns ``{'ref': [(x, y)…], 'm3d': [(x, y)…], 'rig': (x, y) | None,
    'assemble': (x, y), 'note': (x, y), 'bounds': (left, bottom, right, top)}``.
    """
    lane_count = max(1, int(lane_count))
    ref = [(0.0, -row * ROW_PITCH - CARD_H) for row in range(lane_count)]
    m3d = [(COL_PITCH, y) for _x, y in ref]
    rig = (2.0 * COL_PITCH, ref[0][1]) if has_rig else None
    centre = sum(y + CARD_H * 0.5 for _x, y in ref) / lane_count
    assemble = ((3.0 if has_rig else 2.0) * COL_PITCH, centre - CARD_H * 0.5)
    note = (0.0, ref[-1][1] - NOTE_GAP - float(note_h))
    right = max(assemble[0] + CARD_W, float(note_w))
    return {
        'ref': ref,
        'm3d': m3d,
        'rig': rig,
        'assemble': assemble,
        'note': note,
        'bounds': (0.0, note[1], right, 0.0),
    }
