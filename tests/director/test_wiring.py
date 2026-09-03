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


def test_camera_beats_key_native_data_and_pack_stills():
    capture = _read("core/capture.py")
    media_import = MOODBOARD_IMPORT.read_text(encoding="utf-8")

    assert 'camera.keyframe_insert(data_path="location"' in capture
    assert 'camera.data.keyframe_insert(data_path="lens"' in capture
    assert "repair_euler_rotation_continuity(camera)" in capture
    assert "bpy.ops.render.opengl" in capture
    # Capture packs the still into the blend but never boards it — stills reach
    # the moodboard only through the explicit Director export.
    assert "pack_still_image" in capture
    assert "import_packed_still" not in capture
    assert "image.pack()" in media_import
    assert "place_new_moodboard_item" in media_import


def test_camera_euler_continuity_is_repaired_at_every_output_boundary():
    capture = _read("core/capture.py")
    preview = _read("ui/operators/capture_ops.py")
    render = _read("core/render_outputs.py")
    shot_api = _read("core/shot_api.py")

    # New or deleted keys normalize immediately. Existing files normalize at
    # every action that evaluates an in-between camera pose.
    assert capture.count("repair_euler_rotation_continuity(camera)") == 2
    assert "repair_euler_rotation_continuity(shot.camera)" in preview
    assert "repair_euler_rotation_continuity(shot.camera)" in render
    assert "repair_euler_rotation_continuity(shot.camera)" in shot_api


def test_video_handoff_remains_catalog_driven_and_provider_neutral():
    handoff = _read("core/handoff.py")

    assert "get_video_generation_limits" in handoff
    # Tab labels are catalog-driven: the handoff must resolve the Video
    # Gen tab's current category through get_tab_category("video_gen")
    # with the literal only as the offline fallback.
    assert 'get_tab_category("video_gen", "Video Gen")' in handoff
    assert "region.active_panel_category = category" in handoff
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

    assert not (DIRECTOR / "ui/panels/director_popovers.py").exists()
    # Every popup is native now; no Python panel/popover survives.
    assert not (DIRECTOR / "ui/panels/render_popover.py").exists()
    assert "bl_region_type = 'HEADER'" not in python_sources


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
        "view3d_director_popup_shot.cc",
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

    for reference in (
        "view3d_director_shots_popup_create",
        "view3d_director_camera_popup_create",
        "view3d_director_animation_popup_create",
        "view3d_director_render_popup_create",
        "MIXAR_OT_director_capture_beat",
    ):
        assert reference in overlay or reference in timeline
    # Keyframe export lives inside the native Export popup, not the overlay.
    popup_render = (VIEW3D / "view3d_director_popup_render.cc").read_text(
        encoding="utf-8"
    )
    assert "MIXAR_OT_director_send_keyframes" in popup_render
    assert "MIXAR_OT_director_toggle_timeline" in timeline
    assert "MIXAR_OT_director_toggle_immersive" in timeline
    assert "mixar.director_pick_camera" in surface_ops
    assert "mixar.director_set_active_shot" in surface_ops
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


def test_single_keyframe_is_draggable_along_the_timeline():
    """Pressing a keyframe marker retimes it, not just jumps the playhead.

    A draft beat can be dragged: the modal jumps the playhead on invoke (so a
    click that never moves still just views the keyframe, matching the old
    jump behaviour) and slides the beat plus its matching native camera keys
    on MOUSEMOVE. A single beat is clamped to stay between its time-neighbours
    because two Director keys must never share a frame. First and last
    handles stay draggable too — see test_timeline_drag.py. Locked shots stay
    view-only: the C++ handler only starts the drag when the shot is unlocked
    and otherwise falls back to jump_beat.
    """
    timeline_ops = _read("ui/operators/timeline_ops.py")
    timeline_core = _read("core/timeline.py")
    interaction = (
        VIEW3D / "view3d_director_timeline_interaction.cc"
    ).read_text(encoding="utf-8")

    assert "class MIXAR_OT_director_drag_beat" in timeline_ops
    assert "MIXAR_OT_director_drag_beat" in timeline_ops.split("classes = (", 1)[1]
    assert "move_single_beat" in timeline_ops
    assert "def move_single_beat" in timeline_core
    assert '"mixar.director_drag_beat"' in interaction
    assert "begin_beat_drag" in interaction
    # Locked shots never start the drag; jump_beat is the view-only fallback.
    assert "!state.locked && begin_beat_drag" in interaction
    assert '"mixar.director_jump_beat"' in interaction


def test_keyframes_delete_from_timeline_with_standard_keys():
    """X / Delete / Backspace over the timeline remove a keyframe.

    While directing, `mixar.director_block_input` (the Object Mode / WINDOW
    keymap guard) swallows X/Del to protect scene objects, but it never sees
    keys pressed over the timeline's own CHANNELS region. So the native
    timeline handler deletes its own keyframe: the one under the cursor, else
    the one under the playhead, else the active one — through the existing
    `mixar.director_remove_beat` operator. Locked takes stay read-only.
    """
    interaction = (
        VIEW3D / "view3d_director_timeline_interaction.cc"
    ).read_text(encoding="utf-8")

    for key in ("EVT_XKEY", "EVT_DELKEY", "EVT_BACKSPACEKEY"):
        assert key in interaction, key
    assert "beat_to_delete" in interaction
    assert '"mixar.director_remove_beat"' in interaction
    assert "state.has_shot && !state.locked" in interaction


def test_orphaned_keyframes_prune_when_native_keys_deleted_elsewhere():
    """Deleting camera keys in the Dope Sheet/Timeline must not leave stale
    orange handles on the Director strip.

    The strip draws from ``beats``, but the pose lives in native F-curves. A
    depsgraph handler watches the native Director key count while directing
    and, on a genuine deletion (count drops below the beat count — never a
    move, which keeps the count), a timer prunes orphaned beats through the
    ordinary ``remove_beat`` path. Following ``auto_key``, the handler only
    detects; the timer mutates (editing data inside ``depsgraph_update_post``
    is unsafe). The ``ui/`` bridge installs it like ``auto_key_watch``.
    """
    beat_sync = _read("core/beat_sync.py")
    watch = _read("ui/beat_sync_watch.py")

    assert "depsgraph_update_post" in beat_sync
    assert "@persistent" in beat_sync
    assert "def prune_orphaned_beats" in beat_sync
    assert "from .capture import remove_beat" in beat_sync
    assert "remove_beat(scene, shot, index)" in beat_sync
    # Detect in the handler, mutate in the timer (never mutate in the handler).
    assert "bpy.app.timers.register(_sync_timer" in beat_sync
    # Never destroy a beat + its still on a MOVE (native count stays equal).
    assert "len(native) >= len(shot.beats)" in beat_sync
    # Mirror native insertion: keys the strip never saw become beats.
    assert "def adopt_native_keyframes" in beat_sync
    assert "native - covered" in beat_sync
    assert "beat_sync.register()" in watch

    # Directing entry and shot/camera switches cause no depsgraph tick, so
    # they must request reconciliation explicitly or a natively keyed
    # camera keeps an empty strip until an unrelated edit ticks the watcher.
    assert "def request_reconcile" in beat_sync
    properties = _read("ui/properties/director_properties.py")
    # One definition plus the three switch paths: shot activation, camera
    # assignment, and directing entry.
    assert properties.count("_request_beat_reconcile()") == 4
    assert "update=_on_directing_update" in properties


def test_camera_switches_hand_the_selection_to_the_new_camera():
    """Precise gizmos and transform keys follow the selection.

    Every deliberate camera switch — shot activation, camera assignment,
    session start, new shot, new take — selects the new camera. Plain view
    entry must NOT: captures re-enter the camera view, and stealing the
    selection there breaks flows acting on the selected object (character
    Animation presets).
    """
    viewport = _read("core/viewport.py")
    properties = _read("ui/properties/director_properties.py")
    session = _read("ui/operators/session_ops.py")

    assert "def select_camera_object" in viewport
    # Precise mode reuses the one selection helper.
    assert "select_camera_object(context, camera)" in viewport
    # Both switch callbacks select, gated on an active directing session.
    assert properties.count("select_camera_object(") == 2
    # Session entry selects explicitly: is_directing is still False there.
    assert session.count("select_camera_object(") == 3
    # enter_camera_view runs on every capture — it never touches selection.
    enter_view = viewport.split("def enter_camera_view", 1)[1]
    enter_view = enter_view.split("\ndef ", 1)[0]
    assert "select_camera_object" not in enter_view


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


def test_splat_scene_stills_capture_through_a_real_render():
    """A splat scene's keyframe still must be a real EEVEE render.

    ``render.opengl`` produces a blank frame in splat scenes: the KIRI
    proxy draws only during interactive viewport redraws (never inside an
    OpenGL render), the splat mesh itself is eye-hidden, and the
    ``splat_render_camera`` handlers that push camera matrices into the
    geometry-nodes sockets fire only for real renders. The capture path
    must branch to ``render.render`` with the shot camera and restore
    engine, samples, and scene camera afterwards.
    """
    capture = _read("core/capture.py")

    assert "def _render_splat_still" in capture
    assert "scene_has_splats(scene)" in capture
    assert "_render_splat_still(scene, camera)" in capture
    assert "enable_render_updates(scene.objects)" in capture
    assert "bpy.ops.render.render(write_still=True)" in capture
    assert "render.engine = old_engine" in capture
    assert "scene.camera = old_camera" in capture


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

    assert "group_above" in overlay
    assert "group_gap" in overlay
    assert "RAIL_DIVIDER" not in overlay
    rail = overlay[overlay.index("void draw_tool_rail"):overlay.index("void draw_empty_state")]
    assert "director_overlay_panel_draw" not in rail
    assert "view3d_director_moves_popup_create" in rail
    assert "view3d_director_shots_popup_create" in rail
    assert "view3d_director_camera_popup_create" in rail
    assert "view3d_director_animation_popup_create" in rail
    # Camera tools never hide behind selection: a character ADDS its
    # animation tool to the rail instead of swapping the camera tools out
    # (the camera is only clickable via its gate rim in camera view, so
    # selection must not gate the mode's backbone). Navigate/Precise are
    # deliberately NOT here — they live on the camera gate and the dock.
    assert "character ? 4 : 3" in rail
    assert "MIXAR_OT_director_navigate" not in rail
    assert "MIXAR_OT_director_precise" not in rail


def test_camera_control_is_navigate_only_and_text_only():
    """Precise is hidden until its role is clear; Navigate is just the word.

    Artist feedback: the Precise gizmo mode confused more than it helped, and
    the hand icon on Navigate read as a pan tool. The operator and the
    `navigation_mode` property survive (Precise stays reachable for future
    surfaces); no native surface draws its button, and Navigate renders as a
    text-only button on the camera gate only — the timeline dock's copy
    duplicated it and was removed (same artist feedback).
    """
    frame = (VIEW3D / "view3d_director_overlay_frame.cc").read_text(
        encoding="utf-8"
    )
    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(
        encoding="utf-8"
    )
    camera_ops = _read("ui/operators/camera_ops.py")

    assert "MIXAR_OT_director_precise" not in frame
    assert "MIXAR_OT_director_precise" not in timeline
    assert "class MIXAR_OT_director_precise" in camera_ops
    assert '"Navigate"' in frame
    assert "MIXAR_OT_director_navigate" not in timeline
    # Text-only: the hand icon is gone from Navigate everywhere. The one
    # ICON_VIEW_PAN left on the gate belongs to the drag-frame tool.
    assert frame.count("ICON_VIEW_PAN") == 1
    assert "ICON_VIEW_PAN" not in timeline
    assert "ICON_ORIENTATION_GIMBAL" not in frame
    assert "ICON_ORIENTATION_GIMBAL" not in timeline


def test_auto_key_uses_native_timeline_record_icons():
    """The Auto Key toggle mirrors Blender's timeline auto-keying button.

    Native auto-key is `ICON_RECORD_OFF` flipping to `ICON_RECORD_ON` when
    armed (rna_scene.cc ui_icon on `use_keyframe_insert_auto`), not a static
    REC glyph.
    """
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(
        encoding="utf-8"
    )

    assert "ICON_RECORD_ON" in overlay
    assert "ICON_RECORD_OFF" in overlay
    assert "ICON_REC," not in overlay


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


def test_camera_trajectory_overlay_is_curve_sampled_and_cached():
    """The 3D path overlay must never scrub the scene to sample itself.

    Samples come from evaluating the camera's location F-curves directly
    (pure curve math, handheld modifiers included) through the slotted-
    action-safe helper, cached behind an animation signature; only the
    one-point playhead marker recomputes per redraw. Drawn always-on-top
    in the timeline strip's orange with green keyframe dots and the
    timeline-playhead blue marker, gated by the Path toggle in the Camera
    popup's Guides row.
    """
    trajectory = _read("core/trajectory.py")
    overlay = _read("ui/trajectory_overlay.py")
    properties = _read("ui/properties/director_properties.py")
    popup_shot = (VIEW3D / "view3d_director_popup_shot.cc").read_text(encoding="utf-8")

    assert "from .anim_curves import assigned_fcurves" in trajectory
    assert ".evaluate(frame)" in trajectory
    assert "frame_set(" not in trajectory
    assert "def _signature" in trajectory
    assert "MAX_SAMPLES" in trajectory
    assert "'POST_VIEW'" in overlay
    assert "POLYLINE_UNIFORM_COLOR" in overlay
    assert "depth_test_set('NONE')" in overlay
    assert "PATH_COLOR" in overlay and "BEAT_COLOR" in overlay
    assert "show_trajectory" in overlay
    assert "show_trajectory: BoolProperty" in properties
    assert '"show_trajectory"' in popup_shot


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
    # Inherited from the parent snapshot: the parent's RNA reference dies
    # when create_shot() reallocates the shots collection.
    assert "take.handheld = parent.handheld" in shot_api
    assert "parent = _ShotSnapshot(shot)" in shot_api
    assert '"handheld"' in popup
    assert '"handheld_strength"' in popup


def test_character_animation_presets_are_real():
    """The Animation popover keys blocking motion, not a placeholder."""
    presets = _read("core/animation_presets.py")
    moves_ops = _read("ui/operators/moves_ops.py")
    popup_shot = (VIEW3D / "view3d_director_popup_shot.cc").read_text(encoding="utf-8")

    for key in ("WALK", "RUN", "TURN_LEFT", "TURN_RIGHT", "TURN_AROUND", "IDLE"):
        assert key in presets, key
        assert f'"{key}"' in popup_shot, key
    assert 'group="Director Character"' in presets
    assert "MIXAR_OT_director_apply_animation" in moves_ops
    assert '"MIXAR_OT_director_apply_animation"' in popup_shot
    assert '"animation_seconds"' in popup_shot
    # The Shots and Camera popups carry no duplicated controls: navigation
    # and lens/aspect each keep their single home elsewhere.
    assert "MIXAR_OT_director_navigate" not in popup_shot
    assert "MIXAR_OT_director_set_lens" not in popup_shot
    assert '"MIXAR_OT_director_set_active_shot"' in popup_shot
    assert '"MIXAR_OT_director_new_shot"' in popup_shot
    assert '"MIXAR_OT_director_finish"' in popup_shot


def test_director_native_files_follow_the_module_size_limit():
    native_files = list(VIEW3D.glob("view3d_director*"))

    assert native_files
    for path in native_files:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 500, path.name
