# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A first-ever Zen drawer is clickable in the refresh that created it.

`ED_area_init()` polls regions and lays out their rects BEFORE the space init
hook that creates the drawer region, and nothing re-polls until the next full
screen refresh. A freshly duplicated Zen Mode workspace therefore came up
with a poll-failed, zero-width drawer: no grip painted, no grip to click,
until a window resize or workspace switch happened to refresh the screen.
QA reported it as "Moodboard not opening on click".

Source-level: bpy is mocked here, so the C++ bootstrap is pinned by reading it.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAWER = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer.cc"
).read_text(encoding="utf-8")
AREA = (ROOT / "src/source/blender/editors/screen/area.cc").read_text(encoding="utf-8")
CONSTANTS = (ROOT / "src/scripts/mixar/modules/workflow/constants.py").read_text(
    encoding="utf-8"
)


def _fn(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start : source.index("\n}\n", start)]


def test_area_init_polls_regions_before_the_space_init_hook():
    """The ordering that makes the bootstrap necessary; if upstream ever
    re-polls after `type->init`, the bootstrap becomes redundant, not wrong."""
    init = _fn(AREA, "void ED_area_init(bContext *C, const wmWindow *win, ScrArea *area)")
    assert init.index("area_regions_poll(C, screen, area);") < init.index("area->type->init(wm, area);")
    assert init.index("region_rect_recursive(") < init.index("area->type->init(wm, area);")
    # The region-size pass the bootstrap requests re-lays-out and re-inits
    # visible regions before the first draw, and honours a cleared poll flag.
    update = _fn(AREA, "void ED_area_update_region_sizes(")
    assert "if (region.flag & RGN_FLAG_POLL_FAILED)" in update
    assert "region_evaluate_visibility(&region);" in update
    assert "region.runtime->type->init(wm, &region);" in update


def test_new_drawer_region_answers_its_own_poll_and_requests_layout():
    ensure = _fn(DRAWER, "void view3d_moodboard_drawer_region_ensure(wmWindowManager *wm, ScrArea *area)")
    created = ensure[ensure.index("ARegion *region = BKE_area_region_new();"):]
    assert "RGN_FLAG_TEMP_REGIONDATA | RGN_FLAG_POLL_FAILED" in created
    assert "if (drawer_area_in_zen_workspace(wm, area)) {" in created
    assert "region->flag &= ~RGN_FLAG_POLL_FAILED;" in created
    assert "view3d_moodboard_drawer_size_sync(wm, area, region);" in created
    assert "area->flag |= AREA_FLAG_REGION_SIZE_UPDATE;" in created
    # The bootstrap's answer is the region poll's answer.
    lookup = _fn(DRAWER, "static bool drawer_area_in_zen_workspace(")
    assert "BLI_findindex(&screen->areabase, area)" in lookup
    assert "view3d_moodboard_drawer_workspace_is_zen(WM_window_get_active_workspace(&win))" in lookup
    poll = _fn(DRAWER, "static bool drawer_region_poll(")
    assert "view3d_moodboard_drawer_zen_active(params->context)" in poll
    active = _fn(DRAWER, "bool view3d_moodboard_drawer_zen_active(const bContext *C)")
    assert "view3d_moodboard_drawer_workspace_is_zen(CTX_wm_workspace(C))" in active


def test_the_zen_workspace_name_is_the_shared_constant():
    """Every drawer gate compares this one literal; it must be the workspace
    `workflow/constants.py` creates, or the drawer silently never appears."""
    assert 'BASIC_WORKSPACE_NAME = "Zen Mode"' in CONSTANTS
    header = (ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer.hh").read_text()
    predicate = _fn(header, "inline bool view3d_moodboard_drawer_workspace_is_zen(const WorkSpace *workspace)")
    assert 'STREQ(workspace->id.name + 2, "Zen Mode")' in predicate
    assert (DRAWER + header).count('"Zen Mode"') == 1


def test_region_init_seeds_the_hit_rect_amount_from_the_wm_property():
    """The grip's hit rect reads regiondata that only the draw pass wrote, so
    fresh regiondata after a workspace round trip put the click target at the
    shut position while the tab painted open."""
    init = _fn(DRAWER, "void view3d_moodboard_drawer_region_init(wmWindowManager *wm, ARegion *region)")
    assert "runtime->amount = std::clamp(view3d_moodboard_drawer_amount_wm(wm), 0.0f, 1.0f);" in init
    state = (ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer_state.cc").read_text()
    assert 'RNA_struct_find_property(&wm_ptr, "mixar_moodboard_drawer_amount")' in _fn(
        state, "float view3d_moodboard_drawer_amount_wm(const wmWindowManager *wm)"
    )
