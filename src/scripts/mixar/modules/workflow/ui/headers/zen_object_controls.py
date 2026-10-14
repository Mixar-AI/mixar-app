# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Floating adaptive bar; native popovers hold the detailed properties."""
import bpy
from ...core.zen_object_controls import selected_object


def _section(row, panel, label):
    cell = row.row(align=True)
    cell.ui_units_x = 7.0
    if hasattr(bpy.types, panel):
        cell.popover(panel=panel, text=label)
    else:
        cell.enabled = False
        cell.label(text=label)
    cell.mixar_style(component="TOOLBAR", variant="SECONDARY")


def draw_object_controls(layout, context):
    obj = selected_object(context)
    if obj is None:
        return
    row = layout.mixar_surface(theme="ZEN", density="COMPACT").row(align=True)
    row.use_property_decorate = False
    grip = row.row(align=True)
    grip.ui_units_x = 1.4
    grip.operator_context = 'INVOKE_DEFAULT'
    grip.operator('view2d.pan', text='', icon='GRIP')
    grip.mixar_style(component="TOOLBAR", variant="GHOST")
    name = row.row(align=True)
    name.ui_units_x = 5.0
    name.label(text=obj.name if len(obj.name) <= 12 else obj.name[:11] + "…")
    name.mixar_style(component="TOOLBAR", variant="GHOST")
    if obj.type == "MESH":
        _section(row, "MIXAR_PT_zen_object_modifiers", "Modifier")
        _section(row, "MIXAR_PT_zen_object_textures", "Textures")
    else:
        controls = row.row(align=True)
        controls.enabled = obj.data.is_editable
        caption = controls.row(align=True)
        caption.ui_units_x = 3.2
        caption.label(text="Color")
        caption.mixar_style(component="TOOLBAR", variant="GHOST")
        color = controls.row(align=True)
        color.ui_units_x = 1.0
        color.scale_y = 0.5
        color.prop(obj.data, "color", text="")
        caption = controls.row(align=True)
        caption.ui_units_x = 4.8
        caption.label(text="Brightness")
        caption.mixar_style(component="TOOLBAR", variant="GHOST")
        energy = controls.row(align=True)
        energy.ui_units_x = 6.5
        energy.prop(obj.data, "energy", text="", slider=True)
        energy.mixar_style(component="TOOLBAR", variant="SECONDARY")

    close = row.row(align=True)
    close.ui_units_x = 1.4
    close.operator('mixar.zen_object_controls_show', text='', icon='X').show = False
    close.mixar_style(component="TOOLBAR", variant="GHOST")


classes = ()
