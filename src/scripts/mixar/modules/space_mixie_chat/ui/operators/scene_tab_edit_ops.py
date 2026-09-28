# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated rename commits and explicit scene deletion confirmations."""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ...core.scene_tab_edit import (
    batch_preflight, close_scene_tabs, rename_scene_tab, tab_has_chat, tab_is_empty)
from .scene_tab_ops import _running, real_scenes

logger = get_logger(__name__)


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
        return f'Delete all {len(tabs)} scenes?'
    if len(tabs) == 1:
        return f'Delete \u201c{tabs[0].name}\u201d?'
    return f'Delete {len(tabs)} scenes?'


def delete_consequences(tabs) -> list:
    """What a delete costs, from the tabs' real state: one line per fact,
    nothing generic. Shared by the batch dialog and the drawer's in-card
    confirmation (which reads the same facts off the tab mirror)."""
    lines = []
    working = sum(1 for s in tabs if _running(s))
    chats = sum(1 for s in tabs if tab_has_chat(s))
    if working:
        lines.append('Stops the working agent' if working == 1 else f'Stops {working} working agents')
    if chats:
        lines.append('Chat kept in History' if chats == 1 else f'{chats} chats kept in History')
    if not lines:
        lines.append('Their objects go with them' if len(tabs) > 1 else 'Its objects go with it')
    if len(tabs) == len(real_scenes()):
        lines.append('A new empty scene stays open')
    return lines


def _draw_delete_confirmation(layout, scene_uids):
    tabs, reason = batch_preflight(scene_uids)
    if reason:
        layout.label(text=reason, icon='ERROR')
        return
    for line in delete_consequences(tabs):
        layout.label(text=line)


class MIXIE_CHAT_OT_delete_scene_tabs(Operator):
    bl_idname = 'mixie_chat.delete_scene_tabs'
    bl_label = 'Delete Selected Scenes'
    bl_description = 'Stop selected agents, archive their chats and delete these scenes'
    bl_options = {'REGISTER'}

    scene_uids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    # The scenes drawer asks on the card itself and calls with this set; the
    # header's batch delete (no single card to ask on) keeps the dialog.
    confirmed: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        tabs, reason = batch_preflight(self.scene_uids)
        if reason:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        if self.confirmed:
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(
            self, width=380, title=_delete_title(tabs), confirm_text='Delete', cancel_default=True)

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


# --- a tab with nothing to lose: no question, an Undo instead -----------------

UNDO_TOAST_ID = 'mixie-scene-tab-undo'
_last_deleted = {}   # {"name": str} of the tab the Undo toast can bring back


class MIXIE_CHAT_OT_delete_scene_tab_now(Operator):
    bl_idname = 'mixie_chat.delete_scene_tab_now'
    bl_label = 'Delete Empty Scene'
    bl_description = 'Delete an empty, idle scene tab at once; a toast offers Undo'
    bl_options = {'REGISTER', 'INTERNAL'}

    scene_uid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        scene = next((s for s in real_scenes() if str(s.session_uid) == self.scene_uid), None)
        if scene is None:
            return {'CANCELLED'}
        if not tab_is_empty(scene):
            # The mirror was stale (a message landed since): ask like any other tab.
            return bpy.ops.mixie_chat.delete_scene_tabs('INVOKE_DEFAULT', scene_uids=f'["{self.scene_uid}"]')
        name = scene.name
        count, reason = close_scene_tabs(f'["{self.scene_uid}"]')
        _refresh()
        if not count:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        _last_deleted.clear()
        _last_deleted['name'] = name
        slog('tab.close.quiet', None, scene_name=name)
        try:
            from mixar.modules.common.notifications.store import (
                NotificationAction, get_notification_store)
            get_notification_store().push(
                type_str='info', title=f'\u201c{name}\u201d deleted', body='It was empty.',
                priority='low', id=UNDO_TOAST_ID, ttl_ms=6000,
                actions=[NotificationAction(label='Undo', operator='mixie_chat.undo_delete_scene_tab',
                                            style='primary')])
        except Exception:  # noqa: BLE001 — the delete stands without its toast
            logger.debug('undo toast skipped', exc_info=True)
        return {'FINISHED'}


class MIXIE_CHAT_OT_undo_delete_scene_tab(Operator):
    bl_idname = 'mixie_chat.undo_delete_scene_tab'
    bl_label = 'Undo Delete Scene'
    bl_description = 'Bring back the empty scene tab that was just deleted'
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        name = _last_deleted.pop('name', '')
        try:
            from mixar.modules.common.notifications.store import get_notification_store
            get_notification_store().dismiss(UNDO_TOAST_ID)
        except Exception:  # noqa: BLE001
            pass
        if not name:
            return {'CANCELLED'}
        from .scene_tab_ops import new_scene_tab
        scene = new_scene_tab(name)   # empty, like the one that went: nothing else was in it
        _refresh()
        slog('tab.close.undone', scene)
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_rename_scene_tab, MIXIE_CHAT_OT_delete_scene_tabs,
           MIXIE_CHAT_OT_delete_scene_tab_now, MIXIE_CHAT_OT_undo_delete_scene_tab)
