# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The surface-wide rules a UI audit found broken one file at a time.

Every one of these was a per-painter decision that drifted: a label centred
on its own ink box, a card inset chosen by whoever wrote the card, a hit box
truncated into its own paint, a string drawn without ever being measured.
They are rules, so they are checked across every painter at once.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
SURFACE = sorted(VIEW3D.glob("view3d_director_cinema*.cc"))
TEXT = (VIEW3D / "view3d_director_cinema_text.cc").read_text(encoding="utf-8")
PAINT = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
LAYOUT = (VIEW3D / "view3d_director_cinema_layout.cc").read_text(encoding="utf-8")
TOKENS = (VIEW3D / "view3d_director_cinema_tokens.hh").read_text(encoding="utf-8")


def test_a_baseline_centres_the_cap_band():
    """Two wrong answers came before this one.

    The string's own ink box made the baseline depend on which glyphs it
    happened to contain, so "My Cameras" and "Depth of Field" sat one to two
    pixels apart on the same row. `BLF_ascender` is uniform but far taller
    than the capitals — it carries the accent and line-gap space above them —
    so it hung every label low: measured at 5.5 px below centre on a 72 px
    row, which reads as text resting on the pill's bottom edge.
    """
    body = TEXT[TEXT.index("float baseline_for(") :]
    body = body[: body.index("\n}\n")]
    assert "cap_height(font, size)" in body
    assert "BLF_ascender(" not in TEXT

    cap = TEXT[TEXT.index("float cap_height(") :]
    cap = cap[: cap.index("\n}\n")]
    # ONE glyph, always the same one, so the answer cannot vary with the text.
    assert 'BLF_boundbox(font, "H", 1, &box);' in cap
    assert "float(box.ymax)" in cap


def test_the_surface_has_exactly_one_text_painter():
    """A second one drifts: the compact rail's took a BASELINE where every
    other call passes a centre line, and measured nothing."""
    for path in SURFACE + [VIEW3D / "view3d_director_overlay.cc"]:
        source = path.read_text(encoding="utf-8")
        if path.name == "view3d_director_cinema_text.cc":
            continue
        assert "BLF_draw(" not in source, path.name
        assert "BLF_position(" not in source, path.name


def test_clipping_is_left_in_a_known_state():
    """It is a SHARED font state with no getter. Switching it off and walking
    away leaves the next widget's own clip rect unset."""
    body = TEXT[TEXT.index("void draw_text(") :]
    body = body[: body.index("\n}\n")]
    assert body.count("BLF_disable(font, BLF_CLIPPING);") == 2
    assert "BLF_clipping(font," in body
    assert "BLF_enable(font, BLF_CLIPPING);" in body


def test_hit_boxes_contain_their_paint():
    """Paint is float and a uiBut's box is int; truncating both corners lost
    up to a pixel on each edge of every control — a whole control when the
    control is a 3 px scroll track."""
    body = PAINT[PAINT.index("rcti hit_box(") :]
    body = body[: body.index("\n}\n")]
    assert "std::floor(rect.xmin)" in body and "std::ceil(rect.xmax)" in body
    for name in ("cinema_op_button", "cinema_icon_button", "cinema_popup_button",
                 "cinema_blocker"):
        definition = PAINT[PAINT.index(f"ui::Button *{name}(") :]
        definition = definition[: definition.index("\n}\n")]
        assert "hit_box(rect)" in definition, name
        assert "int(rect.xmin)" not in definition, name


def test_one_inset_per_card_and_it_is_the_same_one():
    """13 for the dropdown rows, 16 for the speed meter, 11 for a camera row
    against a 13 caption — nothing in a card lined up with anything else."""
    assert "#define CINEMA_CARD_PAD" in TOKENS
    assert "#define CINEMA_ROW_W (CINEMA_PANEL_W - CINEMA_CARD_PAD * 2.0f)" in TOKENS
    for name in ("view3d_director_cinema_left.cc", "view3d_director_cinema_cameras.cc"):
        source = (VIEW3D / name).read_text(encoding="utf-8")
        assert "CINEMA_CARD_PAD" in source, name
        assert "LABEL_INSET" not in source, name
        assert "ROW_INSET" not in source, name


def test_every_user_typed_string_is_measured():
    """The surface paints into fixed cards. A camera name and a focus
    object's name are the two strings a user types themselves, and both used
    to run out of their row and off the card."""
    cameras = (VIEW3D / "view3d_director_cinema_cameras.cc").read_text(encoding="utf-8")
    left = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
    assert "cinema_text_left_fitted(name," in cameras
    assert "cinema_text_left_fitted(value," in left


def test_a_query_does_not_rewrite_the_scale():
    """`cinema_stage_rect` and `cinema_columns_contain` are asked from polls
    and event handlers; leaving `g_unit` rewritten is a read with a side
    effect on whatever painter runs next."""
    assert "struct ScopedUnit {" in LAYOUT
    for name in ("bool cinema_stage_rect(", "bool cinema_columns_contain("):
        body = LAYOUT[LAYOUT.index(name) :]
        body = body[: body.index("\n}\n")]
        assert "const ScopedUnit unit_scope(region);" in body, name
        assert "cinema_unit_begin(region);" not in body, name


def test_per_region_statics_are_all_released():
    """Each is keyed on a raw `ARegion *`; a record that outlives its region
    answers for whatever is allocated at that address next."""
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    for release in ("view3d_director_minimap_release(region",
                    "cinema_camera_list_release(region)",
                    "cinema_gate_release(region)"):
        assert release in overlay, release


def test_the_dead_tokens_of_the_removed_gate_frame_are_gone():
    for token in ("CINEMA_COL_GATE_FILL", "CINEMA_COL_GATE_LINE", "CINEMA_PHONE_W"):
        assert token not in TOKENS, token
        for path in SURFACE:
            assert token not in path.read_text(encoding="utf-8"), f"{token} in {path.name}"


def test_font_sizes_come_from_tokens():
    """The Export button carried a bare 14.0f where every other size is a
    named step."""
    right = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
    assert "#define CINEMA_FONT_ACTION" in TOKENS
    assert "CINEMA_FONT_ACTION * u" in right
    assert "14.0f * u" not in right


def test_the_three_greys_have_a_written_rule():
    """They were picked per painter, so the same kind of text came out three
    shades depending on which file drew it."""
    rule = TOKENS[TOKENS.index("/* THREE greys") :]
    rule = rule[: rule.index("*/")]
    for token in ("LABEL", "CAPTION", "DIM"):
        assert token in rule, token
