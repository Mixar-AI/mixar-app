# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Bounded native modifier search and legacy quick actions."""
import bpy
from ...constants import ZEN_MODIFIER_ITEMS, ZEN_MODIFIER_TYPES
from ...core.zen_object_controls import editable_mesh


class MIXAR_MT_zen_modifiers(bpy.types.Menu):
    bl_label = "Modifiers"

    def draw(self, context):
        obj = editable_mesh(context)
        if obj is None:
            return
        layout = self.layout
        existing = [m for m in obj.modifiers if m.type in ZEN_MODIFIER_TYPES]
        if existing:
            for modifier in existing:
                op = layout.operator("mixar.zen_select_modifier", text=modifier.name,
                                     icon="RADIOBUT_ON" if modifier == obj.modifiers.active else "RADIOBUT_OFF")
                op.object_name = obj.name
                op.modifier_name = modifier.name
            layout.separator()
        for value, label, description in ZEN_MODIFIER_ITEMS:
            op = layout.operator("mixar.zen_add_modifier", text="Add " + label, icon="ADD")
            op.object_name = obj.name
            op.modifier_type = value


class MIXAR_MT_zen_modifier_catalog(bpy.types.Menu):
    bl_idname = "MIXAR_MT_zen_modifier_catalog"
    bl_label = "Add Modifier"
    bl_options = {'SEARCH_ON_KEY_PRESS'}

    def draw(self, context):
        if editable_mesh(context) is None:
            return
        layout = self.layout
        # Blender draws searchable menus with INVOKE, regular menus with EXEC.
        # Keep the resting menu short, but index the full native enum on typing.
        searching = layout.operator_context == 'INVOKE_REGION_WIN'
        layout.operator_context = 'EXEC_REGION_WIN'
        if searching:
            layout.operator_enum("object.modifier_add", "type")
            return
        search = layout.row()
        search.operator_context = 'INVOKE_REGION_WIN'
        search.operator("wm.search_single_menu", text="Search all modifiers…",
                        icon='VIEWZOOM').menu_idname = self.bl_idname
        layout.separator()
        for kind, label, icon in (
                ('CLOTH', 'Cloth', 'MOD_CLOTH'),
                ('PARTICLE_SYSTEM', 'Particles', 'PARTICLES'),
                ('BEVEL', 'Bevel', 'MOD_BEVEL'),
                ('BOOLEAN', 'Boolean', 'MOD_BOOLEAN'),
                ('SUBSURF', 'Subdivision', 'MOD_SUBSURF')):
            layout.operator("object.modifier_add", text=label, icon=icon).type = kind



classes = (MIXAR_MT_zen_modifiers, MIXAR_MT_zen_modifier_catalog)
