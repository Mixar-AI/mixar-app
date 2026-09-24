# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset picker selection for the agent island.

While the agent's asset question is pending the Agent tab shows its picks as a
Library-style grid (``space_agent_bubble/agent_ui_asset_picker.cc``). Clicking
a tile only SELECTS it — the same stock ``wm.context_set_string`` the Library
tab's tiles use — and the detail column's "Use This Asset" answers with the
selected pick. The value stored is the pick's action VALUE; empty or stale
means the first (best) pick.

WindowManager, never Scene: per-session UI state that must not be serialised
into a shared ``.blend`` or take part in undo. The name is a CONTRACT with the
C++ pane and with ``space_mixie_chat/core/asset_picker.py:SELECTED_PROP``,
pinned by ``tests/test_agent_asset_picker.py``.
"""

import bpy
from bpy.props import StringProperty

PROP_NAME = "mixie_chat_asset_pick_selected"


def _redraw_bubbles(_self, context):
    """Repaint every island so the detail column follows the selection."""
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def register():
    bpy.types.WindowManager.mixie_chat_asset_pick_selected = StringProperty(
        name="Selected Asset Pick",
        description="Action value of the asset pick the picker's detail column describes",
        default="",
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, PROP_NAME):
        delattr(bpy.types.WindowManager, PROP_NAME)
