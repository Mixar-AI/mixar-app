# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact Zen toolbar popovers retain all scene controls on small windows."""

import bpy

from ..headers.zen_scene_controls import draw_render_settings, draw_sky


class MIXAR_PT_zen_render_settings(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Render Settings"
    bl_ui_units_x = 18

    def draw(self, context):
        draw_render_settings(self.layout, context, vertical=True)


class MIXAR_PT_zen_sky(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Sky Light"
    bl_ui_units_x = 14

    def draw(self, context):
        draw_sky(self.layout, context)
        self.layout.label(text="Uses the scene world in renders.")


classes = (MIXAR_PT_zen_render_settings, MIXAR_PT_zen_sky)
