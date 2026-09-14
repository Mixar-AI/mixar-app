# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native scene/view-layer controls for compact Engine topbars."""
import bpy


class MIXAR_PT_scene_controls(bpy.types.Panel):
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_label = "Scene and View Layer"
    bl_ui_units_x = 16

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Scene")
        col.template_ID(context.window, "scene", new="scene.new", unlink="scene.delete")
        col.separator()
        col.label(text="View Layer")
        col.template_search(context.window, "view_layer", context.window.scene, "view_layers",
                            new="scene.view_layer_add", unlink="scene.view_layer_remove")


classes = (MIXAR_PT_scene_controls,)
