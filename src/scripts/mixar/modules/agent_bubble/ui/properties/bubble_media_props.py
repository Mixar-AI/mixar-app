# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Media tab sub-state for the agent island.

One WindowManager enum picks which half of the Media tab the island's card
shows — Image Generation or Video Generation. The C++ segmented buttons are
plain ``wm.context_set_enum`` uiButs bound to
``window_manager.mixar_bubble_media_kind`` (the same stock-operator pattern
as ``mixar_bubble_tab`` in ``bubble_tab_props.py``).

This is ONLY island UI state: the actual generation settings stay on the
moodboard tabs' own PropertyGroups (``tab_imagegen`` / ``tab_video_gen``)
and the catalog param groups, so the island and the N-panel always agree.

WindowManager, never Scene: per-session UI state, no .blend serialization,
no undo participation.
"""

import bpy
from bpy.props import EnumProperty

KIND_ITEMS = (
    ('IMAGE', "Image Generation", "Generate images (moodboard Image Gen)"),
    ('VIDEO', "Video Generation", "Generate videos (moodboard Video Gen)"),
)


def _redraw_bubbles(_self, context):
    """Repaint every island so the pane swaps halves immediately."""
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def register():
    bpy.types.WindowManager.mixar_bubble_media_kind = EnumProperty(
        name="Media Kind",
        description="Which media generator the island's Media tab is showing",
        items=KIND_ITEMS,
        default='IMAGE',
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_bubble_media_kind'):
        delattr(bpy.types.WindowManager, 'mixar_bubble_media_kind')
