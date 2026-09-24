# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dock's Start/End fields: beside the ruler, in the ruler's own unit.

They used to sit at the far end of the row, past the transport, where nothing
said they were the range the ruler under them is scaling.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")


def _define(name: str) -> float:
    match = re.search(rf"^constexpr float {name} = (-?[0-9.]+)f;", DOCK, re.M)
    assert match is not None, name
    return float(match.group(1))


def test_the_value_gets_what_the_label_does_not_need():
    """A fixed 48% split of a 100-design-px field left about 14px of usable
    text once a Num button's own arrow padding was taken out — which is where
    "only 2 digits max is visible" came from."""
    body = DOCK[DOCK.index("void frame_field(") :]
    body = body[: body.index("\n}\n")]
    assert "cinema_text_width(label, font)" in body
    assert "BLI_rctf_size_x(&rect) * 0.52f" not in DOCK


def test_the_field_is_wide_enough_for_a_label_and_four_digits():
    # Roughly: label ~34 + gap 8 + pad 12 + a Num button's ~24 of arrow
    # padding still has to leave room for "1200".
    assert _define("FIELD_W") >= 120.0
    assert _define("FIELD_MIN_W") >= 80.0


def test_the_fields_shrink_before_they_disappear():
    """Dropping the pair whole meant a slightly narrower viewport made Start
    and End vanish outright."""
    assert (
        "const float field_w = std::min(FIELD_W * u, (available - FIELD_GAP * u) * 0.5f);"
        in DOCK
    )
    assert "if (field_w < FIELD_MIN_W * u) {" in DOCK
    assert "fields_fit" not in DOCK


def test_they_sit_where_the_ruler_group_leaves_off():
    """The range is what the scale beside it measures; the row reads left to
    right as one sentence about it."""
    controls = DOCK[DOCK.index("void cinema_draw_dock_controls(") :]
    assert controls.index("cinema_draw_ruler_group(") < controls.index(
        "draw_frame_range(block, C, region, state, x, row_ymin, row_ymax);"
    )


def test_the_transport_is_created_after_the_fields():
    """`ui_but_find_mouse_over_ex` walks a block BACKWARDS, so the later
    button wins an overlapping band. With the fields last, an invisible Num
    over the transport turned "previous keyframe" into a drag-edit of the
    scene's start frame."""
    controls = DOCK[DOCK.index("void cinema_draw_dock_controls(") :]
    assert controls.index("draw_frame_range(") < controls.index(
        "cinema_draw_transport(block, region, state, cy, playing);"
    )


def test_the_fields_still_keep_clear_of_the_transport():
    assert "transport_left - FIELD_CLEARANCE * u - start_x" in DOCK


def test_they_read_in_the_unit_the_switch_beside_them_selects():
    """A ruler labelled in seconds over a range quoted in frames is the row
    disagreeing with itself. The seconds are the Director state's mirrors of
    `scene.frame_start` / `frame_end`, so nothing is stored twice."""
    body = DOCK[DOCK.index("float draw_frame_range(") :]
    body = body[: body.index("\n}\n")]
    assert "const bool seconds = !state.ruler_frames" in body
    assert 'seconds ? "range_start_seconds" : "frame_start"' in body
    assert 'seconds ? "range_end_seconds" : "frame_end"' in body
    # The unit decides which datablock owns the property, and the cell takes
    # whichever it is handed.
    assert "PointerRNA *ptr = seconds ? &state_ptr : &scene_ptr;" in body
    assert "view3d_director_state_pointer(scene, &state_ptr)" in body
