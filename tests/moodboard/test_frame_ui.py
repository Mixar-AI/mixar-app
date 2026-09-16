# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas frames: the drawing, the selection model and the wiring.

The frame box, its name and its hit-test are C++ canvas content, so these are
source-level pins on the contracts that would otherwise drift silently:

* the palette is duplicated across two languages and must agree;
* frames must paint UNDER every other canvas pass (a wash over a card tints
  the result the user is looking at);
* the keymap ORDER is the selection model -- frames ahead of cards ahead of
  media, each passing through what is not theirs;
* the legacy index-based grouping must not come back.
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The palette is duplicated across languages
# --------------------------------------------------------------------------- #


def test_the_cpp_palette_matches_the_python_one():
    """The painter owns its own copy of FRAME_PALETTE (C++ cannot read a Python
    constant) and the colour menu names the pastels from the Python one. A
    drift would label one pastel and paint another."""
    from mixar.modules.moodboard.constants import FRAME_PALETTE

    source = _read(SPACE_MIXIE / "mixie_moodboard_frame_geometry.cc")
    block = source.split("static const float FRAME_PALETTE")[1].split("};")[0]
    triples = re.findall(
        r"\{\s*([0-9.]+)f,\s*([0-9.]+)f,\s*([0-9.]+)f\s*\}", block
    )
    assert len(triples) == len(FRAME_PALETTE)
    for (name, rgb), painted in zip(FRAME_PALETTE, triples):
        assert tuple(round(float(v), 4) for v in painted) == tuple(
            round(float(v), 4) for v in rgb
        ), f"{name} differs between constants.py and the painter"

    assert f"#define MOODBOARD_FRAME_PALETTE_SIZE {len(FRAME_PALETTE)}" in source


def test_the_size_floors_agree_across_languages():
    """The C++ hit-test and the Python geometry must not disagree about how
    small a frame may get, or the grow pass would produce a rect the other side
    reads as a different size."""
    from mixar.modules.moodboard.constants import FRAME_MIN_HEIGHT, FRAME_MIN_WIDTH

    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    assert f"#define MOODBOARD_FRAME_MIN_W {FRAME_MIN_WIDTH}f" in intern
    assert f"#define MOODBOARD_FRAME_MIN_H {FRAME_MIN_HEIGHT}f" in intern


def test_the_name_buffer_is_larger_than_the_declared_maxlen():
    """The GRAPH_*_MAXLEN <-> MIXIE_*_BUF rule: `maxlen` is only enforced on
    ASSIGNMENT, so a .blend written before the limit can carry a longer value
    that reaches the draw -- the buffer must have room and the read must
    clamp."""
    from mixar.modules.moodboard.constants import FRAME_NAME_MAXLEN

    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    match = re.search(r"#define MIXIE_FRAME_NAME_BUF (\d+)", intern)
    assert match, "MIXIE_FRAME_NAME_BUF missing"
    assert int(match.group(1)) > FRAME_NAME_MAXLEN

    frames = _read(SPACE_MIXIE / "mixie_draw_moodboard_frames.cc")
    assert "mixie_rna_string_get_clamped(&iter.ptr, \"name\"" in frames


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def test_frames_paint_before_every_other_canvas_pass():
    """A frame is a translucent wash over a region of the board. Painted after
    the media and the cards -- which is where the old group pass sat -- it
    would tint the very results the user is looking at."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard.cc")
    body = draw.split("void mixie_draw_moodboard_mode(")[1]
    frames_at = body.index("mixie_draw_moodboard_frames(C, v2d)")
    for later in (
        "mixie_draw_moodboard_links(",
        "mixie_draw_moodboard_images(",
        "mixie_draw_moodboard_graph_nodes(",
        "mixie_draw_moodboard_textboxes(",
    ):
        assert frames_at < body.index(later), f"frames must precede {later}"


def test_the_top_border_is_thicker_than_the_rest():
    """It is the frame's drag handle and primary click target, so it has to be
    aimable -- the same job a node card's header strip does."""
    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    border = float(re.search(r"#define MOODBOARD_FRAME_BORDER ([0-9.]+)f", intern).group(1))
    top = float(
        re.search(r"#define MOODBOARD_FRAME_TOP_BORDER ([0-9.]+)f", intern).group(1)
    )
    assert top > border
    # And both are thick enough to see and to aim at. A hairline border read as
    # a faint artifact rather than as the edge of an object, and a title strip
    # only a few canvas units tall is a sliver to grab a frame by.
    assert border >= 6.0
    assert top >= 20.0


def test_a_click_on_a_frames_interior_selects_the_frame():
    """Selecting only from the title strip read as arbitrary -- the rect is
    visibly one object. But the PRESS still has to pass through (it is also how
    a member is grabbed and how a marquee inside a frame starts), so the click
    is resolved from the one branch that knows the gesture ended as a click
    rather than a drag: box select's tiny-box case."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_frame_geometry.cc")
    assert "bool moodboard_frame_select_at_point(" in geometry
    # It reuses the ONE hit-test, so clicking and dragging can never disagree
    # about which frame the pointer is over.
    select_at = geometry.split("bool moodboard_frame_select_at_point(")[1]
    assert "moodboard_find_frame_at(" in select_at

    box = _read(SPACE_MIXIE / "mixie_moodboard_ops_box_select.cc")
    click = box.split("if (box_width <= CLICK_THRESHOLD")[1].split("\n  }")[0]
    # Deselect first, then let the frame under the cursor claim the click.
    assert click.index("moodboard_deselect_all") < click.index(
        "moodboard_frame_select_at_point"
    )


def test_moving_a_frame_is_still_only_possible_from_its_chrome():
    """The click/drag split is the whole point: a frame is clickable everywhere
    and movable by its edge. If the select operator ever claimed the interior
    it would install a modal there and take the press away from a member's own
    drag and from the marquee."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_frame_select.cc")
    invoke = source.split("static wmOperatorStatus frame_select_invoke(")[1]
    guard = invoke.split("return OPERATOR_PASS_THROUGH;")[0]
    assert "MOODBOARD_FRAME_PART_INTERIOR" in guard
    # And the click-time helper is NOT reached from here, or the pass-through
    # above would be unreachable in practice.
    assert "moodboard_frame_select_at_point" not in source


def test_the_two_fill_states_differ_in_alpha_not_saturation():
    """The canvas is pure black, so a pastel at low alpha reads as a faint
    coloured haze (the intent) while desaturating toward white -- the instinct
    from a white canvas -- turns it grey and costs the frame its identity."""
    intern = _read(SPACE_MIXIE / "mixie_intern.hh")
    fill = float(
        re.search(r"#define MOODBOARD_FRAME_FILL_ALPHA ([0-9.]+)f", intern).group(1)
    )
    fill_sel = float(
        re.search(
            r"#define MOODBOARD_FRAME_FILL_ALPHA_SELECTED ([0-9.]+)f", intern
        ).group(1)
    )
    border = float(
        re.search(r"#define MOODBOARD_FRAME_BORDER_ALPHA ([0-9.]+)f", intern).group(1)
    )
    # A wash, not a fill: it must never obscure what is inside the frame.
    assert 0.0 < fill < 0.2
    assert fill < fill_sel < 0.25
    # The border is the same pastel, just far more opaque.
    assert border > fill_sel

    frames = _read(SPACE_MIXIE / "mixie_draw_moodboard_frames.cc")
    body = frames.split("static void draw_frame_box(")[1].split("\n}")[0]
    # One colour feeds both, so saturation cannot differ between the states.
    assert body.count("color[0]") == 2 and body.count("color[2]") == 2


def test_the_name_is_drawn_for_every_frame_not_just_a_selected_one():
    """A rect cannot say WHICH frame it is, and a board of same-shaped
    rectangles is exactly where a name earns its keep. The old group drawing
    painted nothing at all unless something inside it was selected."""
    frames = _read(SPACE_MIXIE / "mixie_draw_moodboard_frames.cc")
    labels = frames.split("void mixie_draw_moodboard_frame_labels(")[1]
    # `selected` is read only to pick the text alpha and to reserve the action
    # row's width -- never to decide whether to draw at all.
    for skip in re.findall(r"if \(([^)]*selected[^)]*)\)[^\n]*\n[^\n]*continue", labels):
        raise AssertionError(f"name draw gated on selection: {skip}")


def test_the_name_is_sized_with_the_canvas_then_fitted():
    """The media-label rules, reused: clamp the zoom-derived size, THEN fit it
    to the width available, then drop the name if the fit forced it back under
    the floor. Clamping after the fit would let a name come back wider than
    the frame it labels."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_frames.cc").split(
        "void mixie_draw_moodboard_frame_labels("
    )[1]
    clamp_at = labels.index("std::clamp(MOODBOARD_FRAME_LABEL_SIZE_PX")
    fit_at = labels.index("font_px *= frame_width / text_width")
    drop_at = labels.index("if (font_px < MOODBOARD_FRAME_LABEL_MIN_PX")
    assert clamp_at < fit_at < drop_at
    assert "UI_SCALE_FAC" in labels and "view_scale" in labels


def test_a_long_name_folds_in_the_middle_over_utf8_offsets():
    """What tells two frames apart is as often their tail as their head -- and
    a raw byte cut would slice a multi-byte character into a replacement
    glyph."""
    frames = _read(SPACE_MIXIE / "mixie_draw_moodboard_frames.cc")
    fold = frames.split("static void frame_label_text(")[1].split("\n}")[0]
    assert "BLI_str_utf8_offset_from_index" in fold
    assert "BLI_strlen_utf8_ex" in fold
    assert '"%s...%s"' in fold


# --------------------------------------------------------------------------- #
# The selection model
# --------------------------------------------------------------------------- #


def test_the_keymap_order_is_frames_then_cards_then_media():
    """The order IS the model: frames get first refusal but claim only their
    own chrome, so a press on a frame's interior passes through and a member
    takes the click."""
    keymap = _read(SPACE_MIXIE / "space_mixie.cc")
    block = keymap.split("/* Select and move images in moodboard */")[1]
    frame_at = block.index('"MIXIE_OT_moodboard_frame_select", &params)')
    graph_at = block.index('"MIXIE_OT_moodboard_graph_select", &params)')
    media_at = block.index('"MIXIE_OT_moodboard_select_image", &params)')
    assert frame_at < graph_at < media_at


def test_the_frame_operator_passes_through_the_interior():
    """Press-drag inside a frame is a marquee and a press on a member selects
    the member. Claiming the interior would make the frame swallow both."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_frame_select.cc")
    invoke = source.split("static wmOperatorStatus frame_select_invoke(")[1]
    guard = invoke.split("return OPERATOR_PASS_THROUGH;")[0]
    assert "MOODBOARD_FRAME_PART_INTERIOR" in guard
    assert "MOODBOARD_FRAME_PART_NONE" in guard


def test_extend_is_skip_save_on_the_frame_operator():
    """A REGISTER operator refills unset properties from the previous run, and
    the plain-click keymap item sets nothing -- so without the flag ONE
    Shift-click would make every later press take the toggle branch, which
    returns FINISHED and installs no modal: frames could not be dragged."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_frame_select.cc")
    tail = source.split("void MIXIE_OT_moodboard_frame_select(")[1]
    assert '"extend"' in tail
    assert "RNA_def_property_flag(prop, PROP_SKIP_SAVE)" in tail


def test_clicking_a_member_selects_the_member():
    """The old model was inverted: a plain click on a grouped image selected
    the GROUP, reaching the image needed a double-click, and Shift+click on it
    did nothing. The media selection context must not read frame membership at
    all."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    ctx = source.split("static MoodboardSelectionContext get_selection_context(")[1]
    ctx = ctx.split("\n}")[0]
    assert "frame_id" not in ctx
    assert "group_index" not in ctx

    dispatch = source.split("static void update_moodboard_selection(")[1].split("\n}")[0]
    # Extend toggles unconditionally now -- no membership branch in front of
    # it, and none of the group-promotion handlers survives anywhere.
    assert "handle_extend_click(ctx)" in dispatch
    for retired in (
        "handle_click_select_group",
        "handle_double_click_grouped_image",
        "handle_extend_click_ungrouped",
        "is_group_selected",
        "MOODBOARD_ELEMENT_GROUP",
    ):
        assert retired not in source, retired


def test_a_frame_move_never_re_resolves_membership():
    """A frame sweeping over the board must not swallow what it passed over;
    its own members came with it and keep their membership. Moving an ITEM is
    the membership change."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_frame_select.cc")
    move = source.split("static wmOperatorStatus frame_move_modal(")[1].split(
        "static wmOperatorStatus frame_select_modal("
    )[0]
    assert "moodboard_frames_request_reframe" not in move


def test_a_frame_cannot_be_hand_resized():
    """A frame's rect follows what it holds -- it grows to keep a member
    dragged outwards, and Fit to Contents wraps it back to them. A drag-to-
    resize grip was a second, competing way to say where its edges go, and it
    fought that automatic grow on every drag."""
    for unit in (
        "mixie_moodboard_ops_frame_select.cc",
        "mixie_moodboard_frame_geometry.cc",
        "mixie_draw_moodboard_frames.cc",
        "mixie_intern.hh",
    ):
        source = _read(SPACE_MIXIE / unit)
        for retired in (
            "MOODBOARD_FRAME_PART_GRIP",
            "MOODBOARD_FRAME_RESIZE_GRIP",
            "moodboard_frame_grip_rect",
            "frame_resize_modal",
        ):
            assert retired not in source, f"{unit} still references {retired}"


def test_every_drag_end_reframes_through_the_one_python_rule():
    """Membership has exactly one definition (`core/frames.resolve_membership`)
    and all three drag ends must apply the same one."""
    common = _read(SPACE_MIXIE / "mixie_moodboard_ops_common.hh")
    assert "void moodboard_frames_request_reframe(bContext *C);" in common
    frame_ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_frame_select.cc")
    assert 'WM_operatortype_find("MIXIE_OT_moodboard_reframe", true)' in frame_ops
    for unit in ("mixie_moodboard_ops_select.cc", "mixie_moodboard_ops_graph.cc"):
        assert "moodboard_frames_request_reframe(C)" in _read(SPACE_MIXIE / unit), unit


def test_a_marquee_selects_a_frame_only_when_it_contains_it_whole():
    """A box drawn inside a frame to pick a few of its pictures overlaps the
    frame by definition; selecting it too would put a frame in the selection
    the user never aimed at -- and a selected frame carries every member, so
    the next drag would move the whole set."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_ops_box_select.cc")
    fn = source.split("static bool select_frames_in_box(")[1].split("\n}")[0]
    assert "rect.xmin >= box_min_x" in fn and "rect.xmax <= box_max_x" in fn
    # And frames are NOT in the plain intersection loop.
    loop = source.split("for (const char *collection_name :")[1].split(")")[0]
    assert "frames" not in loop


def test_deselect_all_clears_frames():
    """A frame left selected behind a click on a picture would move a whole
    set the user did not grab."""
    source = _read(SPACE_MIXIE / "mixie_select.cc")
    fn = source.split("void moodboard_deselect_all(")[1]
    assert '"mixie_moodboard_frames"' in fn


def test_a_locked_frame_is_transparent_to_the_pointer():
    """That is the whole meaning of the lock: leave the frame alone, reach its
    members."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_frame_geometry.cc")
    finder = geometry.split("int moodboard_find_frame_at(")[1]
    assert '"locked"' in finder
    assert "continue" in finder.split('"locked"')[1][:400]


# --------------------------------------------------------------------------- #
# Geometry has one owner
# --------------------------------------------------------------------------- #


def test_draw_actions_and_hit_test_share_one_geometry_definition():
    """Otherwise the pixels the user aims at and the region that responds drift
    apart at some zoom -- the same rule the socket radii and the card grip
    already follow."""
    for unit, wanted in (
        ("mixie_draw_moodboard_frames.cc", ("moodboard_frame_top_strip",)),
        ("mixie_draw_moodboard_frame_actions.cc", ("moodboard_frame_rect",)),
        ("mixie_moodboard_ops_frame_select.cc", ("moodboard_find_frame_at",)),
        ("mixie_moodboard_qa_targets.cc", ("moodboard_frame_top_strip",)),
        ("mixie_moodboard_ops_zoom.cc", ("moodboard_frame_rect",)),
    ):
        source = _read(SPACE_MIXIE / unit)
        for symbol in wanted:
            assert symbol in source, f"{unit} does not use {symbol}"


def test_new_frame_units_are_in_the_build():
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")
    for unit in (
        "mixie_draw_moodboard_frames.cc",
        "mixie_draw_moodboard_frame_actions.cc",
        "mixie_moodboard_frame_geometry.cc",
        "mixie_moodboard_ops_frame_select.cc",
        "mixie_moodboard_ops_rename_frame.cc",
    ):
        assert unit in cmake, unit
    # And the retired group pass is gone.
    assert "mixie_draw_moodboard_groups.cc" not in cmake
    assert not (SPACE_MIXIE / "mixie_draw_moodboard_groups.cc").exists()


def test_the_frame_exports_qa_targets_for_each_clickable_part():
    """New custom-drawn UI is unshippable without them, and each part means
    something different: the body, and the title strip that selects, drags and
    renames. There is no resize target -- a frame has no manual resize."""
    source = _read(SPACE_MIXIE / "mixie_moodboard_qa_targets.cc")
    for surface in ("moodboard_frame", "moodboard_frame_title"):
        assert f'"{surface}"' in source, surface
    assert "moodboard_frame_grip" not in source


def test_every_file_stays_under_the_five_hundred_line_rule():
    for unit in (
        "mixie_draw_moodboard_frames.cc",
        "mixie_draw_moodboard_frame_actions.cc",
        "mixie_moodboard_frame_geometry.cc",
        "mixie_moodboard_ops_frame_select.cc",
        "mixie_moodboard_ops_rename_frame.cc",
    ):
        lines = len(_read(SPACE_MIXIE / unit).splitlines())
        assert lines <= 500, f"{unit} is {lines} lines"
    for unit in ("core/frames.py", "core/frame_geometry.py",
                 "ui/operators/frame_ops.py", "ui/moodboard_frame_menus.py",
                 "ui/moodboard_frame_props.py"):
        lines = len(_read(MOODBOARD / unit).splitlines())
        assert lines <= 500, f"{unit} is {lines} lines"
