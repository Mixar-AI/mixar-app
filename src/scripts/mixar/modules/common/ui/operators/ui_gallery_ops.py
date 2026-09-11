# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy

from mixar.modules.common.ui.constants import CARD_DIALOG_WIDTH


def gallery_available(context):
    try:
        from mixar.config._build_env import BUILD_ENVIRONMENT
    except ImportError:
        return False
    return BUILD_ENVIRONMENT == "Dev" and context.preferences.view.show_developer_ui


class MIXAR_OT_ui_gallery_action(bpy.types.Operator):
    bl_idname = "mixar.ui_gallery_action"
    bl_label = "Local gallery action"
    bl_description = "Increment the developer fixture counter; no generation or scene changes"

    @classmethod
    def poll(cls, context):
        return gallery_available(context)

    def execute(self, context):
        context.window_manager.mixar_ui_gallery.clicks += 1
        return {"FINISHED"}


class MIXAR_OT_ui_gallery(bpy.types.Operator):
    bl_idname = "mixar.ui_gallery"
    bl_label = "Mixar UI Gallery"
    bl_description = "Inspect shared native components using local fixture data"

    @classmethod
    def poll(cls, context):
        return gallery_available(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=CARD_DIALOG_WIDTH)

    def draw(self, context):
        from mixar.modules.common.ui.panels.ui_gallery_panel import draw_gallery
        draw_gallery(self.layout, context)

    def execute(self, context):
        return {"FINISHED"}


classes = (MIXAR_OT_ui_gallery_action, MIXAR_OT_ui_gallery)
