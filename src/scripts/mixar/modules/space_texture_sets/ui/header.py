# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Header definition for the Texture Sets space."""

import bpy
from bpy.types import Header

from mixar.modules.common.i18n import iface_


class TEXTURE_SETS_HT_header(Header):
    """Title bar for the Texture Sets space.

    Draws ``template_header()``: every editor in the Texturing workspace
    stays swappable, so this space keeps the stock Editor Type dropdown and
    appears under the menu's "Texturing" heading.
    """
    bl_space_type = 'TEXTURE_SETS'

    def draw(self, context):
        layout = self.layout
        layout.template_header()
        layout.label(text="Texture Sets")

        layout.separator_spacer()

        # Active object info
        obj = context.object or context.active_object
        if obj:
            layout.label(text=obj.name, icon='OBJECT_DATA')
            mat_count = len(obj.material_slots)
            layout.label(text=iface_("Materials: {count}").format(count=mat_count),
                         translate=False)


classes = (
    TEXTURE_SETS_HT_header,
)
