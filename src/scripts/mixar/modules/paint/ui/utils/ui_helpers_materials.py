# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material section UI drawing helpers."""


def draw_materials_section(context, layout):
    """Draw materials UI list section with material slots management (Mixar Paint pattern).

    Displays a collapsible materials section showing:
    - Current active material name
    - Material slots template_list when expanded
    - Add/Remove/Move buttons for materials
    - Material assignment buttons (Assign/Select/Deselect) in Edit mode
    - Material properties (blend mode, shadow mode) when material is expanded

    Args:
        context: Blender context containing active object and scene data.
        layout: Blender UI layout to draw the materials section into.
    """
    # Check for valid object first - using context.object for better compatibility
    obj = context.object
    if not obj:
        obj = context.active_object
    if not obj:
        return

    # Only show materials section for object types that support materials
    if obj.type not in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE', 'FONT'}:
        return

    wm = context.window_manager
    if not hasattr(wm, 'mpui'):
        return

    mpui = wm.mpui
    mat = obj.active_material

    # ========== MATERIALS HEADER ==========
    row = layout.row(align=True)

    # Collapsible materials header
    icon = 'TRIA_DOWN' if mpui.show_materials else 'TRIA_RIGHT'
    rrow = row.row(align=True)
    rrow.alignment = 'LEFT'
    rrow.scale_x = 0.95

    # Build material display text
    text_material = 'Material: '
    if mat:
        text_material += mat.name
    else:
        text_material += '-'

    rrow.prop(mpui, 'show_materials', emboss=False, text=text_material, icon=icon)

    # ========== MATERIALS LIST (EXPANDED STATE) ==========
    if mpui.show_materials:
        is_sortable = len(obj.material_slots) > 1
        rows = 2
        if is_sortable:
            rows = 4

        box = layout.box()

        # Material slots list with add/remove/menu buttons
        row = box.row()
        row.template_list("MATERIAL_UL_matslots", "", obj, "material_slots", obj, "active_material_index", rows=rows)

        # Right side buttons column
        col = row.column(align=True)
        # Use custom wrapper operators that work in Properties panel context
        col.operator("wm.m_add_material_slot", icon='ADD', text="")
        col.operator("wm.m_remove_material_slot", icon='REMOVE', text="")
        col.menu("MATERIAL_MT_context_menu", icon='DOWNARROW_HLT', text="")

        # Move buttons (only if sortable)
        if is_sortable:
            col.separator()
            col.operator("wm.m_move_material_slot", icon='TRIA_UP', text="").direction = 'UP'
            col.operator("wm.m_move_material_slot", icon='TRIA_DOWN', text="").direction = 'DOWN'

        # Material assignment buttons (only in Edit mode)
        if obj.mode == 'EDIT':
            row = box.row(align=True)
            row.operator("object.material_slot_assign", text="Assign")
            row.operator("object.material_slot_select", text="Select")
            row.operator("object.material_slot_deselect", text="Deselect")

        # Material selector row
        row = box.row(align=True)

        # Material template_ID (allows creating/selecting materials)
        row.template_ID(obj, "active_material", new="material.new")

        layout.separator(factor=1)
