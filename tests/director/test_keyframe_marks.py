# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keyframes read as keyframes on the camera strip.

They were rounded pills in #FFD4B0 drawn on a #FFB87A strip — two shades of
the same orange, which is no contrast at all. They are diamonds with a dark
outline now, the shape every Blender editor marks a key with.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAW = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_timeline_draw.cc"
).read_text(encoding="utf-8")


def _color(name: str) -> tuple[float, ...]:
    match = re.search(rf"constexpr float {name}\[4\] = \{{([^}}]+)\}};", DRAW)
    assert match is not None, name
    return tuple(float(part.strip().rstrip("f")) for part in match.group(1).split(","))


def _luminance(color) -> float:
    r, g, b = color[0], color[1], color[2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = _luminance(a) + 0.05, _luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def test_the_mark_is_a_diamond():
    assert "void draw_diamond(" in DRAW
    assert "GPU_PRIM_TRI_FAN" in DRAW
    loop = DRAW[DRAW.index("for (const DirectorBeatView &beat : state.beats)") :]
    assert "draw_diamond(x, cy, radius, fill);" in loop
    # The old near-invisible pill.
    assert "draw_round_rect(handle," not in DRAW


def test_every_mark_carries_an_outline():
    """A fill alone is two shades of the strip's own orange."""
    assert "void draw_diamond_outline(" in DRAW
    loop = DRAW[DRAW.index("for (const DirectorBeatView &beat : state.beats)") :]
    assert "draw_diamond_outline(x," in loop
    assert loop.index("draw_diamond(x,") < loop.index("draw_diamond_outline(x,")


def test_the_outline_contrasts_with_the_strip_it_sits_on():
    """This is the property that was missing, so it is the one pinned."""
    strip = _color("STRIP_COLOR")
    assert _contrast(_color("HANDLE_OUTLINE_COLOR"), strip) >= 4.5
    # And the fill is legible against its own outline.
    assert _contrast(_color("HANDLE_COLOR"), _color("HANDLE_OUTLINE_COLOR")) >= 4.5


def test_the_old_fill_really_was_invisible():
    """Guards the regression: the previous pair were the same orange."""
    assert _contrast((1.0, 0.83, 0.69), _color("STRIP_COLOR")) < 1.5


def test_a_selected_key_is_a_different_colour_not_just_a_brighter_one():
    """The active keyframe and a hover are already lit, so "lit" cannot also
    mean selected."""
    selected = _color("HANDLE_SELECTED_COLOR")
    assert selected != _color("HANDLE_ACTIVE_COLOR")
    assert _contrast(selected, _color("HANDLE_ACTIVE_COLOR")) >= 1.5


def test_the_mark_never_outgrows_the_strip_carrying_it():
    loop = DRAW[DRAW.index("for (const DirectorBeatView &beat : state.beats)") :]
    assert "std::min(handle_w * 0.75f, strip_h * 0.42f)" in loop
    # ... and never shrinks to nothing on a short dock.
    assert "std::max(5.0f * UI_SCALE_FAC," in loop
