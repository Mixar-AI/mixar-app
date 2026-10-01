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
    assert '"Cannot decode media preview: %s"' in drop
    # Both stills and movies decode before boarding; only stills are packed.
    assert "if (image->source != IMA_SRC_MOVIE)" in drop
    assert "BKE_image_packfiles" in drop


def test_inline_playback_is_compiled_and_reachable_from_video_clicks():
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")
    select = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "mixie_moodboard_ops_preview.cc" in cmake
    assert "moodboard_toggle_video_playback" in select
    assert "play_button_hit" in select
    assert "KM_DBL_CLICK" in select
    assert "moodboard_video_play_radius(v2d, media_rect)" in select
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


def test_zen_drawer_is_a_canvas_for_video_hover():
    """The Zen Mode moodboard is a View3D TOOL_PROPS drawer hosting the Mixie
    canvas. Hover used to require RGN_TYPE_WINDOW only, so every mousemove in
    the drawer forced hovered_index to -1 and stopped playback immediately —
    play was never continuous. The drawer must hit-test like the Mixie window;
    Mixie sidebar/header regions stay non-canvas so leaving the tile still
    stops playback.
    """
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")
    common = _read(SPACE_MIXIE / "mixie_moodboard_ops_common.hh")

    assert "hover_region_is_canvas" in preview
    assert "RGN_TYPE_TOOL_PROPS" in preview
    assert "moodboard_zen_drawer_active" in preview
    # The WINDOW-only gate that broke the drawer must not be the sole test.
    hover = preview.split("moodboard_video_hover_invoke(")[1].split(
        "\n}\n", 1
    )[0]
    assert "hover_region_is_canvas(C, region)" in hover
    assert "region->regiontype == RGN_TYPE_WINDOW ?" not in hover
    assert "moodboard_zen_drawer_active" in common
    assert 'STREQ(workspace->id.name + 2, "Zen Mode")' in common


def test_canvas_filters_preserve_leave_events_and_view2d_timers():
    """A chrome hit must not suppress hover cleanup or timer communication."""
    layout = _read(SPACE_MIXIE / "mixie_moodboard_node_layout.cc")
    poll = layout.split("bool moodboard_canvas_handler_poll(", 1)[1].split("\n}\n", 1)[0]
    upstream = poll.index("WM_event_handler_region_v2d_mask_poll")
    pointer_gate = poll.index("return moodboard_canvas_point_is_interactive")
    for event in ("ISKEYBOARD(event->type)", "ISTIMER(event->type)", "MOUSEMOVE", "WINDEACTIVATE"):
        assert upstream < poll.index(event) < pointer_gate
    drawer = _read(ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer.cc")
    wrapper = drawer.split("bool view3d_moodboard_drawer_canvas_handler_poll(", 1)[1].split("\n}\n", 1)[0]
    assert "moodboard_canvas_handler_poll(win, area, region, event)" in wrapper
    assert "event->xy" not in wrapper  # No second gate may discard accepted leave/timer events.


def test_template_hover_uses_destination_bounds_instead_of_event_routing():
    drop = _read(SPACE_MIXIE / "mixie_moodboard_template_drag.cc")
    poll = drop.split("static bool template_drop_poll(", 1)[1].split("\n}\n", 1)[0]
    assert "moodboard_canvas_point_is_interactive(CTX_wm_area(C), region, event->xy)" in poll
    assert "moodboard_canvas_handler_poll" not in poll


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
    assert "moodboard_video_play_radius(v2d, media_rect)" in draw
    assert "if (is_playing)" in draw


def test_the_play_button_never_outgrows_the_video_it_sits_on():
    """A fixed 28px button is most of a small tile once the canvas is zoomed
    out, which reads as the button GROWING as you zoom away. It is capped
    against the tile's shorter side and shrinks with it from there — and draw,
    the standalone hit-test and the node hit-test all take the radius from the
    ONE definition, or the clickable disc parts company with the glyph."""
    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")

    assert "MOODBOARD_VIDEO_PLAY_MAX_FRACTION" in intern
    assert "float moodboard_video_play_radius(View2D *v2d, const rctf &media_rect);" in intern

    body = geometry.split("float moodboard_video_play_radius(")[1].split("\n}\n")[0]
    assert "MOODBOARD_VIDEO_PLAY_RADIUS_PX / view_scale" in body
    assert "MOODBOARD_VIDEO_PLAY_MAX_FRACTION" in body
    assert "std::min(" in body

    # The only places the raw pixel constant may still be spelled out.
    users = [
        path.name
        for path in SPACE_MIXIE.glob("*.cc")
        if "MOODBOARD_VIDEO_PLAY_RADIUS_PX" in _read(path)
    ]
    assert users == ["mixie_moodboard_graph_geometry.cc"]


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


def test_every_video_gen_limit_lookup_passes_the_selected_model():
    """`video_gen` serves models whose reference ceilings differ by more than
    3x and `input_spec` is service-level, so a lookup that omits the model
    reads the widest set — and every one of these call sites decides what gets
    compressed and uploaded before the backend ever sees the payload."""
    operator = _read(MOODBOARD / "ui/operators/video_gen_ops.py")
    drawer = _read(MOODBOARD / "ui/video_gen_drawer.py")
    node = _read(MOODBOARD / "core/node_execution.py")
    handoff = _read(
        ROOT / "src/scripts/mixar/modules/director/core/handoff.py"
    )

    assert "get_video_generation_limits(service_key, model)" in operator
    assert "get_video_generation_limits(service_key, model)" in node
    # The drawer and the Director handoff have no model in hand, so both go
    # through the one resolver rather than re-deriving the tab's selection.
    assert "selected_video_model_slug(scene)" in drawer
    assert "selected_video_model_slug(scene)" in handoff
    # A bare service-only lookup anywhere here is the bug this pins.
    for source in (operator, drawer, node, handoff):
        assert 'get_video_generation_limits("video_gen")' not in source
        assert "get_video_generation_limits(service_key)" not in source
