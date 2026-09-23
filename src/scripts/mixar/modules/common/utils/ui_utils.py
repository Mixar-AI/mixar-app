# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared UI drawing utilities.

Reusable widget helpers that work across all Mixar modules.
"""


def _estimate_visual_lines(text, chars_per_line):
    """Estimate visual line count including word-wrap.

    Splits on explicit newlines, then for each segment estimates how many
    visual lines it occupies based on characters-per-line width.
    """
    if not text:
        return 1
    visual_lines = 0
    for segment in text.split('\n'):
        seg_len = len(segment)
        if seg_len == 0:
            visual_lines += 1
        else:
            visual_lines += max(1, -(-seg_len // chars_per_line))  # ceil division
    return visual_lines


def draw_multiline_text_input(layout, data, prop, *, text="",
                              min_lines=2, max_lines=5):
    """Draw a multi-line text input field with word-wrap and scroll support.

    Dynamically sizes based on the number of visual lines (including word-wrap)
    between *min_lines* and *max_lines*.  Content beyond *max_lines* is scrollable.

    Uses the same C++ multiline rendering as the Mixie Chat prompt input:
    word-wrapping, vertical scroll via mouse wheel / touchpad, and a scroll
    indicator when content overflows.  Shift+Enter inserts newlines.

    Requirements for the property:
        - Must be a ``StringProperty``
        - Must include ``options={'TEXTEDIT_UPDATE'}`` in its definition
          (this is how the C++ layer detects multi-line mode)

    Args:
        layout: Parent UILayout to draw into.
        data: RNA data block that owns the property (e.g. ``scene``, a PropertyGroup).
        prop: Name of the StringProperty on *data* (str).
        text: Optional label (default ``""`` for no label).
        min_lines: Minimum visible lines (default 2).
        max_lines: Maximum visible lines before scrolling kicks in (default 5).
    """
    min_lines = max(1, min_lines)
    max_lines = max(min_lines, min(max_lines, 20))

    # Estimate visual lines including word-wrap.
    # The sidebar text input fits ~38 chars per line at default UI scale.
    # This is a conservative estimate that works across typical sidebar widths.
    value = getattr(data, prop, "")
    content_lines = _estimate_visual_lines(value, chars_per_line=38)
    lines = max(min_lines, min(content_lines, max_lines))

    col = layout.column(align=True)
    col.scale_y = lines
    if hasattr(col, 'mixar_input'):
        col.mixar_input(data, prop, text=text)
    else:
        col.prop(data, prop, text=text)


# Header strips that can overlap the top of a 3D viewport's WINDOW region
# (the Zen scene toolbar is the HEADER, drawn over the canvas with region
# overlap). Hidden regions collapse to a 1x1 rect, so size alone says visible.
_TOP_OVERLAP_REGION_TYPES = frozenset({'HEADER', 'TOOL_HEADER'})


def visible_overlapping_headers(area, window_region):
    """The visible header regions of *area* that sit over *window_region*."""
    wx0, wy0 = window_region.x, window_region.y
    wx1, wy1 = wx0 + window_region.width, wy0 + window_region.height
    found = []
    for region in area.regions:
        if region.type not in _TOP_OVERLAP_REGION_TYPES:
            continue
        if region.width <= 1 or region.height <= 1:
            continue
        rx0, ry0 = region.x, region.y
        rx1, ry1 = rx0 + region.width, ry0 + region.height
        if rx0 < wx1 and rx1 > wx0 and ry0 < wy1 and ry1 > wy0:
            found.append(region)
    return found


def top_header_overlap_px(area, window_region):
    """Pixels at the top of *window_region* covered by an overlapping header.

    0 when the headers sit beside the canvas (stock, non-overlap layout),
    are hidden, or are bottom-aligned. Overlays anchored to the top of the
    region (the agent halo, the sketch hint) start below this inset so the
    header neither hides them nor is washed over by them.
    """
    try:
        top = window_region.y + window_region.height
        mid = window_region.y + window_region.height / 2.0
        inset = 0
        for region in visible_overlapping_headers(area, window_region):
            if region.y + region.height / 2.0 < mid:
                continue  # bottom-aligned header
            inset = max(inset, top - region.y)
        return max(0, min(int(inset), int(window_region.height)))
    except Exception:  # noqa: BLE001 — draw-time helper, never raise
        return 0
