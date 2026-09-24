# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for View3D navigate gizmo sizing, alignment and the hover readout.

In Mixar:
  1. The navigation gizmo (3D globe) is sized 50% smaller than upstream default.
  2. The mini navigation icons below the gizmo (Zoom, Move, Camera) are
     aligned on the exact same vertical center line as the gizmo itself.
  3. The vertical offset below the axis places the first button with a clean
     gap below the 50% smaller gizmo.
  4. Hovering an axis draws a labelled capsule at that axis handle: filled
     with the colour of the axis it points ALONG and reading "+X" / "-X", so
     the axis and its direction are both visible before the click snaps the
     view.
  5. Each globe ring is one flat colour: the colour of the axis the circle
     is perpendicular to, from the same palette the hover capsule uses.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW3D_DIR = ROOT / "src/source/blender/editors/space_view3d"

NAVIGATE_CC = (VIEW3D_DIR / "view3d_gizmo_navigate.cc").read_text(encoding="utf-8")
NAVIGATE_TYPE_CC = (VIEW3D_DIR / "view3d_gizmo_navigate_type.cc").read_text(encoding="utf-8")


def test_navigate_gizmo_size_is_scaled_50_percent_smaller():
    """GIZMO_SIZE in both view3d_gizmo_navigate.cc and view3d_gizmo_navigate_type.cc
    is defined as 50% of U.gizmo_size_navigate_v3d."""
    assert "#define GIZMO_SIZE (U.gizmo_size_navigate_v3d * 0.5f)" in NAVIGATE_CC
    assert "#define GIZMO_SIZE (U.gizmo_size_navigate_v3d * 0.5f)" in NAVIGATE_TYPE_CC


def test_navigate_type_dimensions_scale_with_gizmo_size():
    """WIDGET_RADIUS, line widths and globe line width derive from GIZMO_SIZE."""
    assert "#define WIDGET_RADIUS ((GIZMO_SIZE / 2.0f) * UI_SCALE_FAC)" in NAVIGATE_TYPE_CC
    assert "#define AXIS_LINE_WIDTH ((GIZMO_SIZE / 40.0f) * U.pixelsize)" in NAVIGATE_TYPE_CC
    assert "#define AXIS_RING_WIDTH ((GIZMO_SIZE / 60.0f) * U.pixelsize)" in NAVIGATE_TYPE_CC
    assert "#define GLOBE_LINE_WIDTH ((GIZMO_SIZE / 27.0f) * U.pixelsize)" in NAVIGATE_TYPE_CC


def test_mini_icons_share_exact_vertical_line_with_rotate_gizmo():
    """When show_rotate_gizmo is active, the horizontal position co[0] for the
    icons below the gizmo aligns directly with co_rotate[0], placing them on the
    same vertical line as the rotate gizmo."""
    assert "show_rotate_gizmo ? co_rotate[0] :" in NAVIGATE_CC


def test_vertical_spacing_accounts_for_50_percent_smaller_gizmo():
    """The vertical distance icon_offset_from_axis offsets the first mini icon
    relative to the 50% smaller gizmo and GIZMO_OFFSET."""
    assert "icon_offset_from_axis = icon_offset +" in NAVIGATE_CC
    assert "((GIZMO_SIZE / 2.0f) + GIZMO_OFFSET + (GIZMO_MINI_SIZE / 2.0f)) *" in NAVIGATE_CC


def test_hover_marker_sits_on_edge_of_gizmo():
    """The hovered axis marker is positioned on the edge of the unit sphere (1.0)."""
    assert "v_local[axis] = 1.0f * (is_pos ? 1.0f : -1.0f);" in NAVIGATE_TYPE_CC


def test_hover_marker_never_shrinks_below_the_resting_handle():
    """The capsule half height keeps the old dot radius as its floor, so the
    marker is never smaller than the plain dot it replaced."""
    assert (
        "const float half_h = std::max(WIDGET_RADIUS * AXIS_HANDLE_SIZE * 1.25f, "
        "text_size * 0.78f);" in NAVIGATE_TYPE_CC
    )


def test_hover_marker_label_carries_axis_letter_and_sign():
    """The readout is the sign followed by the axis letter, so "+X" and "-X"
    are distinguishable — a bare dot showed neither."""
    assert (
        """const char label[3] = {is_pos ? '+' : '-', char('X' + axis), '\\0'};"""
        in NAVIGATE_TYPE_CC
    )
    assert "ui::mixar_label_left(label, -text_width * 0.5f, 0.0f, text_size, text_color);" in (
        NAVIGATE_TYPE_CC
    )


def test_one_axis_palette_is_shared_by_the_rings_and_the_marker():
    """The globe and the hover capsule read the SAME table, so they cannot
    drift apart. Blender's theme axis colours (a yellow-green Y, a pink-red
    X) do not belong to this artwork and must not be read back in."""
    assert "static const float axis_colors[3][4] = {" in NAVIGATE_TYPE_CC
    assert "{0.878f, 0.263f, 0.286f, 1.0f}" in NAVIGATE_TYPE_CC  # X
    assert "{0.094f, 0.612f, 0.310f, 1.0f}" in NAVIGATE_TYPE_CC  # Y
    assert "{0.000f, 0.369f, 1.000f, 1.0f}" in NAVIGATE_TYPE_CC  # Z
    assert "copy_v4_v4(fill, axis_colors[axis]);" in NAVIGATE_TYPE_CC
    assert "copy_v4_v4(ring_color, axis_colors[axis]);" in NAVIGATE_TYPE_CC
    assert "TH_AXIS_X" not in NAVIGATE_TYPE_CC


def test_each_ring_is_one_colour_of_its_perpendicular_axis():
    """A great circle is flat-coloured with the axis it stands perpendicular
    to. The YZ ring (normal X) is red, the XZ ring (normal Y) is green, and
    the XY ring (normal Z) is blue. The hue does not change around the ring."""
    assert "copy_v4_v4(ring_color, axis_colors[axis]);" in NAVIGATE_TYPE_CC
    assert "ring_color[3] = GLOBE_RING_ALPHA;" in NAVIGATE_TYPE_CC
    assert "gizmo_globe_ring_draw(axis, ring_color, depth_axis, viewport_size);" in (
        NAVIGATE_TYPE_CC
    )
    assert "copy_v4_v4(vert_color, color);" in NAVIGATE_TYPE_CC
    # The per-vertex blend, and the old separate muted ring palette, are gone.
    assert "gizmo_globe_axis_tint" not in NAVIGATE_TYPE_CC
    assert "GLOBE_AXIS_TINT_POWER" not in NAVIGATE_TYPE_CC
    assert "GLOBE_AXIS_TINT_SCALE" not in NAVIGATE_TYPE_CC
    assert "ring_colors" not in NAVIGATE_TYPE_CC
    assert "0.329f, 0.173f, 0.173f" not in NAVIGATE_TYPE_CC


def test_silhouette_keeps_a_flat_colour():
    """The screen-aligned outline is not part of the sphere's axis artwork, so
    it still passes a colour and opts out of the depth fade."""
    assert "gizmo_globe_ring_draw(2, silhouette_color, nullptr, viewport_size);" in (
        NAVIGATE_TYPE_CC
    )
    assert "if (depth_axis != nullptr) {" in NAVIGATE_TYPE_CC


def test_hover_marker_part_mapping_matches_test_select():
    """`gizmo_axis_test_select` numbers parts from 1, axis-major with the
    negative end first, so part-1 halves into the axis and its sign."""
    assert "if (is_active && gz->highlight_part >= 1 && gz->highlight_part <= 6) {" in (
        NAVIGATE_TYPE_CC
    )
    assert "gizmo_axis_marker_draw(gz, part / 2, (part % 2) != 0);" in NAVIGATE_TYPE_CC


def test_hover_marker_stays_inside_the_widget_circle():
    """The capsule is pulled in along its own direction so it never draws
    outside `WIDGET_RADIUS` — the gizmo's screen bounds are unchanged."""
    assert (
        "const float extent = ((fabsf(dir[0]) * half_w) + (fabsf(dir[1]) * half_h)) / "
        "WIDGET_RADIUS;" in NAVIGATE_TYPE_CC
    )
    assert (
        "const float radius = std::min(dir_len, std::max(0.0f, 1.0f - extent));"
        in NAVIGATE_TYPE_CC
    )


def test_hit_testing_is_untouched_by_the_readout():
    """Only the drawing changed: the select/cursor/bounds callbacks stay as
    upstream, so click-to-snap and drag-to-orbit are unaffected."""
    assert "gzt->test_select = gizmo_axis_test_select;" in NAVIGATE_TYPE_CC
    assert "gzt->screen_bounds_get = gizmo_axis_screen_bounds_get;" in NAVIGATE_TYPE_CC
    assert "float i_best_len_sq = FLT_MAX;" in NAVIGATE_TYPE_CC


def test_cinema_mode_draws_no_navigation_cluster():
    """Cinema Mode removes the whole group — the axis globe, zoom, move, the
    camera-view toggle and the lock-camera-to-view toggle — through the one
    poll every one of them shares, so none can come back on its own."""
    poll = NAVIGATE_CC.split("static bool WIDGETGROUP_navigate_poll(", 1)[1].split("\n}\n", 1)[0]
    assert "if (view3d_director_is_directing(CTX_data_scene(C))) {" in poll
    directing = poll[poll.index("view3d_director_is_directing") :]
    assert directing.split("}", 1)[0].strip().endswith("return false;")
    # The user's own hide flags are still asked first.
    assert poll.index("V3D_GIZMO_HIDE_NAVIGATE") < poll.index("view3d_director_is_directing")
    assert '#include "view3d_director.hh"' in NAVIGATE_CC
    # And the stage-parking the cluster used to need is gone with it.
    assert "cinema_stage_rect" not in NAVIGATE_CC
    assert "cinema_unit" not in NAVIGATE_CC

