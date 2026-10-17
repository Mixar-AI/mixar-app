# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Platform and compositing contracts for the Windows/Linux transcript opacity fix."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "src/source/blender/editors/space_agent_bubble"


def test_readable_bed_is_shared_by_windows_and_linux():
    glass = (EDITOR / "agent_bubble_glass.cc").read_text(encoding="utf-8")
    start = glass.index("void agent_bubble_composited_transcript_color(")
    assert glass.rfind("#if defined(WIN32) || defined(__linux__)", 0, start) > glass.rfind("#endif", 0, start)
    body = glass[start:glass.index("#endif", start)]
    assert "if (!island_glass.transparent)" in body
    assert "std::max(wash[3], transcript_min_alpha)" in body
    assert "r_rgba[channel] = wash[channel] * alpha;" in body
    assert "r_rgba[3] = alpha;" in body


def test_transcript_uses_the_shared_composited_bed():
    space = (EDITOR / "space_agent_bubble.cc").read_text(encoding="utf-8")
    call = "agent_bubble_composited_transcript_color(panel_bg, transcript_wash);"
    assert space.count(call) == 1
    start = space.index(call)
    assert "#if defined(WIN32) || defined(__linux__)" in space[start - 160:start]
    assert "#endif\n    mixie_chat_set_bg_override(panel_bg);" in space[start:]


def test_windows_chrome_keeps_blastoff_glass_finishing_layers():
    space = (EDITOR / "space_agent_bubble.cc").read_text(encoding="utf-8")
    assert space.count("agent_bubble_composited_island_wash(wash);") == 3
    draw = (EDITOR / "agent_ui_draw.cc").read_text(encoding="utf-8")
    start = draw.index("  /* --- Card --- */")
    end = draw.index("  /* Session actions", start)
    card = draw[start:end]
    assert "#ifndef WIN32" not in card
    assert "draw_card_border_meter(" in card
    assert "glass_fill_round(" in card
    assert "/*rim=*/false" in card  # The separate whole-card rim avoids doubling.
    assert draw.count("glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f, false, false, false);") == 2
