# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for the movie card hover controls, video sound and
the preview player window. The behaviour is compiled C++, so these pin the
decisions that are easy to regress silently."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
DRAWER = ROOT / "src/source/blender/editors/space_view3d/view3d_moodboard_drawer.cc"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(source: str, signature: str) -> str:
    return source.split(signature, 1)[1].split("\n}\n", 1)[0]


def test_hover_is_presentation_only_and_never_stops_playback():
    """A clip must keep playing to its end wherever the pointer goes; hover
    only dims the card and shows its controls."""
    card = _read(SPACE_MIXIE / "mixie_moodboard_video_card.cc")
    for call in ("video_session_pause", "video_session_toggle",
                 "moodboard_toggle_video_playback", "video_sessions_release_owner"):
        assert call not in card


def test_both_canvas_hosts_track_card_hover_on_every_mouse_move():
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    drawer = _read(DRAWER)
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard.cc")

    assert "art->cursor = mixie_main_region_cursor;" in space
    assert "art->event_cursor = true;" in space
    assert "moodboard_video_card_hover_update(win, area, region);" in _function(
        space, "static void mixie_main_region_cursor(")
    assert "ed::mixie::moodboard_video_card_hover_update(win, area, region);" in drawer
    # Cards re-register every frame, so hover matches what is on screen.
    assert "moodboard_video_cards_frame_begin(region);" in draw
    # Leaving a region sends it no event: a watchdog clears the hover.
    card = _read(SPACE_MIXIE / "mixie_moodboard_video_card.cc")
    assert "static double hover_watch_tick(" in card


def test_card_controls_are_preview_play_sound_in_that_order():
    card_api = _read(SPACE_MIXIE / "mixie_moodboard_video_card.hh")
    assert "MOODBOARD_VIDEO_CARD_PREVIEW = 0," in card_api
    assert "MOODBOARD_VIDEO_CARD_PLAY = 1," in card_api
    assert "MOODBOARD_VIDEO_CARD_SOUND = 2," in card_api
    # Every translation unit that includes the internal header still sees it.
    assert '#include "mixie_moodboard_video_card.hh"' in _read(SPACE_MIXIE / "mixie_intern.hh")
    press = _function(_read(SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc"),
                      "wmOperatorStatus moodboard_video_card_press(")
    assert '"MIXIE_OT_moodboard_preview_media"' in press
    # Opening a window moves the context; the click must finish where it began.
    assert press.index("CTX_wm_window(C)") < press.index("WM_operator_name_call_ptr")
    assert "CTX_wm_window_set(C, win);" in press


def test_sound_is_on_by_default_and_audio_failures_are_not_fatal():
    header = _read(SPACE_MIXIE / "mixie_moodboard_video_session.hh")
    session = _read(SPACE_MIXIE / "mixie_moodboard_video_session.cc")
    device = _read(SPACE_MIXIE / "mixie_moodboard_video_audio_device.cc")

    assert "bool muted = false;" in header
    start = _function(session, "static void audio_start(")
    # Blender closes its own device whenever the scene is not playing, so the
    # movie opens one of its own (never taking over Blender's slot).
    assert "audio_device_ensure()" in start
    assert "aud::DeviceManager::getDevice()" not in start
    ensure = _function(device, "std::shared_ptr<aud::IDevice> audio_device_ensure(")
    assert "factory->openDevice()" in ensure
    for source in (session, device):
        assert "DeviceManager::setDevice(device" not in source
        assert "BKE_sound_play_scene" not in source and "scene->runtime->audio" not in source
    assert "new aud::File(path)" in start
    assert "catch (aud::Exception &)" in start
    assert "session.has_audio = false;" in start
    # Pause stops the track; seek restarts it at the new position.
    assert "audio_stop(session);" in _function(session, "void video_session_pause(")
    assert "audio_start(bmain, session, target);" in _function(
        session, "void video_session_seek(")


def test_preview_player_owns_its_window_input_and_closes_safely():
    player = _read(SPACE_MIXIE / "mixie_moodboard_video_player.cc")
    space = _read(SPACE_MIXIE / "space_mixie.cc")

    assert "WM_operatortype_append(MIXIE_OT_moodboard_video_player);" in space
    # The Image Editor is only the frame renderer: its chrome is hidden and
    # its picture follows the player's clock, not the scene frame.
    hide = _function(player, "static void hide_editor_chrome(")
    assert "RGN_FLAG_HIDDEN" in hide
    sync = _function(player, "static void player_sync_frame(")
    assert "sima->iuser.flag &= ~IMA_ANIM_ALWAYS;" in sync
    # The editor's refresh recomputes framenr from the scene frame, so the
    # session frame is reached through sfra, never by writing framenr.
    assert "sima->iuser.sfra = cfra - video_session_frame(session) + 1;" in sync
    assert "BKE_image_user_frame_calc(player.image, &sima->iuser, cfra);" in sync
    assert "iuser.framenr =" not in sync
    # Controls are painted over the picture by a window draw callback.
    assert "WM_draw_cb_activate(win, video_player_draw, player)" in player
    # No close control on the picture: the title bar or Esc closes, and Esc
    # must not free the window from inside its own modal handler.
    assert "PLAYER_CLOSE" not in _read(SPACE_MIXIE / "mixie_moodboard_video_player.hh")
    modal = _function(player, "static wmOperatorStatus video_player_modal(")
    assert "request_window_close(win);" in modal
    assert "wm_window_close(" not in modal
    tick = _function(player, "static double close_windows_tick(")
    assert "BLI_findindex(&wm->windows, win) != -1" in tick
    # The OS close button cancels the player, which releases the session.
    cancel = _function(player, "static void video_player_cancel(")
    assert "player_release(C, op);" in cancel
    release = _function(player, "static void player_release(")
    assert "video_sessions_release_owner(player);" in release
    assert "WM_draw_cb_exit(" in release


def test_player_window_is_chromeless_and_sized_for_watching():
    """The hidden Image Editor regions offer no edge arrows or reveal tabs, its
    navigation gizmos are off, and a small clip opens at a watchable size."""
    player = _read(SPACE_MIXIE / "mixie_moodboard_video_player.cc")
    area = _read(ROOT / "src/source/blender/editors/screen/area.cc")
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc")

    hide = _function(player, "static void hide_editor_chrome(")
    assert "ED_area_mixar_chromeless_set(area_is_player);" in hide
    assert "sima->gizmo_flag |= SI_GIZMO_HIDE;" in hide
    poll = _function(area, "static bool region_azone_edge_poll(")
    assert "g_mixar_area_chromeless(area)" in poll
    # Registered before the chrome is hidden, so the predicate sees the area.
    invoke = _function(player, "static wmOperatorStatus video_player_invoke(")
    assert invoke.index("g_players.push_back(player);") < invoke.index(
        "hide_editor_chrome(*player, area);")
    assert "VIDEO_PREVIEW_MIN_W * UI_SCALE_FAC" in preview


def test_a_silent_clip_never_opens_the_audio_device():
    """An open device holds the machine awake (macOS PreventUserIdleSystemSleep).
    A movie without an audio stream must be found out BEFORE the device opens,
    and any play that leaves the device open without a sounding track must arm
    the idle close, which audio_stop() only arms for a handle."""
    session = _read(SPACE_MIXIE / "mixie_moodboard_video_session.cc")
    device = _read(SPACE_MIXIE / "mixie_moodboard_video_audio_device.cc")
    start = _function(session, "static void audio_start(")

    probe = start.index("reader = session.audio_sound->createReader();")
    assert probe < start.index("audio_device_ensure()")
    # The probe IS the reader the track plays from: no second file open.
    assert "device->play(reader, true)" in start
    assert "device->play(session.audio_sound" not in start
    no_stream = start[probe:start.index("audio_device_ensure()")]
    assert "session.has_audio = false;" in no_stream and "return;" in no_stream
    tail = start[start.rindex("if (!session.audio_handle) {"):]
    assert "audio_device_schedule_close();" in tail
    # The close itself only drops the device once no session holds a handle.
    tick = _function(device, "static double audio_device_close_tick(")
    assert "video_sessions_any_audio_handle()" in tick


def test_a_reused_preview_window_runs_one_player():
    """WM_window_open reuses an open temporary Image Editor window, so a second
    Preview lands in the window that already plays the first. Its player must
    end (modal, draw callback, timer, sessions, sound) before the new media is
    shown -- for a still too -- and the chrome it hid comes back."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc")
    player = _read(SPACE_MIXIE / "mixie_moodboard_video_player.cc")
    header = _read(SPACE_MIXIE / "mixie_moodboard_video_player.hh")

    execute = _function(preview, "static wmOperatorStatus moodboard_preview_media_exec(")
    stop = execute.index("video_player_stop_in_window(C, CTX_wm_window(C));")
    assert execute.index("WM_window_open(") < stop
    assert stop < execute.index("ED_space_image_set(bmain, sima, image, false);")
    assert stop < execute.index("start_video_player(C, image, op->reports);")
    assert "void video_player_stop_in_window(bContext *C, wmWindow *win);" in header

    body = _function(player, "void video_player_stop_in_window(")
    assert "WM_operator_find_modal_by_type(win, ot)" in body
    # Released, unhooked and freed at once: a postponed removal would leave a
    # handler pointing at a freed operator for window.modal_operators to read.
    order = [body.index(step) for step in (
        "restore_editor_chrome(*player);",
        "player_release(C, op);",
        "WM_event_remove_modal_handler(&win->runtime->modalhandlers, op, false);",
        "WM_operator_free(op);")]
    assert order == sorted(order)
    # Only what the player hid comes back.
    hide = _function(player, "static void hide_editor_chrome(")
    assert "!(region.flag & RGN_FLAG_HIDDEN)" in hide
    assert "player.hidden_regions |= 1u << region.regiontype;" in hide
    restore = _function(player, "static void restore_editor_chrome(")
    assert "region.flag &= ~RGN_FLAG_HIDDEN;" in restore
    assert "if (!player.gizmos_were_hidden)" in restore

    # The tooltips and the description say what happens (adjacent C string
    # literals joined, as the compiler joins them).
    for source in (preview,
                   _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc"),
                   _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")):
        text = re.sub(r'"\s*\n\s*"', "", source)
        assert "Several" not in text
        assert "An open preview window is reused and shows this instead" in text


def test_sessions_are_matched_by_session_uid_not_address():
    """Sessions are keyed on the Image address; a datablock later allocated
    there (File > New, a deleted node) must not inherit the old frame, mute
    state or sound."""
    header = _read(SPACE_MIXIE / "mixie_moodboard_video_session.hh")
    session = _read(SPACE_MIXIE / "mixie_moodboard_video_session.cc")
    player = _read(SPACE_MIXIE / "mixie_moodboard_video_player.cc")
    draw = _read(SPACE_MIXIE / "mixie_moodboard_video_player_draw.cc")

    assert "unsigned int image_session_uid = 0;" in header
    ensure = _function(session, "MoodboardVideoSession *video_session_ensure(")
    assert "session.image_session_uid = image->id.session_uid;" in ensure
    assert ensure.index("video_session_find(image, owner)") < ensure.index("g_sessions.emplace(")
    find = _function(session, "MoodboardVideoSession *video_session_find(")
    assert "it->second.image_session_uid != image->id.session_uid" in find
    assert "audio_stop(it->second);" in find and "g_sessions.erase(it);" in find
    prune = _function(session, "void video_sessions_prune(")
    # Membership before the uid: only a live image may be dereferenced.
    assert prune.index("BLI_findindex(&bmain->images, session.image) != -1") < prune.index(
        "session.image->id.session_uid == session.image_session_uid")

    # The player checks the same before it reads its image (modal, draw, QA).
    live = _function(player, "static bool player_image_live(")
    assert live.index("BLI_findindex(&bmain->images, player.image) != -1") < live.index(
        "player.image->id.session_uid == player.image_session_uid")
    assert "player->image_session_uid = image->id.session_uid;" in player
    assert "video_session_find(player.image, &player)" not in draw
    assert draw.count("video_player_session_find(") == 2


def test_board_sessions_are_released_on_file_load():
    """Zen hosts the board in a View3D drawer, so the Mixie region exit that
    releases board sessions never runs there: a file-load callback does."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    hook = _function(preview, "static void board_sessions_load_pre(")
    assert "mixie_moodboard_video_playback_shutdown();" in hook
    register = _function(preview, "static void board_sessions_load_pre_register(")
    assert "static bCallbackFuncStore store = {};" in register
    assert "BKE_callback_add(&store, BKE_CB_EVT_LOAD_PRE);" in register
    board = _function(preview, "static MoodboardVideoSession *board_session(")
    assert board.index("board_sessions_load_pre_register();") < board.index(
        "video_session_ensure(bmain, image, BOARD_OWNER)")
