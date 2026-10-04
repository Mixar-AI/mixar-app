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
    assert "BLI_timer_register" in preview
    assert "moodboard_video_playback_frame" in preview


def _function(source: str, signature: str) -> str:
    return source.split(signature, 1)[1].split("\n}\n", 1)[0]


def test_inline_playback_runs_to_the_end_wherever_the_pointer_goes():
    """A pass-through MOUSEMOVE monitor used to stop a movie the moment the
    pointer left its tile (or crossed into the sidebar/header), so a clip could
    only be watched by holding the mouse still over it. Nothing may stop
    playback but the movie's own play/pause gesture or its end."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    keymap = _read(MOODBOARD / "ui/keymap.py")

    for source in (preview, space, intern):
        assert "moodboard_video_hover" not in source
        assert "stop_video_playback_outside_tile" not in source
    assert "moodboard_video_hover" not in keymap
    # The sidebar/header maps existed only to carry that monitor.
    assert '"Mixie Sidebar"' not in space
    assert '"Mixie Header"' not in space


def test_inline_playback_plays_once_and_rests_on_the_first_frame():
    """No hover stop means nothing else would ever end a looping clip, so a
    movie plays through ONCE and returns to its poster frame."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    frame_at = _function(preview, "static int playback_frame_at(")
    assert "%" not in frame_at, "playback must not wrap around and loop"
    assert "if (frame > playback.frame_count)" in frame_at
    finished = frame_at.split("if (frame > playback.frame_count)", 1)[1]
    assert "playback.playing = false;" in finished
    assert "playback.current_frame = 1;" in finished

    # The frame that ends playback must already report "not playing", or the
    # last redraw paints a pause glyph over the poster frame.
    frame = _function(preview, "int moodboard_video_playback_frame(")
    assert frame.index("playback_frame_at(") < frame.index("*r_is_playing = playback.playing")

    # A press after the clip ran out restarts it instead of "pausing" it.
    toggle = _function(preview, "bool moodboard_toggle_video_playback(")
    settle = toggle.index("playback_frame_at(playback, now);")
    assert settle < toggle.index("if (playback.playing)")


def test_playback_redraw_tick_retires_itself_when_the_last_movie_ends():
    """The redraw clock is a context-free BLI timer, so the tick that sees the
    last movie end is the one that stops redrawing -- no event has to reach
    the canvas, which may never happen once the pointer is elsewhere."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "WM_event_timer_add_notifier" not in preview
    tick = _function(preview, "static double video_redraw_tick(")
    assert "prune_dead_playback_entries(G_MAIN);" in tick
    assert "playback_frame_at(entry.second, now);" in tick
    # The final tick still redraws, to put the poster and play glyph back.
    assert "WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE, nullptr);" in tick
    assert "return any_playing ? MOODBOARD_VIDEO_REDRAW_SECONDS : -1.0;" in tick

    ensure = _function(preview, "static void video_redraw_tick_ensure(")
    assert "BLI_timer_is_registered(tick_id)" in ensure
    toggle = _function(preview, "bool moodboard_toggle_video_playback(")
    assert "video_redraw_tick_ensure();" in toggle


def test_qa_exports_movie_playback_state():
    """The harness can only assert playback through a QA target: the state is
    C++ runtime-only. The disc must come from the shared play radius and the
    node preview bounds, like the draw pass and both click hit-tests."""
    qa = _read(SPACE_MIXIE / "mixie_moodboard_qa_targets.cc")

    assert '"moodboard_video"' in qa
    assert "moodboard_video_play_radius(v2d, tile)" in qa
    assert "moodboard_graph_node_preview_bounds(*card, &tile)" in qa
    assert "moodboard_video_playback_frame(image, &playing)" in qa
    assert "t.sel = playing;" in qa
    assert "t.value = std::to_string(frame);" in qa
    # A node offers playback for its first embedded movie only, like the click.
    assert "moodboard_find_embedded_media_index(&scene_ptr, owner) != i" in qa
    graph_video = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_video.cc")
    assert "moodboard_find_embedded_media_index(scene_ptr, node_id)" in graph_video


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
    assert "BLI_timer_unregister" in preview
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
