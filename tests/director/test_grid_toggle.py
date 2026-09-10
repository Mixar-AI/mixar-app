# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode top-strip control: the grid-lines toggle chip.

The chip sits immediately left of the tracking eyedropper and flips the
floor grid AND both axis lines together ("gridlines" is all of them). It is
view state: no undo, no shot required, never greyed with the shot.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import viewport

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

OPS = (DIRECTOR / "ui/operators/grid_ops.py").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")


def _space(floor=True, x=True, y=True):
    return SimpleNamespace(
        overlay=SimpleNamespace(show_floor=floor, show_axis_x=x, show_axis_y=y)
    )


# -------------------------------------------------------------------------
# core/viewport.py


def test_grid_shown_reads_the_floor_flag():
    assert viewport.grid_shown(_space(floor=True)) is True
    assert viewport.grid_shown(_space(floor=False, x=True, y=True)) is False
    assert viewport.grid_shown(SimpleNamespace(overlay=None)) is False
    assert viewport.grid_shown(SimpleNamespace()) is False


def test_toggle_grid_hides_floor_and_both_axes_together_and_returns_the_new_state():
    space = _space(True, True, True)
    assert viewport.toggle_grid(space) is False
    assert (space.overlay.show_floor, space.overlay.show_axis_x, space.overlay.show_axis_y) == (
        False, False, False,
    )
    assert viewport.toggle_grid(space) is True
    assert (space.overlay.show_floor, space.overlay.show_axis_x, space.overlay.show_axis_y) == (
        True, True, True,
    )


def test_toggle_grid_resyncs_axes_that_drifted_from_the_floor():
    # The floor flag is the truth the chip paints from; a mixed state must
    # settle on one answer, never leave the axes disagreeing with the chip.
    space = _space(floor=False, x=True, y=False)
    assert viewport.toggle_grid(space) is True
    assert (space.overlay.show_floor, space.overlay.show_axis_x, space.overlay.show_axis_y) == (
        True, True, True,
    )


def test_toggle_grid_without_an_overlay_is_a_no_op():
    assert viewport.toggle_grid(SimpleNamespace(overlay=None)) is False


# -------------------------------------------------------------------------
# ui/operators/grid_ops.py


def test_the_operator_is_registered_view_state_with_no_undo():
    assert 'bl_idname = "mixar.director_toggle_grid"' in OPS
    assert 'bl_label = "Toggle Grid"' in OPS
    assert "bl_options = {'REGISTER'}" in OPS
    assert "'UNDO'" not in OPS
    assert "MIXAR_OT_director_toggle_grid" in OPS.split("classes = (", 1)[1]


def test_the_operator_needs_a_3d_view_but_never_a_shot():
    poll = OPS[OPS.index("def poll(") : OPS.index("def execute(")]
    assert "_view3d_target(context)" in poll
    for forbidden in ("active_shot", "is_directing", "mixar_director", "_editable_shot"):
        assert forbidden not in OPS, forbidden
    # Resolves the viewport the way every Director operator does, with the
    # current 3D view as the fallback, and flips through core/.
    assert "find_view3d_context(context)" in OPS
    assert "== 'VIEW_3D'" in OPS
    assert "toggle_grid(space)" in OPS
    assert "area.tag_redraw()" in OPS


# -------------------------------------------------------------------------
# view3d_director_cinema_top.cc


def test_the_chip_sits_left_of_the_eyedropper_at_the_strip_gap():
    assert "rctf grid = {eyedrop.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u," in TOP
    assert "eyedrop.xmin - CINEMA_STRIP_GAP * u," in TOP
    # The hints yield to the leftmost control, which is now the grid chip.
    assert "const float controls_left = grid.xmin;" in TOP
    assert "const float controls_left = eyedrop.xmin;" not in TOP
    assert "std::min(controls_left, float(region->winx))" in TOP
    # Drawn under the leftmost control's own guard, alongside the others.
    assert "if (grid.xmin > 0.0f) {" in TOP
    draw = TOP[TOP.index("if (grid.xmin > 0.0f) {") :]
    assert draw.index("grid_chip(block, C, region, grid);") < draw.index(
        "track_eyedropper(block, region, eyedrop, &shot_ptr, editable);"
    )


def test_the_chip_reads_the_floor_flag_and_records_the_action_it_performs():
    chip = TOP[TOP.index("void grid_chip(") : TOP.index("}  // namespace")]
    assert "CTX_wm_view3d(" in chip
    assert "(v3d->gridflag & V3D_SHOW_FLOOR) != 0" in chip
    assert '#include "DNA_view3d_types.h"' in TOP
    assert '"MIXAR_OT_director_toggle_grid"' in chip
    assert "ICON_GRID," in chip
    assert 'shown ? "Hide grid lines" : "Show grid lines"' in chip
    assert 'cinema_qa_record(region, chip, "director_grid", shown ? "hide" : "show", -1);' in chip
    # Shown paints the row ramp; hidden paints the flat "off" fill; both
    # round at the row radius like every other strip chip.
    assert "cinema_panel(chip, CINEMA_ROW_RADIUS * u, top, bottom);" in chip
    assert "cinema_fill(chip, CINEMA_ROW_RADIUS * u, off);" in chip
    assert "CINEMA_COL_ROW_TOP" in chip and "CINEMA_COL_ROW_BOTTOM" in chip
    assert "CINEMA_COL_PHONE" in chip


def test_the_chip_is_never_disabled_with_the_shot():
    chip = TOP[TOP.index("void grid_chip(") : TOP.index("}  // namespace")]
    assert "director_overlay_disable_button" not in chip
    assert "editable" not in chip
    assert re.search(r"grid_chip\(block, C, region, grid\);", TOP)
    # The other strip controls keep their gating untouched.
    assert "track_eyedropper(block, region, eyedrop, &shot_ptr, editable);" in TOP
    assert "interpolation_dropdown(block, C, region, interp, &shot_ptr, editable);" in TOP
