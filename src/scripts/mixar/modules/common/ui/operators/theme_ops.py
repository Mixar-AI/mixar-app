# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Explicitly apply the built-in palette without changing other preferences."""

import bpy
from bpy.types import Operator

from ...core.theme_backgrounds import apply_forest_backgrounds


class MIXAR_OT_apply_forest_theme(Operator):
    bl_idname = "mixar.apply_forest_theme"
    bl_label = "Apply Mixar Forest"
    bl_description = "Apply Mixar's charcoal and forest-green theme with default text styling"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        bpy.ops.preferences.reset_default_theme()
        apply_forest_backgrounds(context.preferences.themes[0], bpy.data.screens)
        return {'FINISHED'}


class MIXAR_OT_apply_forest_backgrounds(Operator):
    bl_idname = "mixar.apply_forest_backgrounds"
    bl_label = "Reset Workspace Backgrounds"
    bl_description = (
        "Set Zen and Engine viewport backgrounds to #0F0F0F and both Moodboard "
        "hosts to #1E1E1E; use theme backgrounds and hide Material Preview HDRI backdrops"
    )

    def execute(self, context):
        apply_forest_backgrounds(context.preferences.themes[0], bpy.data.screens)
        return {'FINISHED'}


classes = (MIXAR_OT_apply_forest_theme, MIXAR_OT_apply_forest_backgrounds)
