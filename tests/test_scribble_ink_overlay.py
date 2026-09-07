# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for Scribble ink overlay moodboard dot grid surface and text output.

When scribble mode is on:
  1. A translucent surface covers the chat window with the same pattern as the
     moodboard background (uniform gray dot grid of filled discs).
  2. The scribble text output window is moved over the new chat topbar, displaying
     the recognized handwriting text in a sleek pill window over the topbar.
  3. The translucent dot grid overlay also covers the normal text input field at the bottom.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "src/source/blender/editors/space_mixie_chat"
BUBBLE_DIR = ROOT / "src/source/blender/editors/space_agent_bubble"

OVERLAY_CC = (CHAT_DIR / "mixie_chat_ink_overlay.cc").read_text(encoding="utf-8")
DRAW_CC = (BUBBLE_DIR / "agent_ui_draw.cc").read_text(encoding="utf-8")
BUBBLE_CC = (BUBBLE_DIR / "space_agent_bubble.cc").read_text(encoding="utf-8")


def test_overlay_draws_moodboard_dot_grid():
    """ink_draw_moodboard_grid draws a uniform dot grid with segments, matching
    the moodboard background pattern."""
    assert "static void ink_draw_moodboard_grid(float winx, float winy, float scale, float ease)" in OVERLAY_CC
    assert "ink_draw_moodboard_grid(float(winx), float(winy), scale, ease);" in OVERLAY_CC
    assert "const float dot_color[4] = {0.45f, 0.45f, 0.45f, 0.35f * ease};" in OVERLAY_CC
    assert "immBegin(GPU_PRIM_TRIS, dot_count * segments * 3);" in OVERLAY_CC


def test_overlay_surface_is_translucent():
    """The base surface is translucent and dark before the dot grid is drawn."""
    assert "chat_ui_draw_rounded_rect(&full, 0.0f, scrim);" in OVERLAY_CC
    assert "const float scrim[4] = {0.05f, 0.05f, 0.06f, 0.82f * ease};" in OVERLAY_CC


def test_scribble_text_output_window_over_topbar():
    """In scribble mode, the text output window is rendered over the new chat
    topbar, showing recognized text in a rounded window replacing 'New Chat'."""
    assert "if (state->ink_visible) {" in DRAW_CC
    assert "/* Scribble text output window over the new chat topbar */" in DRAW_CC
    assert "fill_round(&text_win, 14.0f * u, win_bg);" in DRAW_CC
    assert "outline_round(&text_win, 14.0f * u, win_border);" in DRAW_CC
    assert "state->input_text" in DRAW_CC


def test_overlay_covers_normal_text_input_field():
    """In scribble mode, the translucent dot grid overlay also covers the normal
    text input field in the bottom region, and the embossed button is suppressed."""
    assert "/* When scribble mode is on, put the translucent dot grid overlay over the" in BUBBLE_CC
    assert "if (input_prop && !state->ink_visible)" in BUBBLE_CC
    assert "if (state->ink_visible) {" in BUBBLE_CC
    assert "agent_bubble_rect_to_region(region, layout->input, &ibx, &iby, &ibw, &ibh);" in BUBBLE_CC
    assert "agent_ui_draw_scribble_input_overlay(&input_rect, layout->scale);" in BUBBLE_CC
    assert "void agent_ui_draw_scribble_input_overlay(const rctf *input_rect, const float scale)" in DRAW_CC

