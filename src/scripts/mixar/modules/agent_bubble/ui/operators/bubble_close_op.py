# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ESC / close-button → minimise-to-pill operator.

The bubble must never be destroyed by the user — it should always be
present as either the full chat window or the floating status pill.
ESC and the header close button both route here, which minimises the
bubble to the pill instead of calling wm.window_close.

Why this exists instead of binding wm.window_close to the AGENT_BUBBLE
keymap directly:

Blender's event dispatcher consults the global "Window" keymap before
any space-specific keymap, so ESC bindings on a space keymap never
fire. This operator is bound in the global "Window" keymap; poll()
restricts it to the AGENT_BUBBLE space so ESC in every other editor
is unaffected.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator


class MIXAR_OT_bubble_close(Operator):
    bl_idname = "mixar.bubble_close"
    bl_label = "Minimise"
    bl_description = "Minimise"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def execute(self, context):
        # Mark the bubble as user-dismissed so the workspace-change
        # autoshow doesn't immediately re-open it.
        try:
            from mixar.bootstrap import agent_bubble_module
            agent_bubble_module.mark_user_closed()
        except Exception:  # noqa: BLE001 — never break the close path
            pass

        # Minimise to pill instead of destroying the window.
        try:
            return bpy.ops.mixar.bubble_minimise()
        except RuntimeError:
            return {'CANCELLED'}


class MIXAR_OT_bubble_restore_user(Operator):
    """Restore the bubble and clear the user-minimised workspace intent."""

    bl_idname = "mixar.bubble_restore_user"
    bl_label = "Restore"
    bl_description = "Restore"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def execute(self, context):
        try:
            from mixar.bootstrap import agent_bubble_module
            agent_bubble_module.mark_user_opened()
        except Exception:  # noqa: BLE001 - never break restore
            pass

        try:
            return bpy.ops.mixar.bubble_restore()
        except RuntimeError:
            return {'CANCELLED'}


class MIXAR_OT_bubble_block_context_menu(Operator):
    """Consume right-clicks in the bubble/pill without opening UI menus."""

    bl_idname = "mixar.bubble_block_context_menu"
    bl_label = "Block Context Menu"
    bl_description = "Block Context Menu"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def invoke(self, context, event):
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}


classes = (
    MIXAR_OT_bubble_close,
    MIXAR_OT_bubble_restore_user,
    MIXAR_OT_bubble_block_context_menu,
)
