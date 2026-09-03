# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's chrome has ONE unit, and text is not exempt from it.

Rects are sized in the island unit ``u = window_native_pixel_x / AGENT_ISLAND_W``
(`agent_ui_layout.cc`), which is self-calibrating: the window IS the island. Text
was sized with ``AGENT_DU(v) = v / 1.5 * UI_SCALE_FAC``, which does not depend on
the window width at all. The two are numerically equal ONLY at the default width,
and `bubble_set_min_content_size` constrains the MINIMUM width only — the user can
widen the bubble freely. Widening it therefore grew every pill, chip and card while
the labels inside them stayed at their original pixel size, and `draw_chip_row`,
which mixed both systems in one function, drifted its icon off-centre and started
its label at the wrong x.

That the two agree at the default width is also the correctness check for the fix:
a correct conversion changes nothing at the default size.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
DRAW_CC = (CPP / "agent_ui_draw.cc").read_text(encoding="utf-8")
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
    assert "AGENT_DU(" not in _strip_comments(DRAW_CC), (
        "an AGENT_DU() call came back into the island painter: it is fixed to "
        "UI_SCALE_FAC and does not track the window's width"
    )


def test_the_island_unit_is_still_derived_from_the_window():
    """`layout->scale` is the unit every painter reads; it must stay
    self-calibrating against the window, not against UI_SCALE_FAC."""
    assert "const float u = float(window_w) / float(AGENT_ISLAND_W);" in LAYOUT_CC
    assert "r_layout->scale = u;" in LAYOUT_CC


def test_the_two_unit_systems_agree_at_the_default_width():
    """The conversion is a no-op at the default size — which is why it is safe.

    ``u = AGENT_BUBBLE_DEFAULT_WIDTH * s / AGENT_ISLAND_W`` and
    ``AGENT_DU(1) = s / AGENT_DESIGN_DIVISOR`` for the same interface scale
    ``s``. If a redesign ever moves the default width or the island width
    apart from the 1.5x export factor, this test is the warning that the
    conversion has stopped being appearance-neutral.
    """
    island_w = _define(THEME_HH, "AGENT_ISLAND_W")
    divisor = _define(THEME_HH, "AGENT_DESIGN_DIVISOR")
    default_w = _define(BUBBLE_CC, "AGENT_BUBBLE_DEFAULT_WIDTH")
    assert abs((default_w / island_w) - (1.0 / divisor)) < 0.002


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
    body = _function_body(DRAW_CC, "void draw_chip_row(")
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
    strip = _function_body(DRAW_CC, "void draw_tab_strip(")
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
