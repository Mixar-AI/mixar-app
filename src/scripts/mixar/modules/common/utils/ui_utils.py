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
