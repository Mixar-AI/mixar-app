# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for Scribble ink overlay moodboard dot grid surface and text output.

When scribble mode is on:
  1. A translucent surface covers the chat window with the same pattern as the
     moodboard background (uniform gray dot grid of filled discs).
  2. The scribble text output window is moved over the new chat topbar, displaying
     the recognized handwriting text in a sleek pill window over the topbar.
  3. That same surface continues over the Agent island's composer, so a stroke
     running off the transcript does not stop at the region seam.

(3) is drawn by the ONE painter the chat owns rather than a copy in the island
-- see tests/test_scribble_canvas_grid.py for why the copy had to go, and for
the arithmetic that keeps the lattice's reserved vertex count honest.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_DIR = ROOT / "src/source/blender/editors/space_mixie_chat"
BUBBLE_DIR = ROOT / "src/source/blender/editors/space_agent_bubble"

OVERLAY_CC = (CHAT_DIR / "mixie_chat_ink_overlay.cc").read_text(encoding="utf-8")
DRAW_CC = (BUBBLE_DIR / "agent_ui_draw.cc").read_text(encoding="utf-8")
BUBBLE_CC = (BUBBLE_DIR / "space_agent_bubble.cc").read_text(encoding="utf-8")


def test_overlay_draws_moodboard_dot_grid():
    """The lattice is a uniform grid of filled discs, matching the moodboard.

    Takes a rect and an origin because the island's composer draws the same
    lattice into a different region and must be able to anchor it to the
    transcript's corner rather than its own.
    """
    assert "void mixie_chat_ink_draw_grid(" in OVERLAY_CC
    assert "const rctf *rect," in OVERLAY_CC
    assert "const float origin_x," in OVERLAY_CC
    assert "const float dot_color[4] = {0.45f, 0.45f, 0.45f, 0.35f * ease};" in OVERLAY_CC
    assert "immBegin(GPU_PRIM_TRIS, dot_count * segments * 3);" in OVERLAY_CC


def test_overlay_surface_is_translucent():
    """The base surface is translucent and dark before the dot grid is drawn.

    Scrim and lattice are one painter (`mixie_chat_ink_draw_canvas`) so the
    island's slice cannot mix the surface at a different alpha -- that is what
    made the composer read as a panel ruled across the Scribble pad.
    """
    assert "void mixie_chat_ink_draw_canvas(" in OVERLAY_CC
    assert "chat_ui_draw_rounded_rect(rect, 0.0f, scrim);" in OVERLAY_CC
    assert "mixie_chat_ink_draw_canvas(&full, scale, 0.0f, 0.0f, ease);" in OVERLAY_CC
    assert "INK_CANVAS_SCRIM" in OVERLAY_CC


def test_scribble_text_output_window_over_topbar():
    """In scribble mode, the text output window is rendered over the new chat
    topbar, showing recognized text in a rounded window replacing 'New Chat'."""
    assert "if (state->ink_visible) {" in DRAW_CC
    assert "/* Scribble text output window over the new chat topbar */" in DRAW_CC
    assert "fill_round(&text_win, 14.0f * u, win_bg);" in DRAW_CC
    assert "outline_round(&text_win, 14.0f * u, win_border);" in DRAW_CC
    assert "state->input_text" in DRAW_CC


def test_overlay_covers_the_composers_share_of_the_panel():
    """The surface covers the composer band, not just the input line's rect.

    Pinned to `layout->input` it left a strip of bare panel above and below it
    and sat inside the transcript's own left and right edges, which drew three
    straight lines across the pad where the surface should have been
    continuous. Panel width, region top down to the chip row -- the chips are
    controls and keep their own ground. The embossed field stays suppressed.
    """
    assert "if (input_prop && !state->ink_visible)" in BUBBLE_CC
    assert "if (state->ink_visible) {" in BUBBLE_CC
    assert "agent_bubble_rect_to_region(region, layout->panel," in BUBBLE_CC
    assert "agent_bubble_rect_to_region(region, layout->chip_upload," in BUBBLE_CC
    assert "mixie_chat_ink_draw_canvas(&canvas, UI_SCALE_FAC, ox, oy, 1.0f);" in BUBBLE_CC
    # The island must own no copy of the surface.
    assert "agent_ui_draw_scribble_input" not in BUBBLE_CC
    assert "agent_ui_draw_scribble_input" not in DRAW_CC

