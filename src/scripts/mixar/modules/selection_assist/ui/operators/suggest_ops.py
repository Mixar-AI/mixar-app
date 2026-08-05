# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Expand/shrink operators for selection suggestions.

Thin wrappers over the engine so keymap presses get real operator context
(undo push, proper view layer). Poll fails when there is nothing to cycle,
letting the key event fall through untouched.
"""

import bpy

from ...core.engine import ENGINE


class MIXAR_OT_selection_expand(bpy.types.Operator):
    """Select the next suggested set (matching parts, whole asset, ...)"""

    bl_idname = "mixar.selection_expand"
    bl_label = "Expand Selection Suggestion"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ENGINE.can_expand()

    def execute(self, context):
        if not ENGINE.expand(context):
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_selection_shrink(bpy.types.Operator):
    """Step back to the previous suggested set, or dismiss the suggestion
    when nothing has been accepted yet"""

    bl_idname = "mixar.selection_shrink"
    bl_label = "Shrink Selection Suggestion"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and ENGINE.can_shrink()

    def execute(self, context):
        if not ENGINE.shrink(context):
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MIXAR_OT_selection_expand,
    MIXAR_OT_selection_shrink,
)
