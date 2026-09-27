# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Zen's Move/Rotate/Scale pill must stay a fixed on-screen size.

The pill lives in View3D's overlapping TOOLS region, which still installs the
stock "View2D Buttons List" keymap (trackpad pinch, ctrl+MMB, numpad +/-).
Without a zoom lock those gestures scale the buttons. The pill is also
centred by a full-height spacer, so the region's View2D extent covers the
column above it: only the buttons may count as the pill, and navigation
gestures over them belong to the viewport.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/source/blender"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


CHROME = _read("editors/interface/interface_mixar_zen_chrome.cc")
AREA = _read("editors/screen/area.cc")
QUERY = _read("editors/screen/area_query.cc")
HEADER = _read("editors/include/UI_mixar.hh")
EVENTS = _read("windowmanager/intern/wm_event_system.cc")


def _body(source: str, signature: str) -> str:
    return source.split(signature, 1)[1].split("\n}\n", 1)[0]


def test_fixed_scale_helper_locks_view2d_zoom():
    assert "void mixar_zen_floating_tools_fixed_scale(const bContext *C, ARegion *region);" in HEADER
    body = _body(CHROME, "void mixar_zen_floating_tools_fixed_scale(")
    assert "V2D_LOCKZOOM_X | V2D_LOCKZOOM_Y | V2D_KEEPZOOM" in body
    assert "v2d->minzoom = 1.0f;" in body
    assert "v2d->maxzoom = 1.0f;" in body
    # A zoom saved before the lock existed snaps back to one unit per pixel.
    assert "v2d->cur.xmax = v2d->cur.xmin + mask_w;" in body
    assert "v2d->cur.ymin = v2d->cur.ymax - mask_h;" in body
    # Only the Zen View3D TOOLS overlap region is touched.
    assert "RGN_TYPE_TOOLS" in body and "mixar_area_floats_viewport_chrome" in body


def test_panels_layout_and_draw_reassert_fixed_scale():
    layout = _body(AREA, "void ED_region_panels_layout_ex(")
    assert "ui::mixar_zen_floating_tools_fixed_scale(C, region);" in layout
    # Before the panels are laid out against the View2D.
    assert layout.index("mixar_zen_floating_tools_fixed_scale") < layout.index(
        "v2d->keepofs |= V2D_LOCKOFS_X"
    )

    draw = _body(AREA, "void ED_region_panels_draw(")
    assert "ui::mixar_zen_floating_tools_fixed_scale(C, region);" in draw
    assert draw.index("mixar_zen_floating_tools_fixed_scale") < draw.index("const float aspect")


def test_zen_region_predicate_is_tools_overlap_in_zen_view3d():
    assert "bool mixar_region_is_zen_floating_tools(const ARegion *region);" in HEADER
    body = _body(CHROME, "bool mixar_region_is_zen_floating_tools(")
    assert "region->overlap" in body
    assert "region->regiontype != RGN_TYPE_TOOLS" in body
    assert "mixar_area_floats_viewport_chrome(&area)" in body


def test_only_the_pill_buttons_are_a_hit():
    hit = _body(QUERY, "static bool zen_floating_tools_contains_xy(")
    assert "ui::region_but_find_rect_over(region, &rect) != nullptr" in hit
    assert "UI_REGION_OVERLAP_MARGIN" in hit

    # Hover (ED_screen_set_active_region) and event lookup both go through here.
    contains = _body(QUERY, "bool ED_region_contains_xy(")
    zen = contains.index("ui::mixar_region_is_zen_floating_tools(region)")
    assert contains.index("return zen_floating_tools_contains_xy(region, event_xy);") > zen
    # Ahead of the stock LEFT-aligned rule, which clips Y only.
    assert zen < contains.index("RGN_ALIGN_ENUM_FROM_MASK(region->alignment)")

    any_xy = _body(QUERY, "bool ED_region_overlap_isect_any_xy(")
    assert "ui::mixar_region_is_zen_floating_tools(&region)" in any_xy
    assert "zen_floating_tools_contains_xy(&region, event_xy)" in any_xy


def test_navigation_over_the_pill_reaches_the_viewport():
    body = _body(EVENTS, "static eHandlerActionFlag wm_event_do_handlers_area_regions(")
    route = body.index("ui::mixar_region_is_zen_floating_tools(region_hovered)")
    assert "ISMOUSE_WHEEL(event->type)" in body
    assert "ISMOUSE_GESTURE(event->type)" in body
    assert "event->type == MIDDLEMOUSE" in body
    assert "RGN_TYPE_WINDOW" in body[route:]
    # Rerouted before the hovered region's handlers run.
    assert route < body.index("return wm_event_do_region_handlers(C, event, region_hovered);")
    assert '#include "UI_mixar.hh"' in EVENTS
