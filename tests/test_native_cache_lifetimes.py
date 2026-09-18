# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Two process-global caches keyed on raw pointers.

The Mixar category-tab hit rects grew an entry per region that ever drew the
strip and lost none, so opening, closing and splitting the Mixie sidebar leaked
a vector each time. The key is a raw `ARegion *`, so the allocator handing a
freed region's address to a new one let a click read the DEAD region's tab
idnames and switch to a category that may not exist there.

The Agent Bubble's blanket reset fired whenever ANY bubble-space window closed,
wiping the flags of a sibling that was still open. The per-window pointer
invalidation that actually guards against a dangle is a different function, and
already runs for every freed window.
"""

from pathlib import Path

_EDITORS = Path(__file__).parents[1] / "src/source/blender/editors"
_SECTION = _EDITORS / "interface/interface_mixar_section.cc"
# The cache itself lives in its own TU; the section only draws and hands rects over.
_TAB_RECTS = _EDITORS / "interface/interface_mixar_tab_rects.cc"
_WM_WINDOW = (Path(__file__).parents[1]
              / "src/source/blender/windowmanager/intern/wm_window.cc")


def _fn(source: str, signature: str) -> str:
    start = source.index(signature)
    depth, i, seen = 0, start, False
    while i < len(source):
        if source[i] == "{":
            depth += 1
            seen = True
        elif source[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return source[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced body for {signature!r}")


def test_the_tab_rect_cache_is_bounded():
    src = _TAB_RECTS.read_text(encoding="utf-8")
    assert "MIXAR_TAB_RECT_MAX_REGIONS" in src
    # The bound is enforced where entries are added, not merely declared.
    assert "rect_map.size() >= MIXAR_TAB_RECT_MAX_REGIONS" in src
    assert "rect_map.clear();" in src


def test_a_recycled_region_pointer_cannot_read_stale_tabs():
    src = _TAB_RECTS.read_text(encoding="utf-8")
    body = _fn(src, "static const Vector<MixarCategoryTabRect> *mixar_category_tabs_for(")
    assert "winrct" in body and "BLI_rcti_compare" in body
    # Both readers must go through the validating accessor, not the raw map.
    for reader in ("const char *UI_mixar_panel_category_find_at(",
                   "bool UI_mixar_panel_category_tab_rect_get("):
        assert "mixar_category_tabs_for(region)" in _fn(src, reader), reader
        assert "lookup_ptr(region)" not in _fn(src, reader), reader


def test_the_recorded_entry_carries_the_regions_geometry():
    src = _TAB_RECTS.read_text(encoding="utf-8")
    assert "MixarCategoryTabs{region->winrct" in src


def test_the_strip_records_its_rects_through_the_bounded_writer():
    """The bound and the winrct stamp are only worth having if the draw cannot
    reach past them -- the section must hand its rects to the writer rather
    than touching the map, which now lives in another translation unit."""
    src = _SECTION.read_text(encoding="utf-8")
    body = _fn(src, "void UI_panel_category_draw_all_mixar(")
    assert "mixar_category_tabs_store(region, std::move(tab_rects));" in body
    assert "add_overwrite" not in body and "rect_map" not in body


def test_the_bubble_blanket_reset_waits_for_the_last_window():
    """Per-window invalidation is ED_agent_bubble_window_freed's job and runs
    from wm_window_free for every window; this one resets the subsystem."""
    src = _WM_WINDOW.read_text(encoding="utf-8")
    body = _fn(src, "void wm_window_close(")
    assert "ED_agent_bubble_windows_closed();" in body
    assert "bubble_remains" in body, "the blanket reset still fires per window"
    at_reset = body.index("ED_agent_bubble_windows_closed();")
    assert body.index("if (!bubble_remains)") < at_reset


def test_the_remaining_window_scan_uses_the_5_2_listbase_idiom():
    """DNA lists are ListBaseT<T> in 5.2; LISTBASE_FOREACH is 5.0-shaped."""
    body = _fn(_WM_WINDOW.read_text(encoding="utf-8"), "void wm_window_close(")
    assert "for (wmWindow &other : wm->windows)" in body
    assert "LISTBASE_FOREACH" not in body
