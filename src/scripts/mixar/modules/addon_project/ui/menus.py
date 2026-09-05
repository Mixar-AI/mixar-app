# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clearly labelled secondary actions for a linked Add-on Project."""

from bpy.types import Menu


class MIXAR_MT_addon_project_more(Menu):
    bl_idname = "MIXAR_MT_addon_project_more"
    bl_label = "Add-on Project Actions"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        project_name = (
            getattr(scene, "mixie_addon_project_name", "") or "Add-on Project"
        )

        layout.label(text=project_name, icon='FILE_SCRIPT')
        layout.separator()
        layout.operator(
            "mixar.addon_project_set_entrypoint",
            text="Choose Entrypoint...",
            icon='PREFERENCES',
        )
        layout.operator(
            "mixar.addon_project_rollback_last",
            text="Undo Last AI Change",
            icon='LOOP_BACK',
        )
        layout.separator()
        layout.operator(
            "mixar.addon_project_unlink",
            text="Unlink Project",
            icon='UNLINKED',
        )


classes = (MIXAR_MT_addon_project_more,)
