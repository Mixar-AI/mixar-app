# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contract of the Cinema Mode aerial map.

The right column's preview card is a live top-down render of the scene with
the shot camera on it; a LEFTMOUSE press over it runs the native
`MIXAR_OT_director_place_camera` modal, which places the camera at that
world XY (Z and rotation untouched). These pins keep the keymap contract in
`director/ui/keymap.py`, the painter, the render rule and the operator in
step without a build.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"

MINIMAP = (VIEW3D / "view3d_director_minimap.cc").read_text(encoding="utf-8")
EXTENTS = (VIEW3D / "view3d_director_minimap_extents.cc").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_minimap_draw.cc").read_text(encoding="utf-8")
OPS = (VIEW3D / "view3d_director_place_camera.cc").read_text(encoding="utf-8")
RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start):]
    return body[: body.index("\n}\n") + 3]


def test_keymap_binds_a_plain_left_press_in_the_addon_3d_view_keymap():
    """The item sits at the head of the addon "3D View" keymap with no
    modifiers, so it is asked before the stock `view3d.select` items and
    never claims Shift/Ctrl/Alt clicks."""
    assert '"director_place_camera",' in KEYMAP
    item = KEYMAP[KEYMAP.index('"mixar.director_place_camera"'):]
    item = item[: item.index("addon_keymaps.append")]
    assert "type='LEFTMOUSE'" in item
    assert "value='PRESS'" in item
    assert "head=True" in item
    for modifier in ("shift", "ctrl", "alt", "any", "oskey"):
        assert f"{modifier}=" not in item, modifier
    # Same keymap object as the F capture item: the "3D View" WINDOW keymap.
    before = KEYMAP[: KEYMAP.index('"mixar.director_place_camera"')]
    keymap_new = before.rfind("keyconfig.keymaps.new(")
    assert 'name="3D View"' in before[keymap_new:]
    assert "space_type='VIEW_3D'" in before[keymap_new:]
    assert "region_type='WINDOW'" in before[keymap_new:]


def test_operator_is_registered_from_the_director_operatortypes():
    nudge = (VIEW3D / "view3d_director_nudge.cc").read_text(encoding="utf-8")
    registration = _block(nudge, "void view3d_director_operatortypes()")
    assert "WM_operatortype_append(MIXAR_OT_director_place_camera);" in registration
    assert 'ot->idname = "MIXAR_OT_director_place_camera";' in OPS
    header = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
    assert "void MIXAR_OT_director_place_camera(wmOperatorType *ot);" in header
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    for name in (
        "view3d_director_minimap.cc",
        "view3d_director_minimap_draw.cc",
        "view3d_director_minimap_extents.cc",
        "view3d_director_place_camera.cc",
        "view3d_director_minimap.hh",
    ):
        assert name in cmake, name


def test_poll_scopes_the_left_press_to_the_map():
    poll = _block(OPS, "bool place_camera_poll(bContext *C)")
    assert "view3d_director_is_directing(" in poll
    assert "SPACE_VIEW3D" in poll and "RGN_TYPE_WINDOW" in poll
    assert "view3d_director_minimap_contains(" in poll
    assert "eventstate->xy" in poll
    assert "aerial_mode(C) && stage_contains(C, region, x, y)" in poll
    assert "ot->poll = place_camera_poll;" in OPS
    # A press the transform cannot map is handed back to the viewport.
    invoke = _block(OPS, "wmOperatorStatus place_camera_invoke(")
    assert "OPERATOR_CANCELLED | OPERATOR_PASS_THROUGH" in invoke
    assert "WM_event_add_modal_handler(C, op);" in invoke


def test_placement_keeps_z_and_rotation_and_writes_the_world_matrix():
    apply = _block(OPS, "void place_camera_apply(bContext *C, PlaceCameraData *data")
    assert "loc.x = xy[0];" in apply and "loc.y = xy[1];" in apply
    assert "loc.z" not in apply and "loc[2]" not in apply
    write = _block(OPS, "void place_camera_write(")
    assert "BKE_object_apply_mat4(camera, matrix.ptr(), true, true);" in write
    assert "DEG_id_tag_update(&camera->id, ID_RECALC_TRANSFORM);" in write
    assert "WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, camera);" in write
    assert "ED_region_tag_redraw(region);" in write
    assert "data->start_matrix = camera->object_to_world();" in OPS


def test_whole_drag_is_one_undo_step_and_esc_restores():
    assert "ot->flag = OPTYPE_UNDO;" in OPS
    assert "UNDO_GROUPED" not in OPS.replace("never UNDO_GROUPED", "")
    finish = _block(OPS, "wmOperatorStatus place_camera_finish(")
    assert "moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED" in finish
    modal = _block(OPS, "wmOperatorStatus place_camera_modal(")
    assert "case MOUSEMOVE:" in modal
    assert "event->val == KM_RELEASE" in modal
    assert "case EVT_ESCKEY:" in modal and "case RIGHTMOUSE:" in modal
    cancel = _block(OPS, "void place_camera_cancel(")
    assert "data->start_matrix" in cancel
    assert "ot->cancel = place_camera_cancel;" in OPS


def test_the_placement_resolves_the_shared_shot_camera():
    state = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
    assert "Object *view3d_director_shot_camera(Scene *scene, bool *r_locked)" in state
    nudge = (VIEW3D / "view3d_director_nudge.cc").read_text(encoding="utf-8")
    assert "return view3d_director_shot_camera(scene, r_locked);" in nudge
    assert OPS.count("view3d_director_shot_camera(") >= 3
    assert "view3d_director_shot_camera(scene, &locked)" in DRAW
    assert "This take is locked; start a new take to move the camera" in OPS


def test_qa_record_and_transform_share_the_map_rect_and_lay_no_button():
    painter = _block(DRAW, "void cinema_draw_minimap(")
    assert 'cinema_qa_record(region, inner, "director_minimap", "place", -1);' in painter
    assert "view3d_director_minimap_publish(" in painter
    # Both derive from the same `inner` rect; `map` is its integer form.
    assert "map.xmin = int(inner.xmin);" in painter
    assert "view3d_director_minimap_publish(region, map, world, inset_px, blit);" in painter
    assert "cinema_op_button(" not in DRAW
    assert "cinema_icon_button(" not in DRAW
    assert "uiDefButR(" not in DRAW
    contains = _block(MINIMAP, "bool view3d_director_minimap_contains(")
    assert "BLI_rcti_isect_pt(&g_transform.rect_region_px, x, y)" in contains


def test_the_world_mapping_is_clamped_inside_the_placeable_area():
    mapping = _block(MINIMAP, "bool view3d_director_minimap_world_from_region_px(")
    assert "std::clamp(float(x - t.rect_region_px.xmin) + 0.5f, inset, w - inset)" in mapping
    assert "r_xy[0] = t.world_xmin + (px / w) * (t.world_xmax - t.world_xmin);" in mapping
    assert "r_xy[1] = t.world_ymin + (py / h) * (t.world_ymax - t.world_ymin);" in mapping
    fit = _block(EXTENTS, "rctf view3d_director_minimap_fit_world(")
    assert "BLI_rctf_do_minmax_v(&world, lo);" in fit and "BLI_rctf_do_minmax_v(&world, hi);" in fit
    assert "MINIMAP_PAD_FRACTION = 0.1f" in EXTENTS
    assert "MINIMAP_PAD_MIN = 2.0f" in EXTENTS
    assert "MINIMAP_EMPTY_HALF = 10.0f" in EXTENTS


def test_the_right_panel_card_is_the_aerial_map_now():
    assert "cinema_draw_minimap(block, C, region, state, preview);" in RIGHT
    assert "CINEMA_PREVIEW_H" in RIGHT
    assert "cinema_image_preview(" not in RIGHT
    assert "beats_prop" not in RIGHT and "image_prop" not in RIGHT
    assert "Capture a keyframe" not in RIGHT
    assert 'DNA_image_types.h' not in RIGHT
    # The packed-still painter is kept for a future home.
    paint = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
    assert "void cinema_image_preview(" in paint


def test_the_render_is_throttled_guarded_and_restores_the_region_state():
    update = _block(MINIMAP, "bool view3d_director_minimap_update(")
    assert "ED_view3d_draw_offscreen_check_nested()" in update
    assert "DEG_get_update_count(depsgraph) == 0" in update
    assert "age < MINIMAP_MIN_RENDER_INTERVAL" in update
    assert "camera_moved && age < MINIMAP_CAMERA_MOVE_RENDER_INTERVAL" in update
    assert "MINIMAP_MIN_RENDER_INTERVAL = 0.1" in MINIMAP
    assert "MINIMAP_CAMERA_MOVE_RENDER_INTERVAL = 0.5" in MINIMAP
    # Framebuffer / viewport / scissor around the pass, then pixel space.
    assert "GPU_framebuffer_active_get()" in update
    assert "GPU_viewport_size_get_i(viewport_prev);" in update
    assert "GPU_scissor_get(scissor_prev);" in update
    order = [
        update.index("minimap_render(C, depsgraph, extents, world, w, h);"),
        update.index("GPU_framebuffer_bind(fb_prev);"),
        update.index("GPU_viewport(viewport_prev[0]"),
        update.index("GPU_scissor(scissor_prev[0]"),
        update.index("ED_region_pixelspace("),
    ]
    assert order == sorted(order)
    render = _block(MINIMAP, "void minimap_render(")
    assert "GPU_offscreen_bind(g_minimap.offscreen, true);" in render
    assert "GPU_offscreen_unbind(g_minimap.offscreen, true);" in render
    assert "orthographic_m4(winmat" in render
    assert "V3D_OFSDRAW_SHOW_GRIDFLOOR" in render
    assert "shading.type = OB_SOLID;" in render


def test_the_marker_is_painted_outside_the_render_pass():
    painter = _block(DRAW, "void cinema_draw_minimap(")
    blit = painter.index("GPU_viewport_draw_to_screen_ex(")
    assert painter.index("view3d_director_minimap_update(") < blit
    assert blit < painter.index("draw_wedge(")
    assert blit < painter.index("draw_dot(at, MINIMAP_MARKER_D * u, dot);")
    assert "draw_dot(" not in MINIMAP and "draw_wedge(" not in MINIMAP
    # The camera is excluded from the render by type; the marker is the only camera on the map.
    assert "(1 << OB_CAMERA)" in (VIEW3D / "view3d_director_minimap.hh").read_text(encoding="utf-8")
    assert "MINIMAP_HIDDEN_TYPES" in _block(MINIMAP, "void minimap_render(")
    assert 'caption_chip("Aerial view"' in painter
    assert "Add a camera to place it" in painter
    assert "locked ? 0.45f : 1.0f" in painter


def test_teardown_hooks_release_the_map():
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert "view3d_director_minimap_release(region, /*free_gpu=*/true);" in overlay
    assert "view3d_director_minimap_release(region, /*free_gpu=*/false);" in overlay
    space = (VIEW3D / "space_view3d.cc").read_text(encoding="utf-8")
    free = _block(space, "static void view3d_main_region_free(ARegion *region)")
    assert "view3d_director_minimap_region_free(region);" in free
    region_free = _block(MINIMAP, "void view3d_director_minimap_region_free(")
    assert "DRW_gpu_context_enable();" in region_free
    assert "DRW_gpu_context_disable();" in region_free


def test_every_minimap_file_stays_under_the_line_limit():
    for path in sorted(VIEW3D.glob("view3d_director_minimap*")):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path.name
    assert len(RIGHT.splitlines()) < 500
    assert len((VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8").splitlines()) < 500


def test_operator_id_matches_the_keymap_idname():
    assert re.search(r'ot->idname = "MIXAR_OT_director_place_camera";', OPS)
    assert '"mixar.director_place_camera"' in KEYMAP


def test_the_marker_margin_joins_the_camera_union_and_is_the_placement_clamp():
    """The camera's marker (dot radius + wedge length) is kept inside the map:
    the union is `camera ± margin` in world units from the PRE-margin rect's
    scale, corrected so it is at least that many pixels after the aspect fit,
    and the placement clamp published with the render IS that margin in final
    pixels — so a placement can never grow the rect (no feedback under a held
    press); it grows once, when the camera arrives at the boundary."""
    fit = _block(EXTENTS, "rctf view3d_director_minimap_fit_world(")
    assert "BLI_rctf_do_minmax_v(&pre, camera_xy);" in fit
    assert "const float scale_pre = std::max(BLI_rctf_size_x(&pre) / float(w)," in fit
    assert "margin_world = clamped_margin * scale_pre / (1.0f - clamped_margin / min_px);" in fit
    assert "{camera_xy[0] - margin_world, camera_xy[1] - margin_world}" in fit
    assert "{camera_xy[0] + margin_world, camera_xy[1] + margin_world}" in fit
    # The margin is computed BEFORE the aspect fit, the clamp AFTER it.
    assert fit.index("margin_world =") < fit.index("const float aspect = float(w) / float(h);")
    assert "*r_inset_px = int(std::ceil(margin_world / scale_final));" in fit
    assert fit.index("*r_inset_px = int(") > fit.index("const float aspect")
    painter = _block(DRAW, "void cinema_draw_minimap(")
    assert "const float margin_px = (MINIMAP_MARKER_D * 0.5f + MINIMAP_WEDGE_LEN) * u;" in painter
    assert "view3d_director_minimap_publish(region, map, world, inset_px, blit);" in painter
    update = _block(MINIMAP, "bool view3d_director_minimap_update(")
    assert "g_minimap.rendered_inset_px = inset_px;" in update
