# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for View3D navigate gizmo sizing and vertical alignment.

In Mixar:
  1. The navigation gizmo (3D globe) is sized 50% smaller than upstream default.
  2. The mini navigation icons below the gizmo (Zoom, Move, Camera) are
     aligned on the exact same vertical center line as the gizmo itself.
  3. The vertical offset below the axis places the first button with a clean
     gap below the 50% smaller gizmo.
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


def test_snapping_dot_appears_on_edge_of_gizmo():
    """The hovered axis snapping dot is positioned on the edge of the unit sphere (1.0)."""
    assert "v_local[axis] = 1.0f * (is_pos ? 1.0f : -1.0f);" in NAVIGATE_TYPE_CC


def test_snapping_dot_is_scaled_larger():
    """The snapping dot radius is scaled larger for clear visibility and targeting."""
    assert "const float rad = WIDGET_RADIUS * AXIS_HANDLE_SIZE * 1.25f;" in NAVIGATE_TYPE_CC

