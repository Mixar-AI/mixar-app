# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Interpolation lives in the dock, at its right edge.

It is how the camera eases BETWEEN KEYFRAMES, and it sat off the stage's right
edge in the TOP STRIP — about as far from the timeline as the surface allows.
It describes the shot rather than the ruler, so it belongs to no group on the
left; the right margin is where a surface puts that.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")


def _chip() -> str:
    body = DOCK[DOCK.index("void interpolation_chip(") :]
    return body[: body.index("\n}\n")]


def test_it_left_the_top_strip():
    assert "interpolation_dropdown" not in TOP
    assert "view3d_director_interpolation_popup_create" not in TOP
    assert "CINEMA_INTERP_W" not in TOP
    assert "director_interpolation" not in TOP


def test_it_is_in_the_dock_at_its_right_edge():
    assert "interpolation_chip(block, C, region, interp," in DOCK
    controls = DOCK[DOCK.index("void cinema_draw_dock_controls(") :]
    # Measured back from the dock's own right margin, never forward from the
    # group before it.
    assert "const float right_edge = float(region->winx) - (SIDE_PAD + 8.0f) * u;" in controls
    assert "right_edge - INTERP_W * u, right_edge," in controls
    assert controls.index("interpolation_chip(") < controls.index("cinema_draw_transport(")


def test_it_reads_the_enum_of_whatever_it_is_about():
    """The popup lists that property's RNA items, so a name painted from
    anywhere else could disagree with the list it opens. Which property it is
    depends on the selection — the shot's default, or the selected keyframes'
    own (`tests/director/test_interpolation_per_keyframe.py`)."""
    chip = _chip()
    labels = DOCK.split("bool interpolation_labels(", 1)[1].split("\n}\n", 1)[0]
    assert 'RNA_struct_find_property(ptr, "interpolation")' in labels
    assert "RNA_property_enum_name(" in labels
    assert "RNA_property_enum_identifier(" in labels
    assert "interpolation_labels(C, &shot_ptr, &name, &identifier)" in chip
    assert "interpolation_labels(C, &beat_ptr, &beat_name, &beat_id)" in chip
    assert "view3d_director_interpolation_popup_create" in chip


def test_it_keeps_clear_of_the_transport():
    """The transport is the load-bearing group; the chip is dropped rather
    than drawn into it on a narrow dock."""
    assert "if (interp.xmin > cinema_transport_right_edge(region) + FIELD_CLEARANCE * u) {" in DOCK


def test_it_is_disabled_on_a_locked_take():
    assert "interpolation_chip(block, C, region, interp, state.has_shot && !state.locked);" in DOCK
    assert "director_overlay_disable_button(but, !enabled);" in _chip()


def test_it_keeps_its_qa_surface():
    assert 'cinema_qa_record(region, rect, "director_interpolation", identifier, -1);' in _chip()
