# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Material Slot Panel

Material slot management panel for the Mixar UV Properties space.
Mirrors the material slot UI from Properties > Material panel.
"""

import bpy
from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


# Width of the left label column. Matches the Texel Density / Pack Islands
# sub-section split factor so all panels in the Mixar UV Properties space
# line up the same way.
_LABEL_FACTOR = 0.4


def _row(col, label_text):
    """Open a `[label][controls]` split row at the standard label factor.

    Pass an empty `label_text` to leave a blank gutter — useful for
    checkboxes that should align under other rows' controls.
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


def get_active_object_from_3d_view(context):
    """Get the active object from the 3D View."""
    if context.object:
        return context.object

    if context.active_object:
        return context.active_object

    return context.view_layer.objects.active


class MIXAR_UV_PT_material_slot(Panel):
    """Material slot panel for Mixar UV Properties space"""
    bl_label = "Material Slot"
    bl_idname = "MIXAR_UV_PT_material_slot"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'MATERIAL_SLOT')

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        ob = get_active_object_from_3d_view(context)

        if not ob:
            box = layout.box()
            box.label(text="No active object", icon='ERROR')
            return

        if ob.type not in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE',
                           'FONT', 'VOLUME', 'GPENCIL', 'GREASEPENCIL'}:
            box = layout.box()
            box.label(text="Object type does not support materials", icon='INFO')
            return

        mat = ob.active_material
        slot = (ob.material_slots[ob.active_material_index]
                if (ob.material_slots
                    and 0 <= ob.active_material_index < len(ob.material_slots))
                else None)

        # ---- Material slots list + side button column ----
        # No section header — compact, consolidated layout per the design
        # in the Material figma reference.
        is_sortable = len(ob.material_slots) > 1
        rows = 4 if is_sortable else 2

        list_row = layout.row()
        list_row.template_list(
            "MATERIAL_UL_matslots", "",
            ob, "material_slots",
            ob, "active_material_index",
            rows=rows,
        )

        side_col = list_row.column(align=True)
        side_col.operator("object.material_slot_add", icon='ADD', text="")
        side_col.operator("object.material_slot_remove", icon='REMOVE', text="")
        side_col.separator()
        side_col.menu("MATERIAL_MT_context_menu", icon='DOWNARROW_HLT', text="")
        if is_sortable:
            side_col.separator()
            side_col.operator("object.material_slot_move",
                              icon='TRIA_UP', text="").direction = 'UP'
            side_col.operator("object.material_slot_move",
                              icon='TRIA_DOWN', text="").direction = 'DOWN'

        # ---- Active material picker + link selector inline ----
        active_row = layout.row(align=True)
        active_row.scale_y = 1.1
        active_row.template_ID(ob, "active_material", new="material.new")
        if slot:
            active_row.prop(slot, "link", icon_only=True)

        # ---- Assign / Select / Deselect on one row (Edit mode only) ----
        if ob.mode == 'EDIT':
            face_row = layout.row(align=True)
            face_row.scale_y = 1.3
            face_row.operator("object.material_slot_assign", text="Assign")
            face_row.operator("object.material_slot_select", text="Select")
            face_row.operator("object.material_slot_deselect", text="Deselect")

        # ---- Material Properties (if material exists) ----
        if mat:
            layout.separator(factor=0.5)
            box = layout.box()
            col = box.column(align=True)
            col.label(text="Material Properties", icon='PROPERTIES')
            col.separator(factor=0.5)

            _row(col, "Viewport Color").prop(mat, "diffuse_color", text="")
            _row(col, "Metallic").prop(mat, "metallic", text="")
            _row(col, "Roughness").prop(mat, "roughness", text="")
            _row(col, "Pass Index").prop(mat, "pass_index", text="")


classes = (
    MIXAR_UV_PT_material_slot,
)
