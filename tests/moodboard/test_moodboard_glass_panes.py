# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The moodboard's pans are liquid glass, and they are ONE material.

The bed, the rim and the gloss live in the shared token table; the three call
sites (the media frame, the graph node card, the floating node toolbar) only
say which rect and radius to paint, plus the ACTIVE accent a node's state
implies. Pinned at source level because the failure is invisible at runtime:
these panes are an opaque fill today, so a missed conversion simply keeps a
rectangle that is slightly the wrong dark, and nothing errors.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
ED = ROOT / "src/source/blender/editors"
INTERN = SPACE_MIXIE / "mixie_draw_moodboard_intern.hh"
MEDIA = SPACE_MIXIE / "mixie_draw_moodboard.cc"
GRAPH = SPACE_MIXIE / "mixie_draw_moodboard_graph.cc"
NODE_UI = SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc"
KIT = ED / "interface" / "interface_mixar_liquid_glass_tokens.cc"
GLASS_HEADER = ED / "include" / "ED_mixar_glass.hh"

INTERN_TEXT = INTERN.read_text(encoding="utf-8")
MEDIA_TEXT = MEDIA.read_text(encoding="utf-8")
GRAPH_TEXT = GRAPH.read_text(encoding="utf-8")
NODE_UI_TEXT = NODE_UI.read_text(encoding="utf-8")
KIT_TEXT = KIT.read_text(encoding="utf-8")
HEADER_TEXT = GLASS_HEADER.read_text(encoding="utf-8")


def _floats(text: str) -> list[float]:
    return [float(v.strip().rstrip("f")) for v in text.split(",") if v.strip()]


def _fn(text: str, signature: str) -> str:
    """`signature`'s body, up to the next top-level closing brace."""
    start = text.index(signature)
    end = text.index("\n}\n", start)
    return text[start : end + 2]


def _moodboard_row() -> str:
    start = KIT_TEXT.index("/* MIXAR_GLASS_MOODBOARD")
    return KIT_TEXT[start : KIT_TEXT.index("static_assert", start)]


def test_the_enum_grew_at_the_end_so_existing_roles_keep_their_value():
    """A role inserted in the middle silently re-tones every later surface."""
    enum_body = HEADER_TEXT[
        HEADER_TEXT.index("enum eMixarGlassRole {") : HEADER_TEXT.index(
            "};", HEADER_TEXT.index("enum")
        )
    ]
    names = re.findall(r"^\s*MIXAR_GLASS_([A-Z]+),", enum_body, re.M)
    assert names[-2:] == ["CHIP", "MOODBOARD"], (
        "the moodboard role must be appended after CHIP: the enum is indexed "
        f"into the token table and persisted nowhere, but a mid-insertion "
        f"silently re-tones every later row. Got {names}."
    )


def test_the_three_panes_share_one_glass_helper():
    """One helper, so the frame, the card and the toolbar are one material."""
    assert "void moodboard_draw_glass_pane(const rctf &rect, float radius);" in INTERN_TEXT, (
        "the shared glass helper must be declared in the intern header, where "
        "the graph and node-UI files can reach it"
    )
    assert "void moodboard_draw_glass_pane(const rctf &rect, const float radius)" in MEDIA_TEXT
    assert "moodboard_draw_glass_pane(" in GRAPH_TEXT
    assert "moodboard_draw_glass_pane(" in NODE_UI_TEXT
    assert '#include "ED_mixar_glass.hh"' in MEDIA_TEXT, (
        "the definition calls ui::mixar_glass_draw; without the include the "
        "overlay fails to compile (and the kit is the only declaration site)"
    )


def test_the_helper_paints_the_moodboard_role():
    body = _fn(MEDIA_TEXT, "void moodboard_draw_glass_pane(")
    assert "BLI_rcti_rctf_copy(&pane, &rect);" in body
    assert "style.role = ui::MIXAR_GLASS_MOODBOARD;" in body
    assert "style.radius = radius;" in body
    assert "ui::mixar_glass_draw(pane, style);" in body
    assert "draw_shadow" not in body, (
        "these panes sit on a grid and inside the node clip; a drop shadow "
        "would be clipped at the column edge into a scratched line"
    )


def test_the_media_frame_bed_is_gone():
    body = _fn(MEDIA_TEXT, "void mixie_draw_moodboard_media_frame(")
    assert "moodboard_draw_glass_pane(frame, MOODBOARD_MEDIA_FRAME_RADIUS);" in body
    assert "draw_roundbox_4fv(&frame, true," not in body, "the opaque bed survived"
    assert "0.105f, 0.105f, 0.11f" not in body, "the hand-mixed bed colour survived"


def test_the_media_frame_keeps_the_selected_rim_at_the_call_site():
    body = _fn(MEDIA_TEXT, "void mixie_draw_moodboard_media_frame(")
    assert "if (selected) {" in body
    selected = body.split("if (selected) {")[1]
    assert "const float border[4] = {0.38f, 0.39f, 0.42f, 0.92f};" in selected
    assert "draw_roundbox_4fv(&frame, false, MOODBOARD_MEDIA_FRAME_RADIUS, border);" in selected
    assert "0.58f" not in body, (
        "the RESTING rim belongs to the token row now; a second literal here "
        "is how the media frame and the node card drift apart again"
    )


def test_the_node_card_bed_is_gone():
    body = _fn(GRAPH_TEXT, "static void draw_card_background(")
    assert "moodboard_draw_glass_pane(rect, 22.0f);" in body
    assert "draw_roundbox_4fv(&rect, true," not in body, "the opaque bed survived"
    assert "0.105f, 0.105f, 0.11f" not in body, "the hand-mixed bed colour survived"


def test_the_node_card_keeps_the_selected_rim_at_the_call_site():
    body = _fn(GRAPH_TEXT, "static void draw_card_background(")
    assert "if (selected) {" in body
    selected = body.split("if (selected) {")[1]
    assert "const float border[4] = {0.38f, 0.39f, 0.42f, 0.92f};" in selected
    assert "draw_roundbox_4fv(&rect, false, 22.0f, border);" in selected


def test_the_running_glow_stays_a_call_site_accent():
    """Only the call site knows a node is QUEUED/RUNNING: the token row's rim is
    the resting one, and the breathing green border is painted on top of it."""
    glow = _fn(GRAPH_TEXT, "static void draw_running_glow(")
    assert "{0.32f, 0.72f, 0.55f}" in glow
    assert "0.24f + 0.30f * pulse" in glow, "the breathing border was flattened"
    assert "0.05f + 0.10f * pulse" in glow, "the outset halo was flattened"


def test_the_floating_toolbar_bed_is_gone():
    body = _fn(NODE_UI_TEXT, "void moodboard_draw_floating_background(")
    assert "moodboard_draw_glass_pane(rect, 16.0f);" in body
    assert "draw_roundbox_4fv(&rect, true," not in body, "the opaque bed survived"
    assert "0.14f, 0.14f, 0.15f" not in body, "the hand-mixed bed colour survived"
    assert "0.34f, 0.35f, 0.38f" not in body, "the hand-mixed border survived"


def test_the_token_row_is_the_resting_rim_the_call_sites_brighten():
    """The row's rim RGB must equal the call sites' selected border RGB: the
    two represent one border, resting and active, and a drift here is the
    exact class of mistake the shared row exists to prevent."""
    row = _moodboard_row()
    rim = re.search(r"/\*\s*rim\s*\*/\s*\{([^}]*)\}", row)
    assert rim, "the moodboard row lost its rim"
    rim_values = _floats(rim.group(1))
    assert rim_values[:3] == [0.38, 0.39, 0.42], (
        f"the moodboard token rim is {rim_values[:3]}; the call sites brighten "
        f"0.38/0.39/0.42 to 0.92, so the resting rim must be the same hue"
    )
    assert rim_values[3] == 0.58, (
        f"the room tempering was {rim_values[3]}; the resting rim drew at 0.58 "
        f"before the conversion and must stay there"
    )


def test_the_token_row_asks_for_no_specular():
    """The streak's clip is placed with a region-px scissor, and the moodboard
    cards draw through the View2D matrix: the clip cannot be placed, so the
    row must not claim a streak the painter would clip in the wrong space."""
    row = _moodboard_row()
    for field in ("specular_width", "specular_alpha", "specular_period"):
        match = re.search(rf"/\*\s*{field}\s*\*/\s*([0-9.]+f)", row)
        assert match, f"the moodboard row lost {field}"
        assert float(match.group(1).rstrip("f")) == 0.0, (
            f"{field} is {match.group(1)}: the moodboard cannot place the "
            f"streak's region-px scissor, so the row must disable it"
        )
    assert "No moving specular" in row, (
        "the reason must travel with the zeroed row, not only with this test"
    )


def test_the_token_bed_matches_the_bed_the_panes_drew_before():
    """The conversion is a re-material, not a re-tint: the bed was 0.105/0.105/
    0.11, and the row's tint must keep that identity (a little translucent)."""
    row = _moodboard_row()
    tint_top = re.search(r"/\*\s*tint_top\s*\*/\s*\{([^}]*)\}", row)
    assert tint_top
    values = _floats(tint_top.group(1))
    assert values[:3] == [0.105, 0.105, 0.110], (
        f"the moodboard bed drifted to {values[:3]}; the frame and the node "
        f"card were 0.105/0.105/0.11 before the conversion"
    )
    assert values[3] < 1.0, "an opaque bed defeats the point of a glass pane"
