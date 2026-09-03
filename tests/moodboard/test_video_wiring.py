# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for native moodboard movie integration.

The interaction code lives in Blender C++ and cannot be invoked from the
standalone pytest process. These assertions pin the registration and event
wiring that makes the compiled behavior reachable.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_native_drop_accepts_movies_and_validates_the_first_frame():
    dragdrop = _read(SPACE_MIXIE / "mixie_dragdrop.cc")
    drop = _read(SPACE_MIXIE / "mixie_moodboard_ops_drop.cc")

    assert "WM_drag_has_path_file_type(drag, FILE_TYPE_MOVIE)" in dragdrop
    assert "imb_ext_movie" in drop
    assert "BKE_image_acquire_ibuf" in drop
    assert "image->source == IMA_SRC_MOVIE" in drop


def test_inline_playback_is_compiled_and_reachable_from_video_clicks():
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")
    select = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "mixie_moodboard_ops_preview.cc" in cmake
    assert "moodboard_toggle_video_playback" in select
    assert "play_button_hit" in select
    assert "KM_DBL_CLICK" in select
    assert "MOODBOARD_VIDEO_PLAY_RADIUS_PX" in select
    assert "g_video_playback" in preview
    assert "BKE_image_acquire_ibuf" in preview
    assert "MOV_get_duration_frames" in preview
    assert "MOV_get_fps" in preview
    assert "WM_event_timer_add_notifier" in preview
    assert "moodboard_video_playback_frame" in preview


def test_inline_playback_stops_when_the_pointer_leaves_its_tile():
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "stop_video_playback_outside_tile" in preview
    assert "hovered_video_index_from_event" in preview
    assert "playback.playing = false" in preview
    assert "MIXIE_OT_moodboard_video_hover" in preview
    assert "Stop inline moodboard video playback when the pointer leaves its tile" in preview


def test_inline_playback_is_runtime_only_and_cleans_up_on_shutdown():
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "static std::unordered_map<Image *, MoodboardVideoPlayback>" in preview
    assert "playback_frame_at" in preview
    assert "mixie_moodboard_video_playback_shutdown" in preview
    assert "WM_event_timer_remove" in preview
    assert "g_video_playback.clear()" in preview
    assert "BKE_scene_add" not in preview
    assert "ED_screen_animation_play" not in preview


def test_movie_thumbnail_has_a_play_affordance():
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_images.cc")

    assert "image->source == IMA_SRC_MOVIE" in draw
    # Shared with the inference-node preview, hence the exported name.
    assert "mixie_draw_moodboard_video_overlay" in draw
    assert "MOODBOARD_VIDEO_PLAY_RADIUS_PX" in draw
    assert "if (is_playing)" in draw


def test_file_picker_keeps_movies_linked_to_their_source():
    image_ops = _read(MOODBOARD / "ui/operators/image_ops.py")
    # The loader itself lives in core/ so non-UI callers (the chat composer's
    # attachment mirroring) can reuse it without importing an operator module.
    media_import = _read(MOODBOARD / "core/media_import.py")

    assert 'getattr(bpy.path, "extensions_movie", ())' in image_ops
    assert "load_media_file_to_board" in image_ops
    assert "if img.source != 'MOVIE':" in media_import
    assert "img.pack()" in media_import


def test_video_generation_streams_selected_movies_and_imports_the_result():
    operator = _read(MOODBOARD / "ui/operators/video_gen_ops.py")
    drawer = _read(MOODBOARD / "ui/video_gen_drawer.py")
    media_import = _read(MOODBOARD / "core/media_import.py")
    queue_job = _read(
        ROOT
        / "src/scripts/mixar/modules/common/job_queue/core/generic_jobs.py"
    )

    assert "get_selected_moodboard_media_inputs" in operator
    assert "get_video_generation_limits" in operator
    assert "get_video_generation_limits" in drawer
    assert "_DEFAULT_LIMITS" not in operator
    assert 'kind="video"' in operator
    assert "video_inputs=video_inputs" in operator
    assert "StreamingVideoJob" in queue_job
    assert "stage_media(" in queue_job
    assert "reference_video_s3_keys" in queue_job
    assert "b64" not in queue_job[queue_job.index("class StreamingVideoJob"):]
    assert "mixar/generated_videos" in media_import
    assert "place_new_moodboard_item" in media_import
