# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Assets Space Panel

Panel definition for the Mixar Assets workspace space.
Shows procedural materials and other assets from the paint backend.
"""

from bpy.types import Panel


class MIXAR_ASSETS_PT_main(Panel):
    """Assets Library Panel - Shows procedural materials from paint backend"""
    bl_label = ""
    bl_idname = "MIXAR_ASSETS_PT_main"
    bl_space_type = 'MIXAR_ASSETS'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout

        # Top padding
        layout.separator()

        from ...procedural_materials import material_registry

        # Procedural Materials section
        box = layout.box()
        row = box.row()
        row.label(text="Procedural Materials", icon='MATERIAL')

        col = box.column()

        # Get material categories from registry
        try:
            categories = material_registry.get_categories()
            if categories:
                col.label(text=f"{len(categories)} categories available")
                col.separator()

                # Show procedural material library popup
                col.scale_y = 1.5
                col.operator("layers.procedural_material_library_popup",
                           text="Open Material Library", icon='MATERIAL')
            else:
                col.label(text="No materials loaded", icon='INFO')
        except Exception:
            col.label(text="Material registry unavailable", icon='INFO')

        layout.separator()

        # Smart Materials section
        box = layout.box()
        row = box.row()
        row.label(text="Smart Materials", icon='NODE_MATERIAL')
        col = box.column()
        col.enabled = False
        col.label(text="Coming soon", icon='TIME')

        layout.separator()

        # Brushes section
        box = layout.box()
        row = box.row()
        row.label(text="Brushes", icon='BRUSH_DATA')
        col = box.column()
        col.enabled = False
        col.label(text="Coming soon", icon='TIME')

        layout.separator()

        # Textures section
        box = layout.box()
        row = box.row()
        row.label(text="Textures", icon='TEXTURE')
        col = box.column()
        col.enabled = False
        col.label(text="Coming soon", icon='TIME')


classes = (
    MIXAR_ASSETS_PT_main,
)
