# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Progressive canvas template strip: buttons appear as width allows."""

from ..constants import NODE_TEMPLATES


def templates_that_fit(available_px, items, *, widths, more_width, gap) -> list:
    """Return the leading templates whose buttons fit beside the + menu.

    ``items`` is an ordered sequence of ``(key, label, icon, capability)``
    tuples (typically mesh first, then ``NODE_TEMPLATES`` shortcuts). ``widths``
    contains the measured pixel width of each button, keyed by template ID.
    Reserve the + button and a gap after EVERY shortcut, including the last.
    """
    budget = float(available_px) - more_width
    shown = []
    for item in items:
        needed = widths[item[0]] + gap
        if budget < needed:
            break
        shown.append(item)
        budget -= needed
    return shown


def canvas_template_strip_items(items=NODE_TEMPLATES):
    """Mesh first, then the supplied catalog entries in registry order."""
    mesh = next(item for item in items if item[0] == 'MESH_REFERENCE')
    return (mesh,) + tuple(item for item in items if item[0] != 'MESH_REFERENCE')
