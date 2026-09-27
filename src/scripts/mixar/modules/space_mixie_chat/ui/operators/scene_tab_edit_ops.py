# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated rename commits and explicit scene deletion confirmations."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ...core.scene_tab_edit import batch_preflight, close_scene_tabs, rename_scene_tab
from .scene_tab_ops import real_scenes


def _refresh():
    from ..properties.scene_tabs_props import refresh_scene_tabs
    refresh_scene_tabs()


class MIXIE_CHAT_OT_rename_scene_tab(Operator):
    bl_idname = 'mixie_chat.rename_scene_tab'
    bl_label = 'Rename Scene'
    bl_description = 'Change this scene’s name'
    bl_options = {'REGISTER'}

    scene_uid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    new_name: StringProperty(name='Name', options={'SKIP_SAVE'})

    def target(self):
        return next((s for s in real_scenes() if str(s.session_uid) == self.scene_uid), None)

    def invoke(self, context, event):
        scene = self.target()
        if scene is None:
            return {'CANCELLED'}
        self.new_name = scene.name
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        self.layout.prop(self, 'new_name', text='')

    def execute(self, context):
        ok, reason = rename_scene_tab(self.target(), self.new_name)
        if not ok:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        _refresh()
        return {'FINISHED'}


def _delete_title(tabs):
    if len(tabs) == len(real_scenes()):
        return 'Delete all scenes?'
    return 'Delete this scene?' if len(tabs) == 1 else 'Delete selected scenes?'


def _draw_delete_confirmation(layout, scene_uids):
    tabs, reason = batch_preflight(scene_uids)
    if reason:
        layout.label(text=reason, icon='ERROR')
        return
    all_scenes = len(tabs) == len(real_scenes())
    layout.label(text='Agents will stop and chats will be archived.')
    if all_scenes:
        layout.label(text='A new empty scene will remain open.')


class MIXIE_CHAT_OT_delete_scene_tabs(Operator):
    bl_idname = 'mixie_chat.delete_scene_tabs'
    bl_label = 'Delete Selected Scenes'
    bl_description = 'Stop selected agents, archive their chats and delete these scenes'
    bl_options = {'REGISTER'}

    scene_uids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        tabs, reason = batch_preflight(self.scene_uids)
        if reason:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(
            self, width=380, title=_delete_title(tabs), confirm_text='Yes', cancel_default=True)

    def draw(self, context):
        _draw_delete_confirmation(self.layout, self.scene_uids)

    def execute(self, context):
        count, reason = close_scene_tabs(self.scene_uids)
        _refresh()
        if reason:
            self.report({'WARNING'}, f'{count} deleted. {reason}')
            return {'FINISHED'} if count else {'CANCELLED'}
        self.report({'INFO'}, f'Deleted {count} scene(s)')
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_rename_scene_tab, MIXIE_CHAT_OT_delete_scene_tabs)
