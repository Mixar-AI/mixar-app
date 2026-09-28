# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Collapsed editor menus for a menu bar too narrow to show them inline."""
import bpy


class MIXAR_MT_editor_menus_collapsed(bpy.types.Menu):
    bl_label = "Menu"
    bl_description = "Mixar, File, Edit, Render, Window and Help menus"

    def draw(self, context):
        # TOPBAR_MT_editor_menus labels the app menu with its logo alone,
        # which reads as a blank row inside a vertical menu.
        layout = self.layout
        layout.menu("TOPBAR_MT_blender", text="Mixar", icon='MIXAR_ICON')
        for menu in ("TOPBAR_MT_file", "TOPBAR_MT_edit", "TOPBAR_MT_render",
                     "TOPBAR_MT_window", "TOPBAR_MT_help"):
            layout.menu(menu)
        if hasattr(bpy.types, "MIXAR_MT_community"):
            layout.menu("MIXAR_MT_community")


classes = (MIXAR_MT_editor_menus_collapsed,)
