# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Progressive canvas template strip: buttons appear as width allows."""

from ..constants import NODE_TEMPLATES


def templates_that_fit(available_px, items, *, widths, more_width, gap) -> list:
    """Return the leading templates whose buttons fit beside the + menu.

    ``items`` is an ordered sequence of ``(key, label, icon, capability)``
    tuples in shortcut priority order. ``widths``
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
    """Lead with 3D, video and mesh; preserve registry order for the rest."""
    priority = ('MODEL_3D', 'VIDEO_GEN', 'MESH_REFERENCE')
    items = tuple(items)
    return (tuple(item for key in priority for item in items if item[0] == key)
            + tuple(item for item in items if item[0] not in priority))
