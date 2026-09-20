# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One resize gesture for the whole canvas, and corners only.

A reference picture and an inference card used to scale in two different ways:
a picture had eight handles anchored on the opposite corner, a card had a single
bottom-right wedge that only ever grew down-right. Both now go through
``mixie_moodboard_resize_handles.cc`` -- the ONE definition of where a handle
is, which corner is held, and what the drag means.

All of it is C++ canvas code, so these are source-level pins on the contracts
that would otherwise drift silently (the standing pattern for this space).
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))

SHARED = "mixie_moodboard_resize_handles.cc"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Corners only
# --------------------------------------------------------------------------- #


def test_there_are_exactly_four_handles_and_they_are_the_corners():
    """The four edge midpoints are gone. On this canvas they meant "stretch one
    axis", which for a picture or a generated result is a distortion nobody
    asks for, and they crowded the corners that do the work."""
    # The resize-handle and canvas-frame declarations live in their own header
    # now (500-line rule); `mixie_intern.hh` includes it, so every consumer's
    # include list is unchanged.
    intern = _read(SPACE_MIXIE / "mixie_moodboard_hit_geometry.hh")
    assert "#define MOODBOARD_RESIZE_HANDLE_COUNT 4" in intern
    for corner in (
        "MOODBOARD_HANDLE_BOTTOM_LEFT",
        "MOODBOARD_HANDLE_BOTTOM_RIGHT",
        "MOODBOARD_HANDLE_TOP_RIGHT",
        "MOODBOARD_HANDLE_TOP_LEFT",
    ):
        assert f"#define {corner}" in intern, corner
    # And no midpoint constant crept back in under any name.
    for retired in ("HANDLE_TOP_CENTER", "HANDLE_BOTTOM_CENTER",
                    "HANDLE_LEFT_CENTER", "HANDLE_RIGHT_CENTER"):
        assert retired not in intern, retired


def test_the_shared_unit_places_only_four_corners():
    source = _read(SPACE_MIXIE / SHARED)
    body = source.split("void moodboard_resize_handle_positions(")[1].split("\n}")[0]
    # Every write is a rect EDGE, never a midpoint: a midpoint needs a /2.
    assert "/ 2" not in body and "* 0.5" not in body
    writes = re.findall(r"r_pos\[(MOODBOARD_HANDLE_\w+)\]\[([01])\]", body)
    assert len(writes) == 8, "four corners, x and y each"
    assert len({corner for corner, _axis in writes}) == 4


def test_no_surface_hand_rolls_an_eight_handle_array_any_more():
    """The three places that each carried their own `float positions[8][2]`
    were exactly how the media and card gestures came to differ."""
    for unit in (
        "mixie_select.cc",
        "mixie_draw_moodboard.cc",
        "mixie_moodboard_ops_select.cc",
    ):
        source = _read(SPACE_MIXIE / unit)
        assert "[8][2]" not in source, unit
        assert "h < 8" not in source, unit


# --------------------------------------------------------------------------- #
# One definition, read by draw, hit-test and drag
# --------------------------------------------------------------------------- #


def test_draw_and_hit_test_read_the_same_positions():
    """Otherwise the squares the user aims at and the region that responds
    drift apart at some zoom -- the rule the socket radii already follow."""
    assert "moodboard_resize_handle_positions(" in _read(
        SPACE_MIXIE / "mixie_draw_moodboard.cc"
    )
    # Both the media/text hit-test and the card's resolve through the shared
    # corner test rather than measuring their own boxes.
    assert _read(SPACE_MIXIE / "mixie_select.cc").count(
        "moodboard_resize_handle_at("
    ) == 2
    assert "moodboard_resize_handle_at(" in _read(
        SPACE_MIXIE / "mixie_moodboard_ops_graph_resize.cc"
    )


def test_both_drags_anchor_the_opposite_corner_through_the_one_rule():
    """A card used to hold its TOP edge and grow down-right; a picture anchored
    the diagonal corner. Same gesture, two behaviours -- now one."""
    for unit in ("mixie_moodboard_ops_select.cc",
                 "mixie_moodboard_ops_graph_resize.cc"):
        source = _read(SPACE_MIXIE / unit)
        assert "moodboard_resize_scale_factor(" in source, unit
        assert "moodboard_resize_place(" in source, unit
    # The media drag also reads the anchor point directly: a multi-image resize
    # scales every selected picture's POSITION about that same corner, so the
    # gaps between them are preserved.
    assert "moodboard_resize_handle_anchor(" in _read(
        SPACE_MIXIE / "mixie_moodboard_ops_select.cc"
    )


def test_the_scale_is_one_factor_for_both_axes():
    """Which is what locks the aspect. Taking it from the anchor's DIAGONAL
    (not from dx alone) is what makes the handle track the pointer in both
    directions at once."""
    body = _read(SPACE_MIXIE / SHARED).split(
        "float moodboard_resize_scale_factor("
    )[1].split("\n}")[0]
    assert "diagonal" in body
    assert "return sqrtf(dx * dx + dy * dy) / diagonal;" in body


def test_placing_is_derived_from_the_initial_rect_not_accumulated():
    """A dropped MOUSEMOVE must not leave the rect out of step with the
    pointer -- the same rule every other drag on this canvas follows."""
    resize = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_resize.cc")
    assert "initial_rect" in resize
    drag = resize.split("static void moodboard_graph_resize_drag(")[1].split("\n}")[0]
    # Every size in the drag comes off state.initial_rect.
    assert "state.initial_rect" in drag
    assert "+=" not in drag


def test_a_card_keeps_its_aspect_and_its_width_clamp():
    """A card's height follows the result image, so the aspect AT DRAG START is
    what it keeps, and the width stays inside the node bounds."""
    drag = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_resize.cc").split(
        "static void moodboard_graph_resize_drag("
    )[1].split("\n}")[0]
    assert "aspect" in drag
    assert "MOODBOARD_ACTION_NODE_MIN_W" in drag
    assert "MOODBOARD_ACTION_NODE_MAX_W" in drag


# --------------------------------------------------------------------------- #
# The card wears the same UI
# --------------------------------------------------------------------------- #


def test_a_card_draws_the_same_four_squares_as_a_picture():
    """Same UI means the same painter, not a look-alike: one definition of the
    squares, so they cannot come to differ in size, colour or placement."""
    chrome = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_chrome.cc")
    assert "void moodboard_draw_node_resize_handles(" in chrome
    assert "mixie_draw_moodboard_resize_handles(" in chrome
    # And the selection overlay a picture wears calls that same painter.
    assert "mixie_draw_moodboard_resize_handles(" in _read(
        SPACE_MIXIE / "mixie_draw_moodboard.cc"
    )


def test_a_cards_handles_only_appear_while_it_is_selected():
    """Handles are a property of the selection, exactly as they are for a
    picture. The wedge this replaces was painted on every card."""
    graph = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    call = graph.split("moodboard_draw_node_resize_handles(")[0]
    guard = call[call.rindex("if ("):]
    assert "selected" in guard
    assert "moodboard_node_is_mask_detail" in guard


def test_the_card_grip_wedge_is_gone_everywhere():
    for retired in ("MOODBOARD_NODE_RESIZE_GRIP",
                    "moodboard_draw_node_resize_grip",
                    "moodboard_graph_resize_grip_hit"):
        for path in SPACE_MIXIE.glob("*.*"):
            assert retired not in _read(path), f"{path.name} still has {retired}"


def test_the_handle_size_and_its_grab_zone_are_screen_sized():
    """A handle is an affordance, not part of the picture, so it stays equally
    aimable at every zoom -- and the grab zone has to be converted the same
    way, or a zoomed-out card's corners become unclickable."""
    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    assert re.search(r"#define MOODBOARD_RESIZE_HANDLE_PX [0-9.]+f", intern)
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard.cc")
    assert "MOODBOARD_RESIZE_HANDLE_PX / ui::view2d_scale_get_x(v2d)" in draw
    card = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_resize.cc")
    assert "MOODBOARD_HANDLE_TOLERANCE_PX" in card
    assert "view_scale" in card


def test_one_resize_cursor_because_every_handle_is_a_corner():
    """The NS/EW cursors were the only thing that distinguished the edge
    handles; with corners only there is one diagonal resize cursor."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    assert "WM_CURSOR_NS_SCROLL" not in source
    assert "WM_CURSOR_EW_SCROLL" not in source
    assert "WM_CURSOR_NSEW_SCROLL" in source


def test_the_handles_export_qa_targets_off_the_shared_geometry():
    """New custom-drawn UI is unshippable until it exports QA targets, and they
    must read the surface's OWN hit-test geometry rather than duplicate it."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_qa_targets.cc")
    assert '"moodboard_resize_handle"' in source
    assert "moodboard_resize_handle_positions(" in source
    # The corner is the whole difference between the four, so it is named.
    for corner in ("bottom_left", "bottom_right", "top_right", "top_left"):
        assert f'"{corner}"' in source, corner


def test_the_shared_unit_is_in_the_build():
    assert SHARED in _read(SPACE_MIXIE / "CMakeLists.txt")


def test_every_touched_file_stays_under_the_five_hundred_line_rule():
    for unit in (SHARED,
                 "mixie_moodboard_ops_graph_resize.cc",
                 "mixie_draw_moodboard_graph_chrome.cc",
                 "mixie_draw_moodboard.cc"):
        lines = len(_read(SPACE_MIXIE / unit).splitlines())
        assert lines <= 500, f"{unit} is {lines} lines"
