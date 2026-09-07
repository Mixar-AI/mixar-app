# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animation for the minimized agent bubble pill while working (not idle).

When the bubble is in its minimized state (the elongated pill, w > h * 4), it
serves as the user's primary interface to Mixie. When Mixie is actively working
(busy agent turn, modifying, or active queue generation), the pill must not
remain static and dim.

Instead, it renders a living, animated representation of work:
  1. Subtle breathing halo and animated green rim along the capsule perimeter.
  2. Pulsing gradient and glowing rim on the Mixar logo chip.
  3. Pulsating green activity indicator dot with an expanding/fading ripple halo.
  4. Animated status text with cycling trailing dots ("Working.", "Working..",
     "Working...", "Working") and task prompt context.
  5. Continuous redraw triggers (ED_region_tag_redraw during pill draw and
     agent_bubble_pill_tag_redraw on hover pump ticks) to ensure the animation
     runs fluidly without stalling or wasting cycles when idle.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP_DIR = ROOT / "src/source/blender/editors/space_agent_bubble"

DRAW_CC = (CPP_DIR / "agent_ui_draw.cc").read_text(encoding="utf-8")
BUBBLE_CC = (CPP_DIR / "space_agent_bubble.cc").read_text(encoding="utf-8")
STATE_CC = (CPP_DIR / "agent_ui_state.cc").read_text(encoding="utf-8")
LAYOUT_CC = (CPP_DIR / "agent_ui_layout.cc").read_text(encoding="utf-8")
THEME_HH = (CPP_DIR / "agent_ui_theme.hh").read_text(encoding="utf-8")


def _pill_draw_function() -> str:
    start = DRAW_CC.index("void agent_ui_draw_status_pill")
    end = DRAW_CC.index("void agent_ui_draw_island", start)
    return DRAW_CC[start:end]


def test_minimized_pill_checks_working_state():
    """The elongated pill checks both status_busy and active queue jobs to
    determine if Mixie is actively working."""
    body = _pill_draw_function()
    elongated = body.index("if (w > h * 4.0f)")
    assert elongated != -1
    elongated_body = body[elongated:]

    assert "is_working" in elongated_body
    assert "state->status_busy || (state->queue_count > 0)" in elongated_body


def test_working_state_derives_continuous_pulse():
    """When working, a smooth sine pulse is derived from wall-clock time
    (BLI_time_now_seconds) to drive the breathing glow effects."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    assert "BLI_time_now_seconds()" in elongated
    assert "pulse = is_working ?" in elongated


def test_working_state_draws_animated_halo_and_rim():
    """When working, the capsule draws an animated breathing outer halo and
    pulsing green rim, while the idle state preserves the resting faint rim."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    assert "if (is_working)" in elongated
    assert "outline_round(&halo," in elongated
    assert "rim_work" in elongated
    assert "outline_round(&pill, h * 0.5f, rim_work);" in elongated
    # Idle branch still renders the resting stroke
    assert "outline_round(&pill, h * 0.5f, rim);" in elongated


def test_working_state_pulses_logo_chip():
    """The right-hand logo chip pulses its green gradient and draws an animated
    glowing rim when working."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    assert "chip_rim" in elongated
    assert "outline_round(&chip, chip_r, chip_rim);" in elongated


def test_logo_pill_matches_border_radii_with_minimized_bubble():
    """The pill behind the logo matches the capsule border radius of the
    minimized agent bubble (both are full pills with half-height radii,
    making the inner pill concentric with the outer capsule)."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    # Outer pill is a capsule with half-height radius
    assert "fill_round_gradient(&pill, h * 0.5f," in elongated
    # Inner pill behind logo matches with half-height radius
    assert "chip_r = (chip.ymax - chip.ymin) * 0.5f" in elongated
    assert "fill_round_gradient(&chip, chip_r," in elongated


def test_working_state_draws_activity_dot_and_animated_dots():
    """The left side of the pill renders a green activity dot with a breathing
    ripple ring and a label with animated trailing dots."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    # Dot and ripple
    assert "ripple" in elongated
    assert "rip_col" in elongated
    assert "fill_round(&ripple, rip_r, rip_col);" in elongated
    assert "fill_round(&dot, dot_r, dot_col);" in elongated

    # Cycling trailing dots (0 to 3 dots)
    assert "dot_count = int(fmod(now * 2.5, 4.0))" in elongated
    assert "dots[i] = '.'" in elongated

    # Status label formulation
    assert "Generating" in elongated
    assert "Working" in elongated
    assert "work_col" in elongated


def test_pill_header_region_tags_continuous_redraw_when_working():
    """In space_agent_bubble.cc, the pill header region tags redraw when
    Mixie is busy or has queue jobs, keeping animation fluid."""
    draw_start = BUBBLE_CC.index("void agent_bubble_header_region_draw")
    draw_end = BUBBLE_CC.index("agent_bubble_header_region_draw_overlay", draw_start)
    draw_body = BUBBLE_CC[draw_start:draw_end]

    assert "if (state.status_busy || state.queue_count > 0)" in draw_body
    assert "ED_region_tag_redraw(region);" in draw_body


def test_hover_tick_pumps_pill_redraw_when_minimised_and_working():
    """The hover tick watchdog ensures the minimized pill window is tagged
    for redraw while working even if the main draw loop goes idle."""
    assert "static void agent_bubble_pill_tag_redraw(wmWindowManager *wm)" in BUBBLE_CC

    tick_start = BUBBLE_CC.index("mixar_bubble_hover_tick_exec")
    tick_end = BUBBLE_CC.index("void MIXAR_OT_bubble_hover_tick", tick_start)
    tick_body = BUBBLE_CC[tick_start:tick_end]

    min_start = tick_body.index("if (g_bubble_minimised)")
    min_body = tick_body[min_start : min_start + 400]

    assert "agent_bubble_pill_tag_redraw" in min_body
    assert "state.status_busy || state.queue_count > 0" in min_body


def test_agent_ui_state_flags_busy_on_session_states():
    """agent_ui_state_gather sets status_busy when mixie_chat_is_busy is true
    or when mixie_chat_state is BUSY or MODIFYING."""
    gather_start = STATE_CC.index("void agent_ui_state_gather")
    gather_body = STATE_CC[gather_start:]

    assert 'enum_is(&scene_ptr, "mixie_chat_state", "BUSY")' in gather_body
    assert 'enum_is(&scene_ptr, "mixie_chat_state", "MODIFYING")' in gather_body


def test_bottom_row_buttons_and_input_bubble_aligned():
    """The input bubble and the bottom row of buttons share matching horizontal
    margins so their left and right edges are flush aligned."""
    assert "const float input_x = AGENT_SEG_X;" in LAYOUT_CC
    # `card_w` is the artboard's AGENT_CARD_W normally and the pad's own width
    # while Scribble is armed — the margins stay AGENT_SEG_X either way.
    assert "const float input_w = card_w - AGENT_SEG_X * 2.0f;" in LAYOUT_CC
    assert "r_layout->input = f.box(input_x," in LAYOUT_CC
    assert "r_layout->chip_upload = f.box(\n      AGENT_SEG_X," in LAYOUT_CC
    assert "#define AGENT_BTN_GENERATE_X (AGENT_CARD_W - AGENT_SEG_X - AGENT_BTN_GENERATE_W)" in THEME_HH
    # Generate keeps that same right inset against the live card width.
    assert "card_w - AGENT_SEG_X - AGENT_BTN_GENERATE_W" in LAYOUT_CC


def test_uniform_spacing_around_input_bubble_and_buttons():
    """Padding below buttons, gap between buttons and input, gap above input, and
    side margins all use uniform 16-unit spacing."""
    assert "#define AGENT_CARD_PAD_BOTTOM 16" in THEME_HH
    assert "#define AGENT_INPUT_GAP 16" in THEME_HH
    assert "#define AGENT_TRANSCRIPT_GAP 16" in THEME_HH
    assert "#define AGENT_SEG_X 16" in THEME_HH

