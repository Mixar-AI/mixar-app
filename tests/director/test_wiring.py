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
    assert popovers.count("bl_region_type = 'HEADER'") == 2


def test_incremental_install_cannot_retain_removed_director_panel():
    cmake = CREATOR_CMAKE.read_text(encoding="utf-8")

    assert "file(REMOVE_RECURSE" in cmake
    assert "${TARGETDIR_VER}/scripts/mixar" in cmake


def test_native_viewport_surface_is_registered_from_view3d():
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    space = (VIEW3D / "space_view3d.cc").read_text(encoding="utf-8")

    for filename in (
        "view3d_director_overlay.cc",
        "view3d_director_state.cc",
        "view3d_director_timeline.cc",
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
        "MIXAR_OT_director_send_video",
    ):
        assert operator in overlay or operator in timeline
    assert "MIXAR_OT_director_toggle_timeline" in timeline
    assert "MIXAR_OT_director_toggle_immersive" in timeline
    assert "mixar.director_open_editor" in surface_ops
    assert "mixar.director_open_editor" in mixie_header


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
    assert "uiDefAutoButR" in timeline
    assert "view3d_director_active_shot_pointer" in timeline
    assert 'RNA_struct_find_property(&shot_ptr, "camera")' in timeline
    assert "view3d_director_active_shot_pointer" in state
    assert "enter_camera_view(context or bpy.context, camera, remember=False)" in properties


def test_native_timeline_tracks_playback_and_real_beat_span():
    timeline = (VIEW3D / "view3d_director_timeline.cc").read_text(
        encoding="utf-8"
    )
    preview = _read("ui/operators/capture_ops.py")

    assert "WM_event_timer_add_notifier" in timeline
    assert "PLAYBACK_REDRAW_INTERVAL" in timeline
    assert "ND_ANIMPLAY" in timeline
    assert "has_shot_span ? state.frame_end" in timeline
    assert "state.beats.size() < 2" in timeline
    assert "frames = sorted({beat.frame for beat in shot.beats})" in preview
    assert "Capture at least two camera beats to preview" in preview


def test_capture_shortcut_survives_gui_keyconfig_reload():
    keymap = _read("ui/keymap.py")

    assert 'keyconfigs", None), "addon"' in keymap
    assert 'name="3D View"' in keymap
    assert '"mixar.director_capture_beat"' in keymap
    assert "type='F'" in keymap
    assert "head=True" in keymap


def test_director_native_files_follow_the_module_size_limit():
    native_files = list(VIEW3D.glob("view3d_director*"))

    assert native_files
    for path in native_files:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 500, path.name
