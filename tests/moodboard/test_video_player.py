# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for the movie card hover controls, video sound and
the preview player window. The behaviour is compiled C++, so these pin the
decisions that are easy to regress silently."""

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

    assert "bool muted = false;" in header
    start = _function(session, "static void audio_start(")
    # Blender closes its own device whenever the scene is not playing, so the
    # movie opens one of its own (never taking over Blender's slot).
    assert "audio_device_ensure()" in start
    assert "aud::DeviceManager::getDevice()" not in start
    ensure = _function(session, "static std::shared_ptr<aud::IDevice> audio_device_ensure(")
    assert "factory->openDevice()" in ensure
    assert "DeviceManager::setDevice(device" not in session
    assert "new aud::File(path)" in start
    assert "catch (aud::Exception &)" in start
    assert "session.has_audio = false;" in start
    assert "BKE_sound_play_scene" not in session and "scene->runtime->audio" not in session
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
    assert invoke.index("g_players.push_back(player);") < invoke.index("hide_editor_chrome(area);")
    assert "VIDEO_PREVIEW_MIN_W * UI_SCALE_FAC" in preview
