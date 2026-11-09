# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach and remove chat context folders and context files.

``mixie_chat.attach`` is the composer's paperclip: a descriptive chooser offering
files (the existing picker — images and models keep their pill / import
behaviour, every other file becomes a context-file chip) or a folder. Folder
and file rows then show as compact rows in the island's reference column, each
with its own remove button.
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import rpt_

from ...core.attach import attach_folder, detach_folder
from ...core.files import detach_file


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


_ATTACH_MENU = "MIXIE_CHAT_MT_attach"


def _ensure_attach_menu() -> bool:
    """Make sure the paperclip's chooser menu is registered.

    UI modules load in deferred batches after startup, operators before menus,
    so on a slow machine the paperclip can be clicked while its menu is still
    queued: ``wm.call_menu`` then raised ``Menu "MIXIE_CHAT_MT_attach" not
    found``. Register it now; the loader later reuses the imported module and
    skips classes that are already registered.
    """
    if getattr(bpy.types, _ATTACH_MENU, None) is not None:
        return True
    try:
        from ..menus.attach_menu import MIXIE_CHAT_MT_attach

        if not MIXIE_CHAT_MT_attach.is_registered:
            bpy.utils.register_class(MIXIE_CHAT_MT_attach)
    except Exception:  # noqa: BLE001 — the click reports "still loading" instead
        return False
    return getattr(bpy.types, _ATTACH_MENU, None) is not None


class MIXIE_CHAT_OT_attach(Operator):
    """Attach files (images, 3D models, videos, documents) or a folder the agent can use as context"""
    bl_idname = "mixie_chat.attach"
    bl_label = "Attach"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        if not _ensure_attach_menu():
            self.report({'INFO'}, rpt_("Mixar is still loading. Try again in a moment."))
            return {'CANCELLED'}
        bpy.ops.wm.call_menu('INVOKE_DEFAULT', name=_ATTACH_MENU)
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


class MIXIE_CHAT_OT_remove_context_file(Operator):
    """Detach this file; the agent can no longer read it"""
    bl_idname = "mixie_chat.remove_context_file"
    bl_label = "Remove File"
    bl_options = {'REGISTER', 'INTERNAL'}

    file_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and len(getattr(context.scene, "mixie_context_files", ())) > 0

    def execute(self, context):
        if not detach_file(context.scene, self.file_id):
            return {'CANCELLED'}
        _redraw()
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
    MIXIE_CHAT_OT_remove_context_file,
)
