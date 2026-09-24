# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The timeline dock is an opaque region and must clear itself.

`RGN_TYPE_CHANNELS` is not in View3D's overlap set, so nothing clears the
dock's framebuffer for it, and the panel it paints is translucent glass inset
from the region's edges. Without a clear the previous frame stays underneath
and every redraw composites onto it — the ruler, the keyframes and the
transport all leave ghosts of where they used to be.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")


def _draw_body() -> str:
    body = TIMELINE.split("void director_timeline_draw(", 1)[1]
    return body.split("\nvoid ", 1)[0]


def test_the_dock_clears_before_it_paints():
    """5.2's name for it. `UI_ThemeClearColor` was 5.0's, and writing that
    one from memory is what broke the build
    (`tests/director/test_native_api_names.py` now catches the class)."""
    draw = _draw_body()
    assert "ui::theme::frame_buffer_clear(TH_BACK);" in draw
    assert "UI_ThemeClearColor" not in draw


def test_the_clear_comes_before_any_painting():
    """A clear after the first paint would wipe what it just drew."""
    draw = _draw_body()
    clear = draw.index("ui::theme::frame_buffer_clear(TH_BACK);")
    for painter in (
        "cinema_draw_dock_panel(region);",
        "cinema_draw_dock_controls(",
        "view3d_director_timeline_draw_content(",
    ):
        assert clear < draw.index(painter), painter


def test_the_panel_is_still_inset_so_the_clear_is_load_bearing():
    """If the panel ever covered the region edge to edge AND opaquely, the
    clear would be belt and braces. It does neither."""
    panel = DOCK.split("void cinema_draw_dock_panel(", 1)[1].split("\n}", 1)[0]
    assert "8.0f * u" in panel and "6.0f * u" in panel
    assert "cinema_glass_panel(" in panel


def test_a_saved_layout_is_raised_to_the_current_height():
    """`sizey` is written only when the region is created, so a workspace
    saved by an earlier build kept that build's height forever — and the
    keyframe strip has a content minimum, not a preference."""
    ensure = TIMELINE.split("void view3d_director_timeline_region_ensure(", 1)[1]
    ensure = ensure.split("\nvoid ", 1)[0]
    assert "existing->sizey < VIEW3D_DIRECTOR_TIMELINE_HEIGHT" in ensure
    assert "existing->sizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;" in ensure
    # ... and a taller one is the user's own resize.
    assert "existing->sizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;" in ensure
    assert ensure.count("existing->sizey =") == 1


def test_the_region_is_created_once():
    """The early return that used to guard against a second region is now the
    branch that raises a short one; it must still return."""
    ensure = TIMELINE.split("void view3d_director_timeline_region_ensure(", 1)[1]
    ensure = ensure.split("\nvoid ", 1)[0]
    branch = ensure.split("BKE_area_find_region_type(area, RGN_TYPE_CHANNELS)", 1)[1]
    assert "return;" in branch.split("}", 2)[0] + branch.split("}", 2)[1]
