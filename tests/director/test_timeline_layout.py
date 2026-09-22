# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The timeline dock is tall enough for everything it stacks.

The layout takes any shortfall out of the camera STRIP, and the strip is what
the keyframes are drawn on. When the playhead was given a band of its own the
budget went negative, the strip clamped to zero, and every keyframe vanished
while still existing in the data — "keyframes exist but not at all visible".

So the arithmetic is done here, against the layout's own constants, rather
than left to a magic region height nobody re-checks.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
TIMELINE_HH = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")


def _const(source: str, name: str) -> float:
    match = re.search(rf"^constexpr float {name} = ([0-9.]+)f;", source, re.M)
    assert match is not None, name
    return float(match.group(1))


def _region_height() -> int:
    match = re.search(r"VIEW3D_DIRECTOR_TIMELINE_HEIGHT = (\d+);", DIRECTOR_HH)
    assert match is not None
    return int(match.group(1))


def _control_height(u: float, full: bool = True) -> float:
    """cinema_dock_control_height(): the control row, plus the actions row
    that only the wide surface draws."""
    height = (_const(DOCK, "ROW_H") + _const(DOCK, "ROW_TOP_GAP") * 2.0) * u
    if full:
        height += (_const(DOCK, "SUB_ROW_GAP") + _const(DOCK, "SUB_ROW_H")) * u
    return height


def _strip_height(region_h: float, scale: float = 1.0) -> float:
    """Re-run the draw function's own budget at `UI_SCALE_FAC == scale`."""
    u = scale
    control = _control_height(u)
    content_top = region_h - control
    margin = max(6.0, int(8.0 * u))
    tick_base = margin + 10.0 * u
    label_top = tick_base + 36.0 * u + 12.0 * u
    available = content_top - label_top - 8.0 * u
    pill_band = (_const(TIMELINE_HH, "DIRECTOR_PLAYHEAD_PILL_H") + _const(TIMELINE_HH, "DIRECTOR_PLAYHEAD_PILL_GAP")) * u
    strip = min(_const(TIMELINE_HH, "DIRECTOR_STRIP_H") * u, available - pill_band)
    if strip < _const(TIMELINE_HH, "DIRECTOR_STRIP_MIN_H") * u:
        strip = min(max(available, _const(TIMELINE_HH, "DIRECTOR_STRIP_MIN_H") * u), _const(TIMELINE_HH, "DIRECTOR_STRIP_H") * u)
    return strip


def test_the_strip_gets_its_full_height_at_the_preferred_region_size():
    assert _strip_height(_region_height()) == _const(TIMELINE_HH, "DIRECTOR_STRIP_H")


def test_the_old_region_height_is_what_broke_it():
    """Pins the regression: at 164 the budget went negative and the strip
    clamped to zero."""
    assert _region_height() > 164
    u = 1.0
    control = _control_height(u)
    label_top = max(6.0, int(8.0 * u)) + 10.0 * u + 36.0 * u + 12.0 * u
    pill_band = (_const(TIMELINE_HH, "DIRECTOR_PLAYHEAD_PILL_H") + _const(TIMELINE_HH, "DIRECTOR_PLAYHEAD_PILL_GAP")) * u
    naive = min(
        _const(TIMELINE_HH, "DIRECTOR_STRIP_H") * u,
        max(0.0, (164 - control) - pill_band - label_top - 8.0 * u),
    )
    assert naive == 0.0


def test_a_dock_dragged_smaller_still_shows_a_strip():
    """The pill's band is what gives way; the strip keeps a floor, because a
    strip of zero height takes every keyframe with it."""
    for region_h in range(120, _region_height() + 1, 4):
        assert _strip_height(region_h) >= _const(TIMELINE_HH, "DIRECTOR_STRIP_MIN_H")


def test_the_strip_is_load_bearing_in_the_source_too():
    assert "float strip_h = std::min(DIRECTOR_STRIP_H * u, available - pill_band);" in DRAW
    assert "if (strip_h < DIRECTOR_STRIP_MIN_H * u) {" in DRAW
    # Never the old unconditional clamp-to-zero.
    assert "std::max(0.0f, content_top - pill_band" not in DRAW


def test_the_region_asks_for_the_raised_height():
    assert "region->sizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;" in TIMELINE
    assert "art->prefsizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;" in TIMELINE


def test_the_actions_row_was_paid_for_in_region_height():
    """A row added above the content is height taken FROM the content, and
    the strip is where the layout takes any shortfall. A saved layout shorter
    than this is raised back to it by
    `view3d_director_timeline_region_ensure`."""
    # At the new preferred height the strip is whole; at the height that was
    # enough before the row existed, it no longer would be.
    assert _strip_height(_region_height()) == _const(TIMELINE_HH, "DIRECTOR_STRIP_H")
    added = (_const(DOCK, "SUB_ROW_GAP") + _const(DOCK, "SUB_ROW_H"))
    assert _strip_height(_region_height() - added) < _const(TIMELINE_HH, "DIRECTOR_STRIP_H")


def test_the_compact_dock_keeps_its_old_budget():
    """Its rail already carries Auto Key and Add Keyframe, so reserving a row
    for them there would be height taken from the strip for nothing."""
    assert _control_height(1.0, full=False) < _control_height(1.0)
    assert "full ? row + (SUB_ROW_GAP + SUB_ROW_H) * u : row" in DOCK
