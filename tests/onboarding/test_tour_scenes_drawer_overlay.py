# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Scenes beat rings the drawer's panel and "+ New scene", which live in
the drawer's own left region (RGN_TYPE_NAV_BAR, Python ``NAVIGATION_BAR``),
not in the View3D WINDOW region. The tour must register a POST_PIXEL handler
there, and the drawer's native draw must run that region's handlers."""

from pathlib import Path

from mixar.modules.onboarding.core.tour import session_lifecycle

REPO = Path(__file__).resolve().parents[2]
DRAWER_DRAW = REPO / "src/source/blender/editors/space_view3d/view3d_scenes_drawer_draw.cc"


def test_tour_draws_over_the_scenes_drawer_region():
    assert ("SpaceView3D", "NAVIGATION_BAR") in session_lifecycle.DRAW_TARGETS


def test_drawer_region_runs_post_pixel_handlers():
    src = DRAWER_DRAW.read_text()
    assert "ED_region_draw_cb_draw(C, region, REGION_DRAW_POST_PIXEL);" in src
