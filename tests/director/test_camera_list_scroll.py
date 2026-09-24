# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The My Cameras card scrolls once the list outgrows its four rows.

The Cinema surface paints and never hit-tests, so the card has no handler of
its own: the wheel is an ordinary operator whose POLL is the scoping, the same
shape `MIXAR_OT_director_place_camera` uses on the aerial map.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"

CAMERAS = (VIEW3D / "view3d_director_cinema_cameras.cc").read_text(encoding="utf-8")
#: The wheel/trackpad gesture, split out of the card when the painter
#: reached the module size limit.
SCROLL = (VIEW3D / "view3d_director_cinema_camera_scroll.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
NUDGE = (VIEW3D / "view3d_director_nudge.cc").read_text(encoding="utf-8")
OVERLAY = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")


def test_the_operator_is_declared_and_registered():
    assert "void MIXAR_OT_director_scroll_cameras(wmOperatorType *ot);" in DIRECTOR_HH
    assert "WM_operatortype_append(MIXAR_OT_director_scroll_cameras);" in NUDGE


def test_the_poll_is_the_only_hit_test_and_it_is_scoped():
    body = SCROLL[SCROLL.index("bool camera_list_scroll_poll(bContext *C)") :]
    body = body[: body.index("\n}\n")]
    assert "view3d_director_is_directing" in body
    assert "area->spacetype == SPACE_VIEW3D" in body
    assert "region->regiontype == RGN_TYPE_WINDOW" in body
    # Polls carry no event; the cursor comes from the window's event state.
    assert "win->runtime->eventstate" in body
    assert "cinema_camera_list_contains(" in body


def test_contains_requires_an_overflowing_list_on_this_region():
    """Otherwise a four-camera scene would swallow the viewport's zoom, and a
    rect published by another region could answer this one's poll."""
    body = CAMERAS[CAMERAS.index("bool cinema_camera_list_contains(") :]
    body = body[: body.index("\n}\n")]
    assert "g_scroll.region == region" in body
    assert "scroll_max(g_scroll) > 0" in body


def test_the_scrollable_band_is_the_rows_not_the_whole_card():
    """A wheel over the caption or the Add Camera chip keeps its viewport
    meaning."""
    assert "g_scroll.rect = {card.xmin," in CAMERAS
    assert "first_row_top - CINEMA_LIST_PITCH * float(visible_rows) * u," in CAMERAS


def test_the_window_follows_the_live_camera_then_stays_put():
    """A highlight the card cannot show is worse than losing a scroll
    position — but a deliberate scroll must not snap back on the next draw.

    This test used to assert `followed = nullptr`, which is the code that
    made it snap back on EVERY draw; the docstring and the assertion said
    opposite things. What the second half means is below.
    """
    assert "if (g_scroll.followed != live) {" in CAMERAS
    assert "g_scroll.offset = cinema_list_window_start(count, active_index);" in CAMERAS
    scroll = CAMERAS[CAMERAS.index("bool cinema_camera_list_scroll(") :]
    scroll = scroll[: scroll.index("\n}\n")]
    assert "std::clamp(g_scroll.offset + delta, 0, maximum)" in scroll


def test_the_end_of_the_list_absorbs_the_wheel():
    """Letting it through would zoom the viewport from under a list the user
    is still scrolling."""
    body = SCROLL[SCROLL.index("wmOperatorStatus camera_list_scroll_exec(") :]
    body = body[: body.index("\n}\n")]
    assert "if (!cinema_camera_list_scroll(RNA_int_get(op->ptr, \"delta\"))) {" in body
    assert "return OPERATOR_FINISHED;" in body
    assert "OPERATOR_PASS_THROUGH" not in body


def test_the_published_rect_is_released_when_no_card_is_drawn():
    """A poll must never be answered by a card that is off screen."""
    assert HEADER.count("void cinema_camera_list_release(const ARegion *region);") == 1
    # Director off, and the compact layout that draws no columns.
    assert OVERLAY.count("cinema_camera_list_release(region);") == 2
    assert "cinema_camera_list_release(region);" in CAMERAS  # empty list


def test_a_scroll_position_is_view_state_not_an_undo_step():
    body = SCROLL[SCROLL.index("void MIXAR_OT_director_scroll_cameras(") :]
    assert "ot->flag = OPTYPE_INTERNAL;" in body
    assert "ot->flag = OPTYPE_UNDO" not in body


def test_no_keymap_item_owns_the_gesture():
    """It is a UI HANDLER, and that is the fix.

    The card is painted into the 3D viewport's own WINDOW region, so a wheel
    over it is a wheel over the viewport: a keymap item has to beat
    `view3d.zoom` past the mode keymaps, the active tool's keymap and the UI
    layer. Two rounds of widening the operator's poll did not make the list
    scroll, because the poll was never being asked. UI handlers run ahead of
    every keymap — the toast click handler is installed on this same region
    for exactly that reason.
    """
    bindings = re.findall(r'keymap_items\.new\(\s*"([^"]+)"', KEYMAP)
    assert "mixar.director_scroll_cameras" not in bindings, (
        "the gesture is the UI handler's; a keymap item would be a second owner"
    )
    assert "type='TRACKPADPAN'" not in KEYMAP
    assert "WHEELUPMOUSE" not in KEYMAP

def test_a_scrollbar_says_the_list_continues():
    assert "const int maximum = scroll_max(g_scroll);" in CAMERAS
    assert "if (maximum > 0) {" in CAMERAS


# -------------------------------------------------------------------------
# The trackpad. A wheel binding alone is not "scrollable".


KEYMAP = (
    ROOT / "src/scripts/mixar/modules/director/ui/keymap.py"
).read_text(encoding="utf-8")


def test_the_handler_takes_both_gestures():
    """A trackpad two-finger scroll arrives as MOUSEPAN, not
    WHEELUP/DOWNMOUSE, so a wheel-only path leaves the card dead on a
    laptop."""
    handler = SCROLL[SCROLL.index("int director_cinema_ui_handler(") :]
    handler = handler[: handler.index("\n}\n")]
    assert "ELEM(event->type, WHEELUPMOUSE, WHEELDOWNMOUSE, MOUSEPAN)" in handler
    assert "cinema_camera_list_contains(region, x, y)" in handler
    assert "cinema_camera_list_scroll(rows)" in handler
    # Scoped like the operator's poll was: directing, in a 3D viewport's
    # WINDOW region, and never consuming anything it does not own.
    assert "view3d_director_is_directing(CTX_data_scene(C))" in handler
    assert "region->regiontype != RGN_TYPE_WINDOW" in handler
    assert handler.count("return WM_UI_HANDLER_CONTINUE;") >= 3


def test_the_opaque_columns_swallow_the_gesture():
    """With "Lock Camera to View" on for the session, a wheel that falls
    through does not merely zoom — it dollies the shot camera out from under
    a card the director is reading."""
    handler = SCROLL[SCROLL.index("int director_cinema_ui_handler(") :]
    handler = handler[: handler.index("\n}\n")]
    tail = handler[handler.index("cinema_columns_contain(C, region, x, y)") :]
    assert "return WM_UI_HANDLER_BREAK;" in tail


def test_the_handler_is_installed_on_the_viewport_region():
    space = (VIEW3D / "space_view3d.cc").read_text(encoding="utf-8")
    assert "view3d_director_cinema_region_init(region);" in space
    init = space[space.index("static void view3d_main_region_init(") :]
    init = init[: init.index("view3d_director_cinema_region_init(region);")]
    # Alongside the other Mixar UI handlers, before any keymap is added.
    assert "WM_event_add_keymap_handler" not in init
    assert "void view3d_director_cinema_region_init(struct ARegion *region);" in (
        VIEW3D / "view3d_director.hh"
    ).read_text(encoding="utf-8")
    install = SCROLL[SCROLL.index("void view3d_director_cinema_region_init(") :]
    install = install[: install.index("\n}\n")]
    # Remove-then-add, so a re-init cannot stack a second handler.
    assert install.index("WM_event_remove_ui_handler") < install.index("WM_event_add_ui_handler")


def test_the_gesture_becomes_rows_through_the_published_pitch():
    """The list steps in ROWS, so a pixel gesture has to accumulate — and it
    accumulates against the pitch the CARD published, never a re-derived
    layout."""
    body = SCROLL[SCROLL.index("int pan_rows(") :]
    body = body[: body.index("\n}\n")]
    assert "cinema_camera_list_row_pitch()" in body
    assert "WM_event_absolute_delta_y(event)" in body
    # The remainder is carried, not dropped: a slow gesture must still move.
    assert "g_pan_remainder -= float(rows) * pitch;" in body


def test_natural_scrolling_is_not_inverted_twice():
    """`WM_event_absolute_delta_y` already accounts for the preference. A
    second inversion here is how this comes out backwards."""
    body = SCROLL[SCROLL.index("int pan_rows(") :]
    body = body[: body.index("\n}\n")]
    assert "-WM_event_absolute_delta_y" not in body
    assert "-float(WM_event_absolute_delta_y" not in body


def test_the_card_publishes_the_pitch_it_drew():
    assert "float cinema_camera_list_row_pitch();" in (
        VIEW3D / "view3d_director_cinema.hh"
    ).read_text(encoding="utf-8")
    assert "g_scroll.row_pitch = CINEMA_LIST_PITCH * u;" in CAMERAS
    assert "return g_scroll.row_pitch;" in CAMERAS


def test_the_gesture_state_lives_with_the_gesture():
    """The card publishes geometry; the remainder is the operator's own."""
    assert "g_pan_remainder" not in CAMERAS
    assert "float g_pan_remainder = 0.0f;" in SCROLL


# ---------------------------------------------------------------------------
# The window the card shows, and who owns it.


def test_a_scroll_adopts_the_live_camera_rather_than_forgetting_it():
    """Why the list would not scroll, through three rounds of fixing it.

    The card re-snaps its window onto the live camera's row whenever the
    camera it is FOLLOWING stops matching the live one — a highlight the card
    cannot show is worse than a lost scroll position. A scroll that set
    `followed` to null left it unequal to a live camera forever, so that
    re-snap fired on the very next draw, which is the draw the scroll itself
    tags. Every wheel step was undone before a frame of it could be seen.
    """
    scroll = CAMERAS[CAMERAS.index("bool cinema_camera_list_scroll(") :]
    scroll = scroll[: scroll.index("\n}\n")]
    assert "g_scroll.followed = g_scroll.live;" in scroll
    assert "g_scroll.followed = nullptr;" not in scroll


def test_the_painter_publishes_the_live_camera_for_it():
    """`cinema_camera_list_scroll` runs from an event, not a draw, so the
    live camera has to be waiting for it."""
    draw = CAMERAS[CAMERAS.index("void cinema_draw_camera_list(") :]
    assert "g_scroll.live = live;" in draw
    snap = draw.index("if (g_scroll.followed != live) {")
    assert draw.index("g_scroll.live = live;") < snap


def test_the_re_snap_still_follows_a_camera_change():
    """The scroll position is the user's until the LIVE camera changes; it
    was never meant to survive that."""
    draw = CAMERAS[CAMERAS.index("void cinema_draw_camera_list(") :]
    snap = draw[draw.index("if (g_scroll.followed != live) {") :]
    snap = snap[: snap.index("}")]
    assert "cinema_list_window_start(count, active_index)" in snap
    assert "g_scroll.followed = live;" in snap


def test_the_scroll_track_clears_the_rows_and_the_delete_chip():
    """Three bands share the card's right edge: the row, its delete chip and
    the track. They are laid out from one inset so they cannot meet."""
    assert "row.xmax = card.xmax - CINEMA_CARD_PAD * u;" in CAMERAS
    track = CAMERAS[CAMERAS.index("const rctf track = {") :]
    track = track[: track.index("};")]
    assert "CINEMA_CARD_PAD" in track
