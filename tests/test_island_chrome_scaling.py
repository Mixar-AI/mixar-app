# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's chrome has ONE unit, and text is not exempt from it.

Rects are sized in the island unit ``u = window_native_pixel_x / AGENT_ISLAND_W``
(`agent_ui_layout.cc`), which is self-calibrating: the window IS the island. Text
was sized with ``AGENT_DU(v) = v / 1.5 * UI_SCALE_FAC``, which does not depend on
the window width at all. The two are numerically equal only at the 1.5x export
width (874). The shipped default is a compact cut of that artboard, and
`bubble_set_min_content_size` constrains the MINIMUM width only — the user can
widen the bubble freely. Widening it therefore grows every pill, chip, card and
label together.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
DRAW_CC = (CPP / "agent_ui_draw.cc").read_text(encoding="utf-8")
CONTROLS_CC = (CPP / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
LAYOUT_CC = (CPP / "agent_ui_layout.cc").read_text(encoding="utf-8")
THEME_HH = (CPP / "agent_ui_theme.hh").read_text(encoding="utf-8")
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """Code only — the comments explaining the fix name AGENT_DU()."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _define(source: str, name: str) -> float:
    match = re.search(rf"^#define {name}\s+([0-9.]+)f?\s*$", source, re.M)
    assert match is not None, f"{name} not found"
    return float(match.group(1))


def test_the_island_painter_no_longer_sizes_anything_with_agent_du():
    """`agent_ui_draw.cc` paints the island, whose every metric is `u`.

    AGENT_DU() stays the right tool for surfaces that are NOT the island (the
    window sizing constants, for one) — it is its use inside this painter that
    was the bug.
    """
    assert "AGENT_DU(" not in _strip_comments(DRAW_CC + CONTROLS_CC), (
        "an AGENT_DU() call came back into the island painter: it is fixed to "
        "UI_SCALE_FAC and does not track the window's width"
    )


def test_the_island_unit_is_still_derived_from_the_window():
    """`layout->scale` is the unit every painter reads; it must stay
    self-calibrating against the window, not against UI_SCALE_FAC."""
    assert "const float u = float(window_w) / float(AGENT_ISLAND_W);" in LAYOUT_CC
    assert "r_layout->scale = u;" in LAYOUT_CC


def test_the_default_window_is_a_compact_cut_of_the_artboard():
    """The island unit is ``window_w / AGENT_ISLAND_W`` at every size.

    The 1.5x export would open at 874 logical px and dominate the viewport.
    The shipped default is a compact cut: wide enough that body type stays
    near 11 pt, short enough that the empty composer and the first
    conversation do not cover the 3D view. Widening the window still grows
    every pill, chip and label together.
    """
    island_w = _define(THEME_HH, "AGENT_ISLAND_W")
    default_w = _define(BUBBLE_CC, "AGENT_BUBBLE_DEFAULT_WIDTH")
    default_h = _define(BUBBLE_CC, "AGENT_BUBBLE_DEFAULT_HEIGHT")
    transcript_h = _define(BUBBLE_CC, "AGENT_BUBBLE_TRANSCRIPT_HEIGHT")
    expanded_h = _define(BUBBLE_CC, "AGENT_BUBBLE_EXPANDED_HEIGHT")
    pill_w = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_WIDTH_LARGE")
    pill_h = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_HEIGHT_LARGE")
    assert default_w == 800
    assert default_h == 272
    assert default_h + transcript_h == 480
    assert expanded_h == 560
    assert pill_w == 304
    assert pill_h == 44
    assert pill_w / pill_h > 4.0
    scale = default_w / island_w
    assert 0.60 < scale < 0.62


def test_compact_height_is_valid_the_card_stretches():
    """A window shorter than the artboard must still lay out.

    ``region_h < AGENT_ISLAND_H * u`` rejected the shipped 272 px empty
    island (and the 480 px chat island): chrome never drew, only the
    prompt field remained. Height is valid down to the same chrome floor
    the Scribble pad already uses.
    """
    build = _function_body(LAYOUT_CC, "void agent_ui_layout_build(")
    assert "AGENT_ISLAND_H * u" not in build
    assert "AGENT_PANEL_Y - top_du + AGENT_INPUT_H + AGENT_INPUT_GAP + AGENT_CHIP_H +" in build
    assert "region_h < min_h - slack" in build


def test_open_and_restore_keep_chat_height_once_there_is_a_transcript():
    """Grow-once only fires once. Open/restore must still size to
    DEFAULT + TRANSCRIPT when messages exist, or minimise returns a
    conversation to the empty 272 px island.
    """
    body = _function_body(
        BUBBLE_CC, "static int agent_bubble_collapsed_height_for_current_attachments("
    )
    assert "AGENT_BUBBLE_TRANSCRIPT_HEIGHT" in body
    assert "mixie_chat_messages" in body


def test_compact_card_follows_the_window_foot():
    """Chips sit on the card foot. Flooring ``card_h`` at ``AGENT_CARD_H``
    put that foot below a window shorter than the artboard, so Upload /
    Scribble / Generate never appeared in the compact empty island.
    """
    build = _function_body(LAYOUT_CC, "void agent_ui_layout_build(")
    assert "std::max(float(AGENT_CARD_H)" not in build
    assert "region_h / u + top_du - AGENT_CARD_Y" in build


def _function_body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function: {signature_start}")


def test_chip_row_metrics_all_share_one_unit():
    """The chip row is where mixing the two systems was visible as geometry,
    not just as type size: pad and icon box in one unit, radius in another."""
    body = _function_body(CONTROLS_CC, "void agent_ui_draw_chip_row(")
    for token in (
        "AGENT_CHIP_FONT",
        "AGENT_CHIP_RADIUS",
        "AGENT_CHIP_PAD_X",
        "AGENT_CHIP_ICON_GAP",
        "AGENT_CHIP_ICON",
    ):
        assert re.search(rf"{token} \* u;", body), f"{token} is not in the island unit"


def test_tab_strip_and_card_header_text_scale_with_the_island():
    """The labels the bug was reported against: tab strip, queue count, NEW
    badge, card title and FAQs."""
    strip = _function_body(CONTROLS_CC, "void agent_ui_draw_tab_strip(")
    assert "AGENT_TAB_FONT * u" in strip
    assert strip.count("AGENT_NEW_BADGE_FONT * u") == 2, (
        "the queue count chip and the NEW badge both draw at this size"
    )

    island = _function_body(DRAW_CC, "void agent_ui_draw_island(")
    assert island.count("AGENT_HDR_TITLE_FONT * u") == 2, (
        "the Agent tab's session title and the pane tabs' card title"
    )
    assert "AGENT_HDR_FAQ_FONT * u" in island


def test_status_pill_uses_its_own_window_unit():
    """The pill is a separate, force-sized window — it carries neither the
    island's scale nor UI_SCALE_FAC's ratio to it, so it derives its own unit
    from its height, exactly as its status dot already did."""
    body = _function_body(DRAW_CC, "void agent_ui_draw_status_pill(")
    assert "const float pill_u = h / float(AGENT_PILL_H);" in body
    assert "AGENT_PILL_DOT_R * pill_u" in body
    assert "AGENT_PILL_FONT * pill_u" in body
