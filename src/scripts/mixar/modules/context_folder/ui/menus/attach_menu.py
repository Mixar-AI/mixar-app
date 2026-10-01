# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Attach chooser: native menu dismissal with two descriptive action cards."""
from bpy.types import Menu
from mixar.modules.common.i18n import iface_


class MIXIE_CHAT_MT_attach(Menu):
    bl_idname = "MIXIE_CHAT_MT_attach"
    bl_label = "Attach context"

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 14
        layout.operator_context = 'INVOKE_DEFAULT'
        row = layout.row()
        row.scale_y = 2.8
        row.operator("mixie_chat.add_image_from_file", icon='FILE_IMAGE', translate=False,
                     text=iface_("Images & 3D files") + "\n" + iface_("Add visual references or models"))
        row.mixar_cinema_row(kind='DESCRIPTION')
        row = layout.row()
        row.scale_y = 2.8
        row.operator("mixie_chat.add_context_folder", icon='FILE_FOLDER', translate=False,
                     text=iface_("Project folder") + "\n" + iface_("Let Mixie read files in a folder"))
        row.mixar_cinema_row(kind='DESCRIPTION')


classes = (MIXIE_CHAT_MT_attach,)
