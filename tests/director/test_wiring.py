# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level reachability contracts for the Blender-only Director UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
CREATOR_CMAKE = ROOT / "src/source/creator/CMakeLists.txt"
MOODBOARD_IMPORT = (
    ROOT / "src/scripts/mixar/modules/moodboard/core/media_import.py"
)


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


def test_director_state_is_persistent_but_session_flag_is_not():
    source = _read("ui/properties/director_properties.py")

    assert "bpy.types.Scene.mixar_director = PointerProperty" in source
    assert "shots: CollectionProperty(type=MixarDirectorShot" in source
    assert "beats: CollectionProperty(type=MixarDirectorBeat" in source
    assert 'options={\'SKIP_SAVE\', \'HIDDEN\'}' in source


def test_camera_beats_key_native_data_and_capture_to_moodboard():
    capture = _read("core/capture.py")
    media_import = MOODBOARD_IMPORT.read_text(encoding="utf-8")

    assert 'camera.keyframe_insert(data_path="location"' in capture
    assert 'camera.data.keyframe_insert(data_path="lens"' in capture
    assert "bpy.ops.render.opengl" in capture
    assert "import_packed_still" in capture
    assert "image.pack()" in media_import
    assert "place_new_moodboard_item" in media_import


def test_video_handoff_remains_catalog_driven_and_provider_neutral():
    handoff = _read("core/handoff.py")
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")

    assert "get_video_generation_limits" in handoff
    assert 'region.active_panel_category = "Video Gen"' in handoff
    assert "MIXAR_OT_director_send_video" in overlay
    assert "seedance" not in handoff.lower()


def test_director_has_no_n_panel_implementation():
    panel_path = DIRECTOR / "ui/panels/director_panel.py"
    python_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in DIRECTOR.rglob("*.py")
    )

    assert not panel_path.exists()
    assert "DIRECTOR_PANEL_CATEGORY" not in python_sources
    assert "bl_region_type = 'UI'" not in python_sources
    assert 'bl_idname = "MIXAR_PT_director"' not in python_sources

    popovers = _read("ui/panels/director_popovers.py")
    render_popover = _read("ui/panels/render_popover.py")
    assert popovers.count("bl_region_type = 'HEADER'") == 3
    assert render_popover.count("bl_region_type = 'HEADER'") == 1


def test_incremental_install_cannot_retain_removed_director_panel():
    cmake = CREATOR_CMAKE.read_text(encoding="utf-8")

    assert "file(REMOVE_RECURSE" in cmake
    assert "${TARGETDIR_VER}/scripts/mixar" in cmake


def test_native_viewport_surface_is_registered_from_view3d():
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    space = (VIEW3D / "space_view3d.cc").read_text(encoding="utf-8")

    for filename in (
        "view3d_director_overlay.cc",
        "view3d_director_overlay_frame.cc",
        "view3d_director_popup.cc",
        "view3d_director_state.cc",
        "view3d_director_timeline.cc",
        "view3d_director_timeline_draw.cc",
        "view3d_director_timeline_interaction.cc",
    ):
        assert filename in cmake
    assert "view3d_director_overlay_draw" in space
    assert "view3d_director_timeline_region_register" in space
    assert "view3d_director_timeline_region_ensure" in space
    assert "ED_KEYMAP_UI" in space
    assert "st->keymap = view3d_keymap;" in space
    assert '"Director View"' not in space

    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(
        encoding="utf-8"
    )
    assert "BLI_insertlinkbefore" in timeline
    assert "BKE_regiontype_from_id" in timeline
    assert "RGN_FLAG_POLL_FAILED" in timeline
    assert "art->regionid = RGN_TYPE_CHANNELS" in timeline
    assert "VIEW3D_DIRECTOR_TIMELINE_HEIGHT" in timeline
    assert "ED_region_header_init" not in timeline


def test_native_surface_reaches_the_phase_zero_directing_actions():
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")
    surface_ops = _read("ui/operators/surface_ops.py")
    mixie_header = (
        ROOT / "src/scripts/mixar/modules/space_mixie/ui/header.py"
    ).read_text(encoding="utf-8")

    for operator in (
        "MIXAR_OT_director_show_shots",
        "MIXAR_OT_director_show_camera",
        "MIXAR_OT_director_capture_beat",
        "MIXAR_OT_director_show_render",
        "MIXAR_OT_director_send_keyframes",
        "MIXAR_OT_director_send_video",
    ):
        assert operator in overlay or operator in timeline
    assert "MIXAR_OT_director_toggle_timeline" in timeline
    assert "MIXAR_OT_director_toggle_immersive" in timeline
    assert "mixar.director_pick_camera" in surface_ops
    assert "mixar.director_show_animation" in surface_ops
    assert "mixar.director_open_editor" not in surface_ops
    assert "mixar.director_open_editor" not in mixie_header


def test_native_surface_uses_timeline_camera_dropdown_without_top_switcher():
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(
        encoding="utf-8"
    )
    state = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
    properties = _read("ui/properties/director_properties.py")

    assert "draw_top_dock" not in overlay
    assert '"3D Editor"' not in overlay
    assert '"Canvas"' not in overlay
    assert "region->winy - unit * 2 - gap * 2" in overlay
    assert "region->winy - unit * 6" not in overlay
    surface_ops = _read("ui/operators/surface_ops.py")

    assert '"MIXAR_OT_director_pick_camera"' in timeline
    assert "latest_shot_index_for_camera" in surface_ops
    assert "view3d_director_active_shot_pointer" in state
    assert "enter_camera_view(context or bpy.context, camera, remember=False)" in properties
    assert "update=_on_active_shot_change" in properties
    assert "scope_preview_range(scene, shot)" in properties


def test_native_timeline_tracks_playback_and_real_beat_span():
    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(
        encoding="utf-8"
    )
    timeline_draw = (
        VIEW3D / "view3d_director_timeline_draw.cc"
    ).read_text(encoding="utf-8")
    preview = _read("ui/operators/capture_ops.py")

    assert "WM_event_timer_add_notifier" in timeline
    assert "PLAYBACK_REDRAW_INTERVAL" in timeline
    assert "ND_ANIMPLAY" in timeline
    assert "state.frame_end" in timeline_draw
    assert "runtime->view_span_frames" in timeline_draw
    assert "state.beats.size() < 2" in timeline
    assert "frames = sorted({beat.frame for beat in shot.beats})" in preview
    assert "Capture at least two keyframes to preview" in preview


def test_native_timeline_has_flow_style_strip_drag_and_horizontal_zoom():
    timeline_draw = (
        VIEW3D / "view3d_director_timeline_draw.cc"
    ).read_text(encoding="utf-8")
    interaction = (
        VIEW3D / "view3d_director_timeline_interaction.cc"
    ).read_text(encoding="utf-8")
    timeline_ops = _read("ui/operators/timeline_ops.py")
    timeline_core = _read("core/timeline.py")

    assert "STRIP_COLOR" in timeline_draw
    assert "major_tick_seconds" in timeline_draw
    assert 'BLI_snprintf(label, sizeof(label), "%.2f", seconds)' in timeline_draw
    assert "ICON_CAMERA_DATA" in timeline_draw
    assert "MOUSEZOOM" in interaction
    assert "MOUSEPAN" in interaction
    assert "WHEELUPMOUSE" in interaction
    assert '"mixar.director_drag_strip"' in interaction
    assert '"mixar.director_scrub"' in interaction
    assert "class MIXAR_OT_director_scrub" in timeline_ops
    assert "self._original_frame" in timeline_ops
    assert "shift_camera_beats" in timeline_ops
    assert "point.handle_left[0] += delta" in timeline_core
    assert "point.handle_right[0] += delta" in timeline_core
    assert "refresh_manifest(context.scene, shot)" in timeline_ops


def test_capture_shortcut_survives_gui_keyconfig_reload():
    keymap = _read("ui/keymap.py")

    assert 'keyconfigs", None), "addon"' in keymap
    assert 'name="3D View"' in keymap
    assert '"mixar.director_capture_beat"' in keymap
    assert "type='F'" in keymap
    assert "head=True" in keymap


def test_capture_still_works_on_video_output_scenes():
    """A legacy .blend with FFMPEG output must still capture PNG stills.

    Blender 5 filters ``file_format`` by ``media_type``: selecting PNG while
    the scene renders video raises ``enum "PNG" not found in ('FFMPEG')``.
    The capture path must enter the IMAGE namespace first and restore the
    media type BEFORE the saved file format, which only exists again inside
    its own namespace.
    """
    capture = _read("core/capture.py")

    assert '"media_type": getattr(image_settings, "media_type", None)' in capture
    assert "image_settings.media_type = 'IMAGE'" in capture
    set_media = capture.index("image_settings.media_type = 'IMAGE'")
    set_format = capture.index("image_settings.file_format = 'PNG'")
    assert set_media < set_format
    restore_media = capture.index('image_settings.media_type = old["media_type"]')
    restore_format = capture.index('image_settings.file_format = old["format"]')
    assert restore_media < restore_format


def test_navigate_supervises_walk_for_esc_and_cursor_reset():
    """Esc must stop navigation in place and the pointer must come back.

    Native walk maps Esc to CANCEL, which snaps the camera back to its
    pre-walk pose, and it releases the pointer wherever the grab began. The
    Navigate operator wraps the running walk in its own modal handler: it
    re-applies the pose captured at the Esc press once walk's revert has run,
    warps the cursor back to the middle of the viewport on every exit, and
    draws an aim marker while the pointer is hidden.
    """
    camera_ops = _read("ui/operators/camera_ops.py")
    viewport = _read("core/viewport.py")

    assert "return bpy.ops.view3d.walk('INVOKE_DEFAULT'), target" in viewport
    assert '"VIEW3D_OT_walk"' in camera_ops
    assert "modal_operators" in camera_ops
    assert "'ESC'" in camera_ops
    assert "_exit_pose" in camera_ops
    assert "{'PASS_THROUGH'}" in camera_ops
    assert "cursor_warp" in camera_ops
    assert "_draw_walk_aim" in camera_ops
    assert "'POST_PIXEL'" in camera_ops
    assert "modal_handler_add" in camera_ops
    assert "def cancel(self, context):" in camera_ops


def test_directing_absorbs_object_editing_shortcuts():
    """Transform/delete/chrome hotkeys must not leak through while directing.

    The reported leak was S scaling the scene mid-shot. View3D dispatches its
    WINDOW-region keymaps head to tail — mode keymaps ("Object Mode" owns
    G/R/S, the Alt clears, and X/Del), then "3D View Generic" (the N/T chrome
    toggles), then "3D View" — and a guard parked in a later keymap never
    sees a key an earlier one binds. Every guard must therefore live in the
    keymap that dispatches first for its key, and all of them are poll-gated
    on ``is_directing`` so each key falls back to its native meaning the
    moment the Director surface closes. Director binds no ``N``/``O``
    shortcuts: they can never win against those earlier keymaps, so the
    buttons carry no key hints either.
    """
    keymap = _read("ui/keymap.py")
    camera_ops = _read("ui/operators/camera_ops.py")
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")

    assert "class MIXAR_OT_director_block_input" in camera_ops
    assert '"mixar.director_block_input"' in keymap
    for guarded in (
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'G', {})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'R', {})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'S', {})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'G', {\"alt\": True})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'X', {})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'DEL', {})",
        "(\"Object Mode\", ('EMPTY', 'WINDOW'), 'DEL', {\"shift\": True})",
        "(\"3D View Generic\", ('VIEW_3D', 'WINDOW'), 'T', {})",
        "(\"3D View Generic\", ('VIEW_3D', 'WINDOW'), 'N', {})",
        "(\"3D View\", ('VIEW_3D', 'WINDOW'), 'S', {\"shift\": True})",
    ):
        assert guarded in keymap, guarded
    assert '"mixar.director_navigate", \'N\'' not in keymap
    assert '"mixar.director_precise", \'O\'' not in keymap
    assert '"Navigate  N"' not in overlay
    assert '"Precise  O"' not in overlay


def test_director_entry_sits_beside_the_topbar_mode_switch():
    """The Director toggle lives next to Engine/Zen Mode, not in View3D.

    The workflow module appends the mode switch to TOPBAR_MT_editor_menus;
    Director appends after it so both sit together, and the active session
    renders depressed. State flips also tag the topbar's global area, which
    ordinary screen iteration misses.
    """
    header = _read("ui/headers/director_header.py")
    properties = _read("ui/properties/director_properties.py")

    assert "TOPBAR_MT_editor_menus" in header
    assert "VIEW3D_HT_header" not in header
    assert "depress=True" in header
    assert '"global_areas"' in properties


def test_tool_rail_has_accent_highlight_and_grouping():
    """Rail buttons float without a container panel — their own emboss is
    the only rectangle (a container plus embossed buttons reads as double
    borders). Groups separate through wider spacing, and the active mode
    carries the single filled accent."""
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")

    assert "ACCENT_FILL" in overlay
    assert "ACCENT_BORDER" in overlay
    assert "group_above" in overlay
    assert "group_gap" in overlay
    assert "RAIL_DIVIDER" not in overlay
    rail = overlay[overlay.index("void draw_tool_rail"):overlay.index("void draw_empty_state")]
    assert "director_overlay_panel_draw" not in rail
    assert "view3d_director_moves_popup_create" in overlay
    # Camera tools never hide behind selection: a character ADDS its
    # animation tool to the rail instead of swapping the camera tools out
    # (the camera is only clickable via its gate rim in camera view, so
    # selection must not gate the mode's backbone).
    assert "character ? 6 : 5" in rail
    assert "character_tools" not in rail


def test_camera_moves_reuse_the_ordinary_capture_flow():
    """Presets must produce exactly what manual directing produces.

    Every move funnels through capture_beat — native keys, packed stills,
    manifest — and anchors at the current pose unless the playhead already
    holds a keyframe of this shot.
    """
    moves = _read("core/camera_moves.py")
    moves_ops = _read("ui/operators/moves_ops.py")
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")

    for key in (
        "ORBIT_LEFT",
        "ORBIT_RIGHT",
        "DOLLY_IN",
        "DOLLY_OUT",
        "CRANE_UP",
        "CRANE_DOWN",
        "PAN_LEFT",
        "PAN_RIGHT",
    ):
        assert key in moves, key
        # Identifiers are the frozen contract between the native popup rows
        # and the Python operator's enum.
        assert f'"{key}"' in popup, key
    assert "capture_beat(context, shot, state.beat_seconds)" in moves
    assert "interest_distance" in moves
    assert "MIXAR_OT_director_camera_move" in moves_ops
    assert '"MIXAR_OT_director_camera_move"' in popup
    assert "RNA_enum_set_identifier" in popup


def test_timeline_strip_can_split_and_delete():
    """Right-clicking the strip offers split and destructive editing.

    Split moves the beats after the playhead into a new shot on the SAME
    camera — native keys stay put, both shots scope their own preview
    range — and the first half stays active because the playhead sits in
    it. Clear removes every beat (keys + stills) through the ordinary
    remove_beat path, and Remove Shot is reachable while directing (the
    empty-state overlay takes over when the last shot goes).
    """
    shot_api = _read("core/shot_api.py")
    strip_ops = _read("ui/operators/strip_ops.py")
    session_ops = _read("ui/operators/session_ops.py")
    interaction = (
        VIEW3D / "view3d_director_timeline_interaction.cc"
    ).read_text(encoding="utf-8")

    assert "def split_shot" in shot_api
    assert "state.active_shot_index = original_index" in shot_api
    # Deleting the last reference to a camera must leave it genuinely
    # static: per-frame key deletion misses stray keys, so the transform/
    # lens F-curves (and handheld noise) are purged when the last beat or
    # the last shot referencing the camera goes — but never while another
    # take still shares the camera.
    capture = _read("core/capture.py")
    assert "def purge_camera_animation" in capture
    assert "def camera_shared_elsewhere" in capture
    assert "purge_camera_animation(shot.camera)" in capture
    assert "purge_camera_animation(camera)" in shot_api
    assert "camera_shared_elsewhere" in shot_api
    # Blender 5 stores animation in slotted actions: Action.fcurves is
    # gone, so every F-curve read/removal goes through core/anim_curves.py
    # (assigned-slot channelbag, legacy fallback for old files).
    anim_curves = _read("core/anim_curves.py")
    handheld_source = _read("core/handheld.py")
    timeline_source = _read("core/timeline.py")
    assert "animdata_get_channelbag_for_assigned_slot" in anim_curves
    assert "def remove_fcurves" in anim_curves
    assert "action.fcurves" not in capture
    assert "action.fcurves" not in handheld_source
    assert "assigned_fcurves" in handheld_source
    assert "remove_fcurves" in capture
    assert "from .anim_curves import assigned_fcurves" in timeline_source
    assert "class MIXAR_OT_director_split_strip" in strip_ops
    assert "class MIXAR_OT_director_clear_strip" in strip_ops
    assert "class MIXAR_OT_director_strip_menu" in strip_ops
    assert "remove_beat(context.scene, shot, index)" in strip_ops
    assert '"mixar.director_remove_shot"' in strip_ops
    assert "state.shots and not state.is_directing" not in session_ops
    assert "RIGHTMOUSE" in interaction
    assert '"mixar.director_strip_menu"' in interaction


def test_handheld_is_noise_modifiers_not_keyframes():
    """Handheld texture must never touch the captured keys.

    Jitter cannot be represented by sparse keyframes, so it lives as named
    noise F-modifiers on the camera's transform curves — keys store raw
    values, and everything that reads the EVALUATED camera (preview, guide
    videos, the manifest's `evaluated_get` sampling) carries the drift.
    Captures re-apply because the first capture creates the F-curves, and
    a new take inherits the parent's setting since it shares the camera.
    """
    handheld = _read("core/handheld.py")
    properties = _read("ui/properties/director_properties.py")
    capture = _read("core/capture.py")
    shot_api = _read("core/shot_api.py")
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")

    assert 'HANDHELD_MODIFIER_NAME = "Mixar Handheld"' in handheld
    assert "modifiers.new(type='NOISE')" in handheld
    assert "modifier.name == HANDHELD_MODIFIER_NAME" in handheld
    assert "keyframe_insert" not in handheld
    assert "handheld: BoolProperty" in properties
    assert "handheld_strength: FloatProperty" in properties
    assert "refresh_handheld(shot)" in capture
    assert "take.handheld = shot.handheld" in shot_api
    assert '"handheld"' in popup
    assert '"handheld_strength"' in popup


def test_character_animation_presets_are_real():
    """The Animation popover keys blocking motion, not a placeholder."""
    presets = _read("core/animation_presets.py")
    moves_ops = _read("ui/operators/moves_ops.py")
    popovers = _read("ui/panels/director_popovers.py")

    for key in ("WALK", "RUN", "TURN_LEFT", "TURN_RIGHT", "TURN_AROUND", "IDLE"):
        assert key in presets, key
    assert 'group="Director Character"' in presets
    assert "MIXAR_OT_director_apply_animation" in moves_ops
    assert '"mixar.director_apply_animation"' in popovers
    assert "coming soon" not in popovers.lower()
    assert '"animation_seconds"' in popovers


def test_director_native_files_follow_the_module_size_limit():
    native_files = list(VIEW3D.glob("view3d_director*"))

    assert native_files
    for path in native_files:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 500, path.name
