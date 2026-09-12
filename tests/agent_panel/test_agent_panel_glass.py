# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared glass material and status accents on parallel-agent cards."""

import re

from test_agent_panel_contracts import DRAW, ROOT, _fn_body


def _floats(text):
    return [float(v.strip().rstrip("f")) for v in text.split(",") if v.strip()]


def _glass_panel_row():
    """The kit's MIXAR_GLASS_PANEL token row."""
    kit = (
        ROOT
        / "src"
        / "source"
        / "blender"
        / "editors"
        / "interface"
        / "interface_mixar_liquid_glass_tokens.cc"
    ).read_text()
    start = kit.index("/* MIXAR_GLASS_PANEL")
    return kit[start : kit.index("/* MIXAR_GLASS_ISLAND", start)]


class TestTheCardIsLiquidGlass:
    """The card is painted with the shared glass material.

    This is a palette move, not a repaint: the card's own green wash and its
    running border stay at the call site, so the card is still recognisable,
    while the bed, the rim, the gloss and the specular come from the kit. Every
    failure below is invisible at runtime -- a card that quietly keeps its old
    opaque `draw_roundbox_4fv_ex` fill still draws, it just stops being glass,
    and this overlay has no compiler to say otherwise.
    """

    def test_the_card_draws_the_panel_glass_role(self):
        text = DRAW.read_text()
        assert '#include "ED_mixar_glass.hh"' in text
        card = _fn_body(text, "void draw_card(")
        assert "glass_pane(&rect, ui::MIXAR_GLASS_PANEL, radius, alpha);" in card, (
            "the card must route through the kit's PANEL row"
        )

    def test_the_opaque_bed_is_gone(self):
        """`CARD_DARK` was the card's own near-black fill. The kit's tinted
        silhouette replaced it, and a leftover fill would cover every glass
        layer drawn beneath it. The only fill left on the full card rect is the
        running outline, which paints nothing but its own edge."""
        card = _fn_body(DRAW.read_text(), "void draw_card(")
        assert "with_alpha(CARD_DARK" not in card
        assert "/*inner1 (right)*/ dark" not in card
        assert card.count("draw_roundbox_4fv_ex(&rect,") == 1
        assert "draw_roundbox_4fv_ex(&rect, nullptr, nullptr, 1.0f, border" in card

    def test_the_green_wash_survives_with_a_transparent_dark_end(self):
        """The wash is the card's identity and stays at the call site; the kit's
        tint bed is a vertical ramp and could not express it."""
        card = _fn_body(DRAW.read_text(), "void draw_card(")
        assert "with_alpha(CARD_GREEN, alpha * wash, green)" in card
        assert "const float clear[4] = {0.0f, 0.0f, 0.0f, 0.0f};" in card
        assert "ui::draw_roundbox_4fv_ex(&wash_rect," in card

    def test_the_running_border_stays_where_the_status_lives(self):
        """The token row carries the RESTING border; a running agent needs the
        brighter one, and only the call site knows the status."""
        card = _fn_body(DRAW.read_text(), "void draw_card(")
        assert "with_alpha(CARD_BORDER_RUNNING, alpha, border)" in card
        assert "with_alpha(CARD_BORDER," not in card

    def test_the_pane_asks_for_no_shadow_inside_the_clip(self):
        """A shadow is clipped hard at the card column's scissor edge, where it
        reads as a scratched line across the viewport."""
        pane = _fn_body(DRAW.read_text(), "void glass_pane(")
        assert "style.draw_shadow" not in pane
        assert "style.alpha = alpha;" in pane
        assert "BLI_rcti_rctf_copy(&pane, rect);" in pane

    def test_the_tokens_bed_is_the_cards_own_near_black(self):
        """Cross-file pin: the pane's bed is the card's own dark, not the
        neutral grey the other dark surfaces use, or the panel stops matching
        the island it floats over."""
        dark = re.search(
            r"constexpr float CARD_DARK\[4\] = \{([^}]*)\}", DRAW.read_text()
        )
        row = _glass_panel_row()
        tint = re.search(r"/\* tint_bottom\s+\*/\s*\{([^}]*)\}", row)
        assert _floats(tint.group(1))[:3] == _floats(dark.group(1))[:3]

    def test_the_token_row_carries_the_cards_resting_border(self):
        """Cross-file pin: the rim the card used to draw must be the rim the
        kit's PANEL row draws, or a resting card silently changes colour."""
        border = re.search(
            r"constexpr float CARD_BORDER\[4\] = \{([^}]*)\}", DRAW.read_text()
        )
        rim = re.search(r"/\* rim\s+\*/\s*\{([^}]*)\}", _glass_panel_row())
        rim_vals = _floats(rim.group(1))
        assert rim_vals[:3] == _floats(border.group(1))[:3]
        assert rim_vals[3] == 0.55


