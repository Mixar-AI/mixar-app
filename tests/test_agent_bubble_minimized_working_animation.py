# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animation for the minimized agent bubble pill while working (not idle).

When the bubble is in its minimized state (the elongated pill, w > h * 4), it
serves as the user's primary interface to Mixie. When Mixie is actively working
(busy agent turn, modifying, or active queue generation), the pill must not
remain static and dim.

Instead, it renders a living, animated representation of work:
  1. Subtle breathing glow inset inside the capsule edge and an animated green
     rim along the capsule perimeter.
  2. Pulsing gradient and glowing rim on the Mixar logo chip.
  3. Pulsating green activity indicator dot with an expanding/fading ripple halo.
  4. Animated status text with cycling trailing dots ("Working.", "Working..",
     "Working...", "Working") and task prompt context.
  5. Native one-shot scheduling predicts useful mascot frames. Neither the
     draw callback nor the hover policy duplicates its redraw requests.
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
    assert "mixie_cat_is_working(state->cat_activity)" in elongated_body


def test_working_state_derives_continuous_pulse():
    """When working, a smooth sine pulse is derived from wall-clock time
    (BLI_time_now_seconds) to drive the breathing glow effects."""
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    assert "BLI_time_now_seconds()" in elongated
    assert "pulse = is_working ?" in elongated


def test_working_state_draws_animated_glow_and_rim():
    """When working, the capsule draws an animated breathing glow inside its
    own edge and a pulsing green rim.

    The idle branch paints no rim of its own: the liquid-glass pane that fills
    the capsule already draws the resting stroke, and painting it here a second
    time stacked the two alphas. The glow is INSET rather than an outset halo,
    because the pill's window IS the capsule and an outset shape is clipped.
    """
    body = _pill_draw_function()
    elongated = body[body.index("if (w > h * 4.0f)"):]

    assert "if (is_working)" in elongated
    # Breathing glow, drawn inward from the pill's own bounds.
    assert "glow.xmin += glow_pad;" in elongated
    assert "glow.xmax -= glow_pad;" in elongated
    assert "outline_round(&glow, (h * 0.5f) - glow_pad, glow_col);" in elongated
    assert "rim_work" in elongated
    assert "outline_round(&pill, h * 0.5f, rim_work);" in elongated
    # The resting rim lives in the glass kit's PILL row, not at the call site.
    assert "outline_round(&pill, h * 0.5f, rim);" not in elongated


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

    # Outer pill is a capsule with half-height radius, painted as liquid glass
    assert "glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f);" in elongated
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
    assert "mixie_cat_activity_name(state->cat_activity)" in elongated
    assert "work_col" in elongated


def test_pill_draw_schedules_one_native_frame_without_self_redraw():
    draw_start = BUBBLE_CC.index("void agent_bubble_header_region_draw")
    draw_end = BUBBLE_CC.index("agent_bubble_header_region_draw_overlay", draw_start)
    draw_body = BUBBLE_CC[draw_start:draw_end]
    assert "agent_ui_cat_schedule(win, region, g_host_ghostwin, agent_ui_cat_motion_next_frame(region))" in draw_body
    assert "ED_region_tag_redraw(region)" not in draw_body
    assert "agent_ui_cat_scheduler_forget(region)" in draw_body


def test_hover_tick_only_rearms_after_visibility_changes():
    tick_start = BUBBLE_CC.index("mixar_bubble_hover_tick_exec")
    tick_end = BUBBLE_CC.index("void MIXAR_OT_bubble_hover_tick", tick_start)
    tick_body = BUBBLE_CC[tick_start:tick_end]
    assert "agent_ui_cat_scheduler_sync" in tick_body
    assert "tag_redraw" not in tick_body
    assert "agent_bubble_pill_tag_redraw" not in BUBBLE_CC


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
