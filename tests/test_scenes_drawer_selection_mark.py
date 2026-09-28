# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch-selected scene cards must carry loud cues, not a thin dark outline.

The Scenes drawer once marked a selected card with a one-pixel outline in the
dark primary green, which was invisible on the dark glass card: with two
scenes selected only the active row (whose wash is a different signal) looked
selected. The painter now draws a tint, a light two-pixel outline and a check
badge in place of the drag grip. These checks pin that contract at source
level because the painter needs a GPU context.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "src/source/blender/editors/space_view3d"
DRAW = (SPACE / "view3d_scenes_drawer_draw.cc").read_text()
WIDGETS = (SPACE / "view3d_scenes_drawer_draw_widgets.cc").read_text()


def _body(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


def test_selected_card_uses_the_selection_mark_not_a_primary_outline():
    assert "draw_selection_mark(rect, scale)" in DRAW
    assert "draw_roundbox_4fv(&rect, false, CARD_RADIUS * scale, zen.primary)" not in DRAW


def test_selection_mark_draws_tint_light_outline_and_check_badge():
    body = _body(WIDGETS, "void draw_selection_mark(const rctf &card, const float scale)")
    assert "with_alpha(zen.primary" in body, "translucent primary tint over the card"
    assert "with_alpha(zen.focus" in body, "outline must be the light focus green"
    assert body.count("draw_roundbox_4fv(&") >= 3, "fill plus a two-pass (2px) outline"
    assert "ICON_CHECKMARK" in body, "a check badge marks membership"
    assert "draw_pill(badge" in body


def test_selected_card_hides_the_grip_behind_the_badge():
    assert "col < (selected ? 0 : 2)" in DRAW
