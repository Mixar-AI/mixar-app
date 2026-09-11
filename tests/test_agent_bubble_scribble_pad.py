# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble turns the island into a writing PAD on the host's right third.

Arming Scribble freezes the 3D viewport for sketching — and the island, seated
at the host's centre-bottom, sat right on top of the frame the user wanted to
draw on. While Scribble is armed the open island is now re-seated as a tall,
narrow pad on the host window's right third (viewport clear), and goes back
to the frame it had when Scribble ends.

Three things had to hold for that to be more than a window move:

* the island's unit is width-derived, so a narrower window would have shrunk
  every label and chip — the pad keeps the DEFAULT-width unit and re-flows
  the card, panel and composer to its own width instead;
* the pill was detected by WIDTH (< 874 px), so a narrow island would have
  drawn as the pill capsule — detection is by window identity now;
* the per-frame constraint sync and the grow-once latch would have fought
  the pad's size — both stand down while it is up.

Source-level, like the rest of the C++ surface's contracts.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (D / "space_agent_bubble.cc").read_text(encoding="utf-8")
LAYOUT_CC = (D / "agent_ui_layout.cc").read_text(encoding="utf-8")
LAYOUT_HH = (D / "agent_ui_layout.hh").read_text(encoding="utf-8")
DRAW_CC = (D / "agent_ui_draw.cc").read_text(encoding="utf-8")
THEME_HH = (D / "agent_ui_theme.hh").read_text(encoding="utf-8")
COCOA_MM = (ROOT / "src/intern/ghost/intern/GHOST_SystemCocoa.mm").read_text(encoding="utf-8")
WIN32_CC = (ROOT / "src/intern/ghost/intern/GHOST_SystemWin32.cc").read_text(encoding="utf-8")


def _body(source: str, signature_start: str) -> str:
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
    raise AssertionError(f"unbalanced body after {signature_start!r}")


# ---------------------------------------------------------------------------
# 1. The pad follows Scribble's edges, from the one C++ poll of the mode
# ---------------------------------------------------------------------------


def test_hover_tick_applies_and_restores_the_pad_on_scribble_edges():
    body = _body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_hover_tick_exec")
    edge = body.index("agent_bubble_scribble_active(C);")
    assert "agent_bubble_pad_apply(C);" in body
    assert "agent_bubble_pad_restore(C);" in body
    # Before the cooldown gate: a pad must not wait on a minimise settling.
    assert edge < body.index("if (now < g_hover_cooldown_until)")
    assert body.index("agent_bubble_pad_apply(C);") < body.index("if (now < g_hover_cooldown_until)")


def test_pad_apply_takes_the_hosts_right_third_and_forces_the_agent_tab():
    body = _body(BUBBLE_CC, "static void agent_bubble_pad_apply(bContext *C)")
    assert "host_w / 3" in body
    assert "off_x = host_w - pad_w - AGENT_BUBBLE_PAD_SIDE_INSET" in body
    # The pad has no tab strip, so the card must be showing the chat.
    assert 'RNA_enum_set_identifier(C, &wm_ptr, "mixar_bubble_tab", "AGENT")' in body
    # The island's frame is remembered relative to the HOST, size + offset.
    assert "Mixar_WindowGetParentOffset(" in body
    assert "g_pad_saved_w = cur_w" in body
    # Constraints on both sides of the resize (Win32 enforces inside
    # SetWindowPos; Cocoa's force-size resets them).
    force = body.index("Mixar_WindowForceSize(g_bubble_ghostwin, pad_w, pad_h)")
    mins = [m.start() for m in re.finditer(r"Mixar_WindowSetMinContentSize\(", body)]
    assert any(m < force for m in mins) and any(m > force for m in mins)
    # Seated relative to the host and left following it from there.
    assert body.index("Mixar_WindowPlaceInParent(") < body.index("bubble_rebaseline_host_tracking();")


def test_pad_restore_puts_the_saved_frame_back():
    body = _body(BUBBLE_CC, "static void agent_bubble_pad_restore(bContext *C)")
    assert "g_bubble_pad_active = false;" in body
    assert "bubble_force_size_and_refresh(C, g_bubble_ghostwin, w, h);" in body
    assert "g_pad_saved_off_x, g_pad_saved_off_y" in body
    # No saved frame -> the island's default seat, never nowhere.
    assert "Mixar_WindowSnapToCentreBottomOfWindow(" in body


def test_pad_is_dropped_by_minimise_and_teardown():
    minimise = _body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_minimise_exec")
    assert "g_bubble_pad_active = false;" in minimise
    closed = _body(BUBBLE_CC, "void ED_agent_bubble_windows_closed()")
    freed = _body(BUBBLE_CC, "void ED_agent_bubble_window_freed(const void *ghostwin)")
    assert "g_bubble_pad_active = false;" in closed
    assert "g_bubble_pad_active = false;" in freed


# ---------------------------------------------------------------------------
# 2. Nothing fights the pad's size
# ---------------------------------------------------------------------------


def test_constraint_sync_and_grow_once_stand_down_while_padded():
    mins = _body(BUBBLE_CC, "static void bubble_set_min_content_size(void *ghostwin, const int min_height)")
    assert "if (g_bubble_pad_active && ghostwin == g_bubble_ghostwin)" in mins
    grow = _body(BUBBLE_CC, "static void agent_bubble_island_region_layout(const bContext *C, ARegion * /*region*/)")
    assert "!g_bubble_pad_active" in grow


# ---------------------------------------------------------------------------
# 3. A narrow island is not the pill
# ---------------------------------------------------------------------------


def test_pill_detection_is_by_window_identity():
    body = _body(BUBBLE_CC, "static bool agent_bubble_window_is_pill(const bContext *C)")
    assert "win->runtime->ghostwin == g_pill_ghostwin" in body
    # The width heuristic survives only as the no-pill fallback, and nowhere
    # else decides pill-ness by width any more.
    assert BUBBLE_CC.count("WM_window_native_pixel_x(win) < AGENT_BUBBLE_MIN_WIDTH") == 1
    begin = _body(BUBBLE_CC, "bool agent_bubble_island_layout_get(")
    assert "agent_bubble_window_is_pill(C)" in begin


# ---------------------------------------------------------------------------
# 4. The pad keeps the island's unit and re-flows its geometry
# ---------------------------------------------------------------------------


def test_pad_unit_is_the_default_width_unit():
    ratio = _body(BUBBLE_CC, "static float agent_bubble_pad_ratio(const wmWindow *win)")
    assert "float(AGENT_BUBBLE_DEFAULT_WIDTH) / float(logical_w)" in ratio
    assert "Mixar_WindowGetContentSize(" in ratio
    begin = _body(BUBBLE_CC, "bool agent_bubble_island_layout_get(")
    assert "agent_bubble_pad_ratio(win)" in begin
    assert "/*pad_real_w=*/(pad_ratio > 0.0f) ? px_w : 0" in begin
    chrome = _body(BUBBLE_CC, "static void agent_bubble_sync_chrome_sizes(const bContext *C)")
    assert "agent_bubble_pad_ratio(win)" in chrome
    assert "AGENT_PANEL_Y - (AGENT_CARD_Y - AGENT_PAD_TOP_INSET)" in chrome
    # Panes take the layout's unit rather than re-deriving it from the width.
    draw = _body(BUBBLE_CC, "static void agent_bubble_island_region_draw(const bContext *C, ARegion *region)")
    assert "const float u = layout.scale;" in draw


def test_layout_pad_mode_drops_the_strip_and_reflows_to_the_pad_width():
    assert "bool pad;" in LAYOUT_HH
    assert "int pad_real_w);" in LAYOUT_HH
    build = _body(LAYOUT_CC, "void agent_ui_layout_build(")
    # The chrome-scaling contract's unit line is untouched.
    assert "const float u = float(window_w) / float(AGENT_ISLAND_W);" in build
    assert "const float region_w = pad ? float(pad_real_w) : float(window_w);" in build
    assert "const float island_w = pad ? (region_w / u) : float(AGENT_ISLAND_W);" in build
    # Widths derive from the pad's own extent, not the artboard's 1310.
    for token in ("card_w", "panel_w"):
        assert f"const float {token} = " in build
    assert "f.box(AGENT_CARD_X, AGENT_CARD_Y, card_w, card_h)" in build
    assert "f.box(AGENT_PANEL_X, AGENT_PANEL_Y, panel_w, panel_h)" in build
    assert "const float input_w = card_w - AGENT_SEG_X * 2.0f;" in build
    assert "card_w - AGENT_SEG_X - AGENT_BTN_GENERATE_W" in build
    # No strip on the pad: empty rects, active flags kept.
    assert "r_layout->strip = pad ? rctf{} :" in build
    pad_tab = build[build.index("if (pad) {", build.index("for (int i = 0; i < AGENT_TAB_COUNT; i++)")) :]
    assert "tab.active = active;" in pad_tab[:200]
    assert "AGENT_PAD_TOP_INSET" in THEME_HH and "AGENT_PAD_MIN_W_UNITS" in THEME_HH


def test_painter_and_header_controls_skip_the_strip_on_the_pad():
    island = _body(DRAW_CC, "void agent_ui_draw_island(")
    assert "if (!layout->pad) {\n    draw_tab_strip(layout, state);" in island
    header = _body(BUBBLE_CC, "static void agent_bubble_island_controls_header(")
    loop = header.index("for (const auto &tb : tab_buttons)")
    assert "if (layout->pad)" in header[loop : loop + 200]


# ---------------------------------------------------------------------------
# 5. GHOST helpers exist wherever the window controls do
# ---------------------------------------------------------------------------


def test_content_size_and_place_helpers_exist_on_both_platforms():
    for src in (COCOA_MM, WIN32_CC):
        assert 'extern "C" bool Mixar_WindowGetContentSize(' in src
        assert 'extern "C" void Mixar_WindowPlaceInParent(' in src
    # y-DOWN from the parent's top on Cocoa, matching the offset convention.
    place = COCOA_MM[COCOA_MM.index('extern "C" void Mixar_WindowPlaceInParent(') :]
    place = place[: place.index("\n}\n")]
    assert "NSMaxY(parent_frame) - (CGFloat)offset_y - child_frame.size.height" in place


# ---------------------------------------------------------------------------
# 6. Restore sizes BEFORE it snaps
# ---------------------------------------------------------------------------


def test_restore_resizes_before_snapping_to_the_host():
    """The centre-bottom snap centres the bubble's CURRENT width. A bubble
    minimised out of the pad (504 wide) was centred at that width and then
    widened from its left edge, landing 185 px off-centre — seen in the
    running app. Both restore paths size first."""
    restore = _body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_restore_exec")
    assert restore.index("bubble_force_size_and_refresh(") < restore.index(
        "Mixar_WindowSnapToCentreBottomOfWindow(g_bubble_ghostwin")
    show = _body(BUBBLE_CC, "static wmOperatorStatus agent_bubble_show_window_exec")
    branch = show[show.index("if (g_bubble_ghostwin != nullptr && g_bubble_minimised) {") :]
    branch = branch[: branch.index("g_bubble_minimised = false;")]
    assert branch.index("bubble_force_size_and_refresh(") < branch.index(
        "Mixar_WindowSnapToCentreBottomOfWindow(g_bubble_ghostwin")
