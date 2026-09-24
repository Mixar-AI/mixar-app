# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Zen drawer is an overlay, not a Mixie split, and must stay interactive.

Pinned at source level: bpy is mocked, so operator runtime is not exercised
here. The seams that used to paper over a dead grip or a display-only canvas
are the ones that must not regress.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
MIXIE = ROOT / "src/source/blender/editors/space_mixie"
AREA = ROOT / "src/source/blender/editors/screen/area.cc"
AREA_QUERY = ROOT / "src/source/blender/editors/screen/area_query.cc"
DRAWER_GEOM = ROOT / "src/source/blender/editors/include/ED_moodboard_drawer.hh"
UTILS = ROOT / "src/scripts/mixar/modules/moodboard/core/moodboard_utils.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _define_float(source: str, name: str) -> float:
    match = re.search(rf"^#define {name}\s+([0-9.]+)f?\s*$", source, flags=re.M)
    assert match is not None, f"{name} not found"
    return float(match.group(1))


def _fn(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index, char in enumerate(source[brace:], start=brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced function starting {signature!r}")


def test_drawer_sources_stay_under_the_house_line_cap():
    for path in (
        VIEW3D / "view3d_moodboard_drawer.cc",
        VIEW3D / "view3d_moodboard_drawer_draw.cc",
        VIEW3D / "view3d_moodboard_drawer_ops.cc",
        VIEW3D / "view3d_moodboard_drawer_state.cc",
    ):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 500, f"{path.name} is {lines} lines"


def test_canvas_active_amount_is_one_number():
    geom = _read(DRAWER_GEOM)
    mixie = _read(MIXIE / "mixie_intern.hh")
    assert _define_float(geom, "VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT") == 0.98
    assert _define_float(mixie, "MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT") == 0.98


def test_first_open_width_is_about_thirty_five_percent_of_the_viewport():
    geom = _read(DRAWER_GEOM)
    assert _define_float(geom, "VIEW3D_MOODBOARD_DRAWER_WIDTH_FRACTION") == 0.35
    assert _define_float(geom, "VIEW3D_MOODBOARD_DRAWER_WIDTH") == 340
    resize = _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_resize.cc"))
    assert "mixar_moodboard_drawer_width_ready" in resize
    body = _fn(resize, "void view3d_moodboard_drawer_size_sync(")
    assert "VIEW3D_MOODBOARD_DRAWER_WIDTH_FRACTION" in body
    assert "drawer_width_ready" in body
    props = _read(
        ROOT / "src/scripts/mixar/modules/moodboard/ui/moodboard_drawer_props.py"
    )
    assert "mixar_moodboard_drawer_width_ready" in props


def test_visual_hit_is_only_the_grip_and_painted_slice():
    """RIGHT overlap clips Y only; the whole overlay must not eat the viewport."""
    geom = _strip_comments(_read(DRAWER_GEOM))
    body = _fn(geom, "inline bool view3d_moodboard_drawer_contains_xy(")
    assert "view3d_moodboard_drawer_resize_contains_xy" in body
    assert "view3d_moodboard_drawer_panel_rect_for" in body
    panel = _fn(geom, "inline bool view3d_moodboard_drawer_panel_rect_for(")
    assert "0.001f" in panel

    query = _strip_comments(_read(AREA_QUERY))
    visual = _fn(query, "ARegion *ED_area_find_region_xy_visual(")
    assert "view3d_moodboard_drawer_contains_xy" in visual
    assert "RGN_TYPE_TOOL_PROPS" in visual
    overlap = _fn(query, "bool ED_region_overlap_isect_any_xy(")
    assert "view3d_moodboard_drawer_contains_xy" in overlap


def test_floating_header_does_not_hide_the_drawer():
    """Hidden non-overlap regions cannot reset the drawer onto the header."""
    area = _read(AREA)
    layout = _fn(_strip_comments(area), "static void region_rect_recursive(")
    assert "mixar_floating_headers_clip(region, overlap_remainder)" in layout
    fix = _fn(_strip_comments(area), "static void region_overlap_fix(")
    assert "mixar_floating_header_may_share_corner" not in fix


def test_view3d_tool_props_has_no_edge_azone():
    """The overlapping sash covered the open grip's leading half."""
    body = _fn(_strip_comments(_read(AREA)), "static bool region_azone_edge_poll(")
    assert "SPACE_VIEW3D" in body and "RGN_TYPE_TOOL_PROPS" in body
    assert "return false;" in body


def test_moodboard_poll_accepts_the_zen_drawer_host():
    source = _strip_comments(_read(MIXIE / "mixie_moodboard_ops_common.hh"))
    assert "moodboard_zen_drawer_active" in _fn(source, "inline bool moodboard_poll(")

    helper = _fn(source, "inline bool moodboard_zen_drawer_active(")
    assert "SPACE_VIEW3D" in helper
    assert "RGN_TYPE_TOOL_PROPS" in helper
    assert "mixar_moodboard_drawer_amount" in helper
    assert "MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT" in helper


def test_drawer_region_hosts_mixie_and_view2d_behind_an_open_poll():
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer.cc")),
        "void view3d_moodboard_drawer_region_init(",
    )
    assert '"Mixie"' in body and "SPACE_MIXIE" in body
    assert '"View2D"' in body
    assert "view3d_moodboard_drawer_canvas_handler_poll" in body
    assert "WM_dropboxmap_find" in body


def test_grip_handler_beats_ui_and_only_answers_on_the_handle():
    """`~` first, then grip, then UI, then Mixie — a selected card cannot steal close."""
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer.cc")),
        "void view3d_moodboard_drawer_region_init(",
    )
    toggle = body.index("view3d_moodboard_drawer_toggle_handlers_add")
    grip = body.index("WM_event_add_keymap_handler_priority")
    ui = body.index("region_handlers_add")
    canvas = body.index("view3d_moodboard_drawer_canvas_handler_poll")
    # Both UI and priority keymaps prepend; registration order is reversed.
    assert ui < grip < toggle < canvas
    invoke = _fn(_strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_ops.cc")),
                 "static wmOperatorStatus drawer_grip_invoke(")
    assert "drawer_grip_hit(C, event->xy)" in invoke
    assert "return OPERATOR_PASS_THROUGH" in invoke


def test_drawer_region_type_does_not_take_view2d_keymapflag():
    """A shut overlay with ED_KEYMAP_VIEW2D steals viewport pan."""
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer.cc")),
        "void view3d_moodboard_drawer_region_register(",
    )
    assert "art->keymapflag = 0;" in body


def test_viewport_cursor_honors_drawer_edge_after_canvas_view_changes():
    source = _strip_comments(_read(VIEW3D / "space_view3d.cc"))
    body = _fn(source, "static void view3d_main_region_cursor(")
    assert body.index("view3d_moodboard_drawer_resize_contains_xy") < body.index(
        "WM_cursor_set_from_tool")
    assert "drawer->runtime->visible" in body
    assert "WM_CURSOR_X_MOVE" in body
    assert "art->cursor = view3d_main_region_cursor;\n  art->event_cursor = true;" in source


def test_drawer_grip_keymap_is_grip_only():
    """Canvas LEFTMOUSE on the same map as the grip can sort above it in the
    user keyconfig, and WM_keymap_active then never reaches the handle."""
    ops = _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_ops.cc"))
    body = _fn(ops, "void view3d_moodboard_drawer_keymap(")
    assert "Moodboard Drawer Grip" in body
    assert "VIEW3D_OT_moodboard_drawer_grip" in body
    assert "MIXIE_OT_moodboard_graph_select" not in body
    assert "MIXIE_OT_moodboard_select_image" not in body
    py = _read(
        ROOT / "src/scripts/mixar/modules/moodboard/ui/keymap.py"
    )
    assert "Moodboard Drawer Grip" in py
    assert "_bind_moodboard_pointer(km_drawer)" not in py
    assert "_bind_moodboard_pointer(km)" in py
    assert "mixie.moodboard_annotation_erase" in py


def test_tilde_toggles_drawer_in_c_and_addon():
    """`~` is AccentGrave on the dedicated View3D map (first on the
    viewport), the Window map (header / topbar), and addon 3D View
    (beats the View pie after a preset reload). Poll finds the Zen
    drawer instead of requiring CTX_wm_area to be the 3D view.
    """
    ops = _read(VIEW3D / "view3d_moodboard_drawer_ops.cc")
    core = _read(VIEW3D / "view3d_moodboard_drawer.cc")
    space = _read(VIEW3D / "space_view3d.cc")
    py = _read(ROOT / "src/scripts/mixar/modules/moodboard/ui/keymap.py")

    keymap = _fn(_strip_comments(ops), "void view3d_moodboard_drawer_keymap(")
    assert '"Moodboard Drawer"' in keymap
    assert '"Window"' in keymap
    assert "EVT_ACCENTGRAVEKEY" in keymap
    assert "KM_SHIFT" in keymap
    assert "VIEW3D_OT_moodboard_drawer_toggle" in keymap
    assert '"Moodboard Drawer Grip"' in keymap

    poll = _fn(_strip_comments(ops), "static bool drawer_op_poll(")
    assert "view3d_moodboard_drawer_area_find" in poll

    attach = _fn(_strip_comments(core), "void view3d_moodboard_drawer_toggle_handlers_add(")
    assert '"Moodboard Drawer"' in attach
    assert "WM_event_add_keymap_handler_priority" in attach
    assert "view3d_moodboard_drawer_toggle_handlers_add(wm, region)" in space

    assert "def _bind_drawer_toggle(" in py
    assert py.count("_bind_drawer_toggle(") == 4  # def + Drawer + Window + 3D View
    assert "view3d.moodboard_drawer_toggle" in py
    assert "'Moodboard Drawer'" in py
    assert "'Window'" in py
    assert "'3D View'" in py
    assert "shift" in py[py.index("def _bind_drawer_toggle(") : py.index("def _ensure_addon_keymap(")]


def test_macos_grave_key_is_accent_grave():
    """The physical `~` key must arrive as AccentGrave. Upstream #if 0's
    kVK_ANSI_Grave and only maps the '`' character, so Shift+` is Unknown.
    """
    cocoa = _read(ROOT / "src/intern/ghost/intern/GHOST_SystemCocoa.mm")
    convert = _fn(cocoa, "static GHOST_TKey convertKey(")
    ansi_off = convert.index("#if 0")
    ansi_end = convert.index("#endif", ansi_off)
    live = convert[ansi_end:]
    assert "case kVK_ANSI_Grave:" in live
    assert "GHOST_kKeyAccentGrave" in live[live.index("case kVK_ANSI_Grave:") :][:200]
    assert "case '~':" in convert
    assert "GHOST_kKeyAccentGrave" in convert[convert.index("case '~':") :][:200]


def test_user_close_releases_annotate_and_erase():
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_ops.cc")),
        "static void drawer_release_annotate(",
    )
    assert "mixie_moodboard_annotating" in body
    assert "mixie_moodboard_erasing" in body


def test_grip_click_flips_target_and_escape_restores_invoke_state():
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_ops.cc")),
        "static wmOperatorStatus drawer_grip_modal(",
    )
    assert "start_target" in body
    assert "EVT_ESCKEY" in body
    assert "start_amount" in body
    # Click (not dragged) flips the intent, not amount > 0.5.
    assert "view3d_moodboard_drawer_target(C) != 0 ? 0 : 1" in body


def test_canvas_qa_targets_register_on_the_drawer_host():
    source = _strip_comments(_read(MIXIE / "mixie_moodboard_qa_targets.cc"))
    assert "Mixar_qa_register_target_provider(SPACE_VIEW3D" in source
    assert "MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT" in source


def test_external_grip_teardown_restores_modal_cursor():
    source = _read(VIEW3D / "view3d_moodboard_drawer_ops.cc")
    registration = _fn(source, "static void VIEW3D_OT_moodboard_drawer_grip(")
    assert "ot->cancel = drawer_grip_cancel;" in registration
    cancel = _fn(source, "static void drawer_grip_cancel(")
    assert "if (wmWindow *win = CTX_wm_window(C))" in cancel
    assert "WM_cursor_modal_restore(win);" in cancel


def test_drawer_slide_is_time_based_and_redraws_only_the_region():
    """A per-tick fraction plus ED_area_tag_redraw is what made the slide hitch.

    Overlay redraw of the WINDOW region is allowed so navigation gizmos can
    slide with the board without rebuilding the 3D scene.
    """
    geom = _read(DRAWER_GEOM)
    assert _define_float(geom, "VIEW3D_MOODBOARD_DRAWER_SLIDE_SECONDS") == 0.28

    core = _read(VIEW3D / "view3d_moodboard_drawer.cc")
    assert "BLI_time_now_seconds" in core
    assert "drawer_ease_out_cubic" in core
    assert "slide_held" in core
    assert "TIMERNOTIFIER" in core
    assert "drawer_region_listener" in core
    assert "ED_region_tag_redraw_editor_overlays" in core

    ops = _read(VIEW3D / "view3d_moodboard_drawer_ops.cc")
    assert "0.22f" not in ops
    # Full-area redraw hitches the slide; overlay-only WINDOW refresh is required
    # so navigation gizmos can track the board.
    assert "ED_area_tag_redraw(" not in ops
    assert "ED_area_tag_refresh" not in ops
    assert "ED_region_tag_redraw" in ops
    assert "ED_region_tag_redraw_editor_overlays" in ops
    assert "view3d_moodboard_drawer_display_amount" in ops
    assert "view3d_moodboard_drawer_slide_begin" in ops

    draw = _read(VIEW3D / "view3d_moodboard_drawer_draw.cc")
    assert "view3d_moodboard_drawer_display_amount" in draw


def test_navigate_gizmos_slide_with_open_moodboard_drawer():
    """Open drawer parks navigation left of the grip, like the N-panel clamp."""
    source = _read(VIEW3D / "view3d_gizmo_navigate.cc")
    assert "view3d_moodboard_drawer_display_amount" in source
    assert "view3d_moodboard_drawer_grip_rect_for" in source
    assert "grip.xmin - region->winrct.xmin" in source
    assert "sidebar->winrct.xmin - region->winrct.xmin" in source


def test_viewport_center_reads_the_open_drawer():
    source = _read(UTILS)
    start = source.index("def get_moodboard_viewport_center")
    body = source[start : source.index("\n    return 0.0, 0.0", start)]
    assert "VIEW_3D" in body and "TOOL_PROPS" in body
    assert "mixar_moodboard_drawer_amount" in body


def test_reference_drop_handler_precedes_native_image_empty_import():
    """WM_event_add_dropbox_handler prepends, so Mixie must be added last."""
    source = _strip_comments(_read(VIEW3D / "space_view3d.cc"))
    body = _fn(source, "static void view3d_main_region_init(")
    assert body.index('WM_dropboxmap_find("View3D"') < body.index('WM_dropboxmap_find("Mixie"')


def test_file_and_image_id_drop_payloads_cannot_contaminate_one_another():
    source = _strip_comments(_read(MIXIE / "mixie_dragdrop.cc"))
    body = _fn(source, "static void moodboard_image_drop_copy(")
    for name in ("filepath", "multi_filepaths", "image_name"):
        assert f'RNA_struct_property_unset(drop->ptr, "{name}")' in body
        assert f'RNA_string_set(drop->ptr, "{name}", "")' not in body


def test_the_drawer_tab_uses_shared_palette_and_hit_geometry():
    draw = _read(VIEW3D / "view3d_moodboard_drawer_draw.cc")
    assert 'const char *label = "Moodboard";' in draw
    assert "MIXAR_THEME_LOAD(outer_green, CinemaPillOnB)" in draw
    assert "MIXAR_THEME_LOAD(inner_dark, ViewportFill)" in draw
    assert "draw_roundbox_4fv_ex(&tab, inner_dark, outer_green, 0.0f" in draw
    assert "view3d_moodboard_drawer_grip_rect_for" in draw
    assert "GRIP_DOT" not in draw


def test_drawer_hosts_the_same_canvas_chrome_as_the_editor():
    draw = _read(VIEW3D / "view3d_moodboard_drawer_draw.cc")
    chrome = _read(MIXIE / "mixie_draw_moodboard_chrome.cc")
    panels = _read(ROOT / "src/scripts/mixar/modules/moodboard/ui/panels/canvas_chrome.py")
    assert "mixie_moodboard_canvas_draw(C, region)" in draw
    assert "WM_paneltype_find(panel_id, false)" in chrome
    assert "ui::UI_paneltype_draw" in chrome
    assert "draw_moodboard_add_tools(self.layout, context)" in panels
    assert "ED_region_panels(" not in _strip_comments(chrome)


def test_slide_preserves_the_canvas_aspect_correction_for_hit_testing():
    body = _fn(
        _strip_comments(_read(VIEW3D / "view3d_moodboard_drawer_draw.cc")),
        "void view3d_moodboard_drawer_region_draw(",
    )
    assert "region->v2d.cur = saved_cur" not in body
    assert "region->v2d.cur.xmin += delta" in body


def test_pie_popup_actions_keep_the_originating_drawer_region():
    source = _read(ROOT / "src/scripts/mixar/modules/moodboard/ui/moodboard_pie_menu.py")
    # Blender's menu default INVOKE_REGION_WIN silently substitutes the 3D
    # viewport, making every feature popup disabled on an open drawer.
    assert "pie.operator_context = 'INVOKE_DEFAULT'" in source
