# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Header definition for the Texture Sets space."""

import bpy
from bpy.types import Header


class TEXTURE_SETS_HT_header(Header):
    """Title bar for the Texture Sets space.

    No ``template_header()``: the space is hidden from the Editor Type
    dropdown, matching Zen / Cinema chrome that is not a switchable editor.
    """
    bl_space_type = 'TEXTURE_SETS'

    def draw(self, context):
        layout = self.layout
        layout.label(text="Texture Sets")

        layout.separator_spacer()

        # Active object info
        obj = context.object or context.active_object
        if obj:
            layout.label(text=obj.name, icon='OBJECT_DATA')
            mat_count = len(obj.material_slots)
            layout.label(text=f"Materials: {mat_count}")


classes = (
    TEXTURE_SETS_HT_header,
)
