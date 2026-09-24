# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The playhead's frame pill keeps out of the keyframe strip.

It shared the strip's band, so scrubbing dragged a rounded grey chip across
the very keyframe handles the director was aiming at.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
# The ruler and playhead have their own translation unit (500-line rule).
RULER = (VIEW3D / "view3d_director_timeline_ruler.cc").read_text(encoding="utf-8")
TIMELINE_HH = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")


def _const(name: str) -> float:
    match = re.search(rf"^constexpr float {name} = ([0-9.]+)f;", TIMELINE_HH, re.M)
    assert match is not None, name
    return float(match.group(1))


def test_the_pill_has_a_named_band():
    assert _const("DIRECTOR_PLAYHEAD_PILL_H") == 25.0
    assert _const("DIRECTOR_PLAYHEAD_PILL_GAP") > 0.0


def test_the_strip_gives_that_band_up():
    """A band the strip does not subtract is a band they share."""
    assert (
        "const float pill_band = (DIRECTOR_PLAYHEAD_PILL_H + DIRECTOR_PLAYHEAD_PILL_GAP) * u;"
        in DRAW
    )
    assert "available - pill_band" in DRAW


def test_the_pill_is_sized_from_the_same_token_that_reserves_it():
    """A literal here and a token there is how the two drift back together."""
    body = RULER[RULER.index("void director_timeline_draw_playhead(") :]
    assert "const float pill_h = DIRECTOR_PLAYHEAD_PILL_H * UI_SCALE_FAC;" in body
    assert "25.0f * UI_SCALE_FAC" not in body


def test_the_playhead_line_still_crosses_the_strip():
    """Only the label moved out of the way; a playhead that stopped at the
    strip would not mark the frame."""
    body = RULER[RULER.index("void director_timeline_draw_playhead(") :]
    assert "director_timeline_draw_rect(x - 0.5f * UI_SCALE_FAC," in body
    assert "bottom," in body
