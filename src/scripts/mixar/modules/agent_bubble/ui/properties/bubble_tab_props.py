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

from ...constants import CHAT_TAB_MODES

TAB_ITEMS = (
    ('AGENT', "Agent", "Chat with the agent"),
    ('THREE_D', "3D", "3D generation (coming soon)"),
    ('IMAGE', "Image", "Image generation"),
    ('VIDEO', "Video", "Video generation"),
    ('SPLAT', "Splats", "Gaussian splat worlds (coming soon)"),
    ('ADDON', "Add-on", "Build a Blender add-on with the agent"),
    ('GENERATIONS', "Library",
     "Your generations and connected asset libraries"),
    ('QUEUE', "Queue", "Generation job queue"),
)


def _on_tab_changed(self, context):
    """Put the chat into the selected chat tab's mode, then repaint.

    Agent -> ``AGENT``, Add-on -> ``ADDON_PROJECT`` (``CHAT_TAB_MODES``); a
    pane tab leaves ``scene.mixie_chat_mode`` untouched. This is the ONE
    writer of the mode from the island — the C++ strip is stock
    ``wm.context_set_enum`` buttons and knows nothing about modes.
    """
    mode = CHAT_TAB_MODES.get(getattr(self, "mixar_bubble_tab", ""))
    scene = getattr(context, "scene", None) if context else None
    if mode and scene is not None and hasattr(scene, "mixie_chat_mode") \
            and scene.mixie_chat_mode != mode:
        scene.mixie_chat_mode = mode
    _redraw_bubbles(self, context)


def _redraw_bubbles(_self, context):
    """Repaint every island so the card swaps content immediately."""
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    try:
        from mixar.modules.common.analytics.journey_events import tab_changed
        tab_changed(context, wm.mixar_bubble_tab)
    except Exception:
        pass
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
        update=_on_tab_changed,
        options={'SKIP_SAVE'},
    )
    from mixar.modules.common.analytics.journey_events import tab_changed
    tab_changed(bpy.context, 'AGENT')


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_bubble_tab'):
        delattr(bpy.types.WindowManager, 'mixar_bubble_tab')
