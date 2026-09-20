# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Responsive island geometry and fixed, DPI-aware typography contracts."""

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


def test_the_island_painter_keeps_export_units_out_of_geometry_and_text():
    """Geometry and typography each have a resolved unit; neither reapplies
    the source artboard's export divisor."""
    assert "AGENT_DU(" not in _strip_comments(DRAW_CC + CONTROLS_CC)


def test_the_island_unit_is_still_derived_from_the_window():
    """`layout->scale` is the geometry unit; it must stay
    self-calibrating against the window, not against UI_SCALE_FAC."""
    assert "const float u = float(window_w) / float(AGENT_ISLAND_W);" in LAYOUT_CC
    assert "r_layout->scale = u;" in LAYOUT_CC


def test_the_default_window_is_a_compact_cut_of_the_artboard():
    """The island unit is ``window_w / AGENT_ISLAND_W`` at every size.

    The 1.5x export would open at 874 logical px and dominate the viewport.
    The shipped default is 10% larger than the previous compact cut, short enough
    that the empty composer and the first conversation do not cover the
    3D view. Widening the window grows the geometry while typography stays fixed.
    """
    island_w = _define(THEME_HH, "AGENT_ISLAND_W")
    default_w = _define(BUBBLE_CC, "AGENT_BUBBLE_DEFAULT_WIDTH")
    default_h = _define(BUBBLE_CC, "AGENT_BUBBLE_DEFAULT_HEIGHT")
    transcript_h = _define(BUBBLE_CC, "AGENT_BUBBLE_TRANSCRIPT_HEIGHT")
    expanded_h = _define(BUBBLE_CC, "AGENT_BUBBLE_EXPANDED_HEIGHT")
    pill_w = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_WIDTH_LARGE")
    pill_h = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_HEIGHT_LARGE")
    assert default_w == 678
    assert default_h == 230
    assert default_h + transcript_h == 407
    assert expanded_h == 432
    assert pill_w == 304
    assert pill_h == 44
    assert pill_w / pill_h > 4.0
    scale = default_w / island_w
    assert 0.51 < scale < 0.53


def test_post_transcript_strip_grows_instead_of_staying_one_artboard_row():
    """After the first send the composer is a TOOLS strip. A fixed
    AGENT_INPUT_H row is shorter than the multiline gate at the default
    island width, so later prompts must grow the strip and the chrome."""
    build = _function_body(LAYOUT_CC, "void agent_ui_layout_build(")
    assert "agent_ui_composer_strip_h(input_lines)" in build
    assert "chip_y - AGENT_INPUT_GAP - AGENT_INPUT_H" not in build
    chrome = _function_body(BUBBLE_CC, "static void agent_bubble_sync_chrome_sizes(")
    assert "agent_ui_composer_strip_h(input_lines)" in chrome


def test_compact_height_is_valid_the_card_stretches():
    """A window shorter than the artboard must still lay out.

    ``region_h < AGENT_ISLAND_H * u`` rejected the shipped 190 px empty
    island (and the 336 px chat island): chrome never drew, only the
    prompt field remained. Height is valid down to the same chrome floor
    the Scribble pad already uses.
    """
    build = _function_body(LAYOUT_CC, "void agent_ui_layout_build(")
    assert "AGENT_ISLAND_H * u" not in build
    assert "panel_y - top_du + AGENT_INPUT_H + AGENT_INPUT_GAP + AGENT_CHIP_H +" in build
    assert "agent_ui_panel_top(active_tab)" in build
    assert "region_h < min_h - slack" in build


def test_open_and_restore_keep_chat_height_once_there_is_a_transcript():
    """Grow-once only fires once. Open/restore must still size to
    DEFAULT + TRANSCRIPT when messages exist, or minimise returns a
    conversation to the empty 190 px island.
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
        "AGENT_CHIP_RADIUS",
        "AGENT_CHIP_PAD_X",
        "AGENT_CHIP_ICON_GAP",
        "AGENT_CHIP_ICON",
    ):
        assert re.search(rf"{token} \* u;", body), f"{token} is not in the island unit"


def test_tab_strip_uses_fixed_typography_without_redundant_card_titles():
    """Tab labels and badges keep native typography; panes omit their titles."""
    strip = _function_body(CONTROLS_CC, "void agent_ui_draw_tab_strip(")
    assert "AGENT_TAB_FONT * agent_ui_text_unit()" in strip
    assert "AGENT_CHIP_FONT * agent_ui_text_unit()" in CONTROLS_CC
    assert strip.count("AGENT_NEW_BADGE_FONT * agent_ui_text_unit()") == 2, (
        "the queue count chip and the NEW badge both draw at this size"
    )

    island = _function_body(DRAW_CC, "void agent_ui_draw_island(")
    assert "state->title" not in island
    assert "tab_title" not in island
    assert '"Write your prompt here..."' in island
    assert "AGENT_HDR_FAQ_FONT" not in island


def test_status_pill_geometry_uses_its_window_but_text_uses_native_font():
    """Status geometry follows the pill; both label forms match native text."""
    body = _function_body(DRAW_CC, "void agent_ui_draw_status_pill(")
    assert "const float pill_u = h / float(AGENT_PILL_H);" in body
    assert "AGENT_PILL_DOT_R * pill_u" in body
    assert body.count("const float text_size = agent_ui_body_font_size();") == 2
