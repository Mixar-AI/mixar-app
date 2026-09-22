# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Common Module

Shared components for Mixie space including mode selector and utilities.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty


# ============================================================================
# Mode Switching Operator
# ============================================================================

class MIXIE_OT_set_mode(Operator):
    """Switch to a specific Mixie mode"""
    bl_idname = "mixie.set_mode"
    bl_label = "Set Mixie Mode"
    bl_description = "Switch to a specific Mixie mode"
    bl_options = {'REGISTER', 'UNDO'}

    mode: StringProperty(
        name="Mode",
        description="Mode to switch to",
        default="MOODBOARD"
    )

    def execute(self, context):
        smixie = context.space_data
        if smixie and smixie.bl_rna.identifier == "SpaceMixie":
            smixie.mixie_mode = self.mode
            # Trigger redraw
            for area in context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
            return {'FINISHED'}
        return {'CANCELLED'}


# ============================================================================
# Placeholder Operator (for incomplete features)
# ============================================================================

class MIXIE_OT_placeholder(Operator):
    """Placeholder action for features in development"""
    bl_idname = "mixie.placeholder"
    bl_label = "Placeholder Action"
    bl_description = "This is a placeholder button"

    def execute(self, context):
        self.report({'INFO'}, "Placeholder button clicked")
        return {'FINISHED'}


# ============================================================================
# Registration
# ============================================================================

classes = (
    MIXIE_OT_set_mode,
    MIXIE_OT_placeholder,
)


def register():
    """Register shared Mixie components"""
    from bpy.utils import register_class
    for cls in classes:
        try:
            register_class(cls)
        except ValueError:
            pass


def unregister():
    """Unregister shared Mixie components"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        try:
            unregister_class(cls)
        except RuntimeError:
            pass
