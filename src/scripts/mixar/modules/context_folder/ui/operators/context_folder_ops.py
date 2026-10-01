# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach and remove chat context folders.

``mixie_chat.attach`` is the composer's paperclip: a descriptive chooser offering an
image / 3D file (the existing picker) or a folder. Folder rows then show as
compact rows in the island's reference column, each with its own remove button.
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import rpt_

from ...core.attach import attach_folder, detach_folder


def _redraw() -> None:
    try:
        from mixar.modules.space_mixie_chat.core.ui_utils import (
            redraw_chat_areas,
            sync_bubble_attachment_size_deferred,
        )

        redraw_chat_areas()
        sync_bubble_attachment_size_deferred()
    except Exception:  # noqa: BLE001 — a redraw never fails the attach
        pass


class MIXIE_CHAT_OT_attach(Operator):
    """Attach a reference image, a 3D file, or a folder the agent can use as context"""
    bl_idname = "mixie_chat.attach"
    bl_label = "Attach"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        bpy.ops.wm.call_menu('INVOKE_DEFAULT', name="MIXIE_CHAT_MT_attach")
        return {'FINISHED'}

    def execute(self, context):
        return self.invoke(context, None)


class MIXIE_CHAT_OT_add_context_folder(Operator):
    """Attach a folder: the agent lists, reads, views and imports its files to work on your request"""
    bl_idname = "mixie_chat.add_context_folder"
    bl_label = "Attach Folder"
    bl_options = {'REGISTER'}

    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, "mixie_context_folders")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        result = attach_folder(context.scene, self.directory)
        if not result["success"]:
            self.report({'ERROR'}, rpt_(result["error"]).format(**result["error_args"]))
            return {'CANCELLED'}
        _redraw()
        if result["already"]:
            self.report({'INFO'}, rpt_("{name} is already attached").format(name=result["name"]))
        else:
            self.report({'INFO'}, rpt_("Attached folder: {name}").format(name=result["name"]))
        return {'FINISHED'}


class MIXIE_CHAT_OT_remove_context_folder(Operator):
    """Detach this folder; the agent can no longer read it"""
    bl_idname = "mixie_chat.remove_context_folder"
    bl_label = "Remove Folder"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and len(getattr(context.scene, "mixie_context_folders", ())) > 0

    def execute(self, context):
        if not detach_folder(context.scene, self.folder_id):
            return {'CANCELLED'}
        _redraw()
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_attach,
    MIXIE_CHAT_OT_add_context_folder,
    MIXIE_CHAT_OT_remove_context_folder,
)
