# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent island tab state.

One WindowManager enum drives which content the island's card shows —
the C++ tab-strip buttons are plain ``wm.context_set_enum`` uiButs bound to
``window_manager.mixar_bubble_tab``, the same stock-operator pattern the
island's Agent/Generate mode toggle uses (no bespoke operator, no icons
stamped over the painted tabs).

WindowManager, never Scene: tab choice is per-session UI state and must not
be serialized into a shared ``.blend`` or participate in undo.
"""

import bpy
from bpy.props import EnumProperty

TAB_ITEMS = (
    ('AGENT', "Agent", "Chat with the agent"),
    ('THREE_D', "3D", "3D generation (coming soon)"),
    ('MEDIA', "Media", "Media generation (coming soon)"),
    ('SPLAT', "Gaussian Splat", "Gaussian splat worlds (coming soon)"),
    ('GENERATIONS', "My Generations",
     "Your generations and connected asset libraries"),
    ('QUEUE', "Queue", "Generation job queue"),
)


def _redraw_bubbles(_self, context):
    """Repaint every island so the card swaps content immediately."""
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def register():
    bpy.types.WindowManager.mixar_bubble_tab = EnumProperty(
        name="Agent Island Tab",
        description="Which tab the agent island's card is showing",
        items=TAB_ITEMS,
        default='AGENT',
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_bubble_tab'):
        delattr(bpy.types.WindowManager, 'mixar_bubble_tab')
