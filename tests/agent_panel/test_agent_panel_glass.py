# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared glass material on parallel-agent cards."""

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
    """Progress belongs inside the glass mask, beneath the text and controls."""

    def test_the_card_draws_the_panel_glass_role(self):
        text = DRAW.read_text()
        assert '#include "ED_mixar_glass.hh"' in text
        card = _fn_body(text, "void draw_card(")
        assert re.search(r"glass_pane\(&rect,\s*ui::MIXAR_GLASS_PANEL,", card), (
            "the card must route through the kit's PANEL row"
        )

    def test_the_opaque_bed_and_status_strokes_are_gone(self):
        """`CARD_DARK`, the green wash and the running outline all covered the
        pane. The card rect is now one glass call."""
        card = _fn_body(DRAW.read_text(), "void draw_card(")
        assert "CARD_DARK" not in card
        assert "CARD_GREEN" not in card
        assert "CARD_BORDER" not in card
        assert "draw_roundbox_4fv_ex" not in card

    def test_the_chevron_is_the_same_pane(self):
        chevron = _fn_body(DRAW.read_text(), "void draw_chevron(")
        assert "glass_pane(&rect, ui::MIXAR_GLASS_PANEL," in chevron
        assert "CARD_BORDER" not in chevron
        assert "draw_roundbox_4fv_ex" not in chevron

    def test_the_pane_asks_for_no_shadow_inside_the_clip(self):
        """A shadow is clipped hard at the card column's scissor edge, where it
        reads as a scratched line across the viewport."""
        pane = _fn_body(DRAW.read_text(), "void glass_pane(")
        assert "style.draw_shadow" not in pane
        assert "style.alpha = alpha;" in pane
        assert "BLI_rcti_rctf_copy(&pane, rect);" in pane

    def test_the_tokens_bed_is_near_black_not_green(self):
        """The pane's bed is a quiet dark, not a brand-green tint."""
        row = _glass_panel_row()
        tint = re.search(r"/\* tint_bottom\s+\*/\s*\{([^}]*)\}", row)
        rgb = _floats(tint.group(1))[:3]
        assert max(rgb) < 0.08
        assert abs(rgb[0] - rgb[1]) < 0.01
        assert abs(rgb[1] - rgb[2]) < 0.01

    def test_the_token_row_carries_a_neutral_glass_rim(self):
        """Equal RGB is a white/grey stroke; a green channel lead is the old
        resting border coming back through the table."""
        rim = re.search(r"/\* rim\s+\*/\s*\{([^}]*)\}", _glass_panel_row())
        rim_vals = _floats(rim.group(1))
        assert rim_vals[0] == rim_vals[1] == rim_vals[2]
        assert rim_vals[3] > 0.0

    def test_panel_fallback_keeps_the_viewport_visible(self):
        row = _glass_panel_row()
        floor = re.search(r"/\* fallback_alpha \*/\s*([\d.]+)f", row)
        assert 0.3 <= float(floor.group(1)) <= 0.6

