# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Share, discover, and open independent copies through the native UI."""
import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ...core import sharing_flow as flow
from .sharing_ui import draw_explore, draw_share
from .sharing_dialog import SharingDialog


class MIXIE_OT_moodboard_share(SharingDialog, Operator):
    bl_idname = 'mixie.moodboard_share'
    bl_label = 'Share Moodboard'
    bl_description = 'Save a private snapshot, share a link, or publish your board in Explore'

    def invoke(self, context, event):
        flow.open_share(context.scene)
        if not context.scene.moodboard_share_title:
            context.scene.moodboard_share_title = context.scene.name
        return self.begin(context, 560)

    def draw(self, context):
        self.track(context)
        draw_share(self.layout, context)


class MIXIE_OT_moodboard_publish(Operator):
    bl_idname = 'mixie.moodboard_publish'
    bl_label = 'Save Snapshot'

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return wm.mixie_chat_is_logged_in and not wm.moodboard_community_busy

    def execute(self, context):
        try:
            flow.publish(context.scene)
        except (ValueError, RuntimeError) as exc:
            flow.notice(str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_OT_moodboard_explore(SharingDialog, Operator):
    bl_idname = 'mixie.moodboard_explore'
    bl_label = 'Explore Moodboards'
    bl_description = 'Discover boards by other creators or manage your own shared boards'

    def invoke(self, context, event):
        flow.load('explore')
        return self.begin(context, 820)

    def draw(self, context):
        self.track(context)
        draw_explore(self.layout, context)


class MIXIE_OT_moodboard_explore_load(Operator):
    bl_idname = 'mixie.moodboard_explore_load'
    bl_label = 'Refresh Moodboards'
    mode: EnumProperty(items=[('current', 'Current', ''), ('explore', 'Explore', ''), ('mine', 'My Boards', '')])
    page: IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        return not context.window_manager.moodboard_community_busy

    def execute(self, context):
        flow.load(None if self.mode == 'current' else self.mode, self.page)
        return {'FINISHED'}


class MIXIE_OT_moodboard_open_link(Operator):
    bl_idname = 'mixie.moodboard_open_link'
    bl_label = 'Open Link'

    @classmethod
    def poll(cls, context):
        return not context.window_manager.moodboard_community_busy

    def execute(self, context):
        try:
            token = flow.token_from_link(context.window_manager.moodboard_community_open_link)
        except ValueError as exc:
            flow.notice(str(exc))
            return {'CANCELLED'}
        flow.open_copy('shared/' + token)
        return {'FINISHED'}


class MIXIE_OT_moodboard_community_action(Operator):
    bl_idname = 'mixie.moodboard_community_action'
    bl_label = 'Moodboard Action'
    index: IntProperty(default=-1)
    action: EnumProperty(items=[(a, label, '') for a, label in (
        ('open', 'Open Copy'), ('copy', 'Copy Link'), ('private', 'Make Private'),
        ('public', 'Publish in Explore'), ('unlisted', 'Share by Link'), ('delete', 'Delete Cloud Board'))])

    @classmethod
    def poll(cls, context):
        return not context.window_manager.moodboard_community_busy

    def invoke(self, context, event):
        if self.action == 'delete':
            return context.window_manager.invoke_confirm(
                self, event, title="Delete cloud board?", message="Shared links will stop working. Your local board stays.")
        return self.execute(context)

    def execute(self, context):
        flow.sync_account()
        if self.index < 0:
            if self.action == 'copy' and context.window_manager.moodboard_community_link:
                context.window_manager.clipboard = context.window_manager.moodboard_community_link
                flow.notice("Link copied")
                return {'FINISHED'}
            return {'CANCELLED'}
        if self.index >= len(flow.records):
            return {'CANCELLED'}
        record = flow.records[self.index]
        if self.action == 'open':
            flow.open_copy(record['id'] if 'id' in record else 'shared/' + record['token'])
        elif self.action == 'copy':
            context.window_manager.clipboard = flow.url(record)
            flow.notice("Link copied")
        elif self.action == 'delete' and 'id' in record:
            flow.delete(record)
        elif self.action in {'private', 'public', 'unlisted'} and 'id' in record:
            flow.change_visibility(record, self.action)
        return {'FINISHED'}


class MIXIE_OT_moodboard_new_share(Operator):
    bl_idname = 'mixie.moodboard_new_share'
    bl_label = 'Save as New Share'
    bl_description = 'Start a separate cloud snapshot; leave the existing shared board unchanged'

    @classmethod
    def poll(cls, context):
        return not context.window_manager.moodboard_community_busy

    def execute(self, context):
        scene = context.scene
        scene.moodboard_share_id, scene.moodboard_share_revision = '', 0
        context.window_manager.moodboard_community_link = ''
        flow.notice("Ready to save a new snapshot")
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_share, MIXIE_OT_moodboard_publish, MIXIE_OT_moodboard_explore,
           MIXIE_OT_moodboard_explore_load, MIXIE_OT_moodboard_open_link,
           MIXIE_OT_moodboard_community_action, MIXIE_OT_moodboard_new_share)


@bpy.app.handlers.persistent
def _on_load(_unused):
    flow.reset()


def register():
    for cls in classes:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    flow.reset()
    for cls in reversed(classes):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
