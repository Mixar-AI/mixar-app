# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Header definition for the Texture Sets space."""

import bpy
from bpy.types import Header


class TEXTURE_SETS_HT_header(Header):
    """Header for the Texture Sets space."""
    bl_space_type = 'TEXTURE_SETS'

    def draw(self, context):
        layout = self.layout
        layout.template_header()

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
