# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Publish one add-on and download explicit source archives without executing them."""
import base64
import hashlib
import io
from pathlib import Path
import zipfile

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Menu, Operator
from bpy_extras.io_utils import ExportHelper

from ...core import addon_publication as addons
from ...core import sharing_flow as flow
from .sharing_dialog import SharingDialog
from .sharing_ui import draw_link, draw_notice, message, visibility


class MIXAR_OT_addon_share(SharingDialog, Operator):
    bl_idname = 'mixar.addon_share'
    bl_label = 'Publish Add-on'
    bl_description = 'Publish a source package for one add-on you created in Mixar'

    def invoke(self, context, event):
        flow.sync_account()
        context.window_manager.moodboard_community_link = ''
        try:
            addons.prepare(context.scene)
        except Exception as exc:
            flow.notice(getattr(exc, 'message', str(exc)))
        return self.begin(context, 760)

    def draw(self, context):
        self.track(context)
        layout = self.layout.mixar_surface(theme='ZEN', density='DEFAULT')
        layout.operator_context = 'INVOKE_DEFAULT'
        wm = context.window_manager
        layout.label(text='Turn your tool into someone else’s shortcut', icon='PLUGIN')
        if not addons.choices:
            box = layout.box()
            box.label(text='Make something worth sharing')
            message(box, 'Open the Add-on tab in Mixie and describe the tool you want to build. Your add-ons will be available here when their source package is ready.', 85, 3)
            draw_notice(layout, wm)
            return
        form = layout.column()
        form.enabled = not wm.moodboard_community_busy and wm.mixie_chat_is_logged_in
        form.prop(wm, 'community_addon_module')
        split = form.split(factor=.62)
        fields = split.column()
        fields.prop(wm, 'community_addon_title')
        fields.prop(wm, 'community_addon_description')
        row = fields.row(align=True)
        row.prop(wm, 'community_addon_version')
        row.prop(wm, 'community_addon_category')
        fields.prop(wm, 'community_addon_license')
        fields.separator()
        visibility(fields, wm, 'community_addon_visibility')
        package = split.column().box()
        package.label(text='Package contents', icon='PACKAGE')
        meta = addons.preview
        package.label(text=f"{len(meta.get('files', []))} files · {meta.get('size', 0) / 1024:.1f} KB ZIP")
        for item in meta.get('files', [])[:6]:
            message(package, item['name'].split('/', 1)[-1], 31, 1)
        if len(meta.get('files', [])) > 6:
            package.label(text=f"+ {len(meta['files']) - 6} more files")
        message(package, 'Only this add-on’s source, docs and images. Workspace history and other add-ons stay local.', 31, 4)
        form.separator()
        message(form, 'Publish only code and assets you have permission to share under the selected license.', 96, 2)
        row = form.row(align=True); row.scale_y = 1.3
        row.operator('mixar.addon_publish', text='Publish Add-on' if wm.community_addon_visibility == 'public' else 'Save Add-on', icon='EXPORT')
        if addons.saved_publication:
            row.operator('mixar.addon_new_publication', text='Save as New', icon='DUPLICATE')
        if not wm.mixie_chat_is_logged_in:
            layout.operator('mixie_chat.login', text='Sign in to publish', icon='USER')
        draw_link(layout, wm)
        draw_notice(layout, wm)


class MIXAR_OT_addon_publish(Operator):
    bl_idname = 'mixar.addon_publish'
    bl_label = 'Publish Add-on'

    @classmethod
    def poll(cls, context):
        return context.window_manager.mixie_chat_is_logged_in and not context.window_manager.moodboard_community_busy

    def execute(self, context):
        try:
            addons.publish()
        except Exception as exc:
            flow.notice(getattr(exc, 'message', str(exc)))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_addon_new_publication(Operator):
    bl_idname = 'mixar.addon_new_publication'
    bl_label = 'Save Add-on as New'

    def execute(self, context):
        if context.window_manager.moodboard_community_busy:
            return {'CANCELLED'}
        addons.remember(context.window_manager.community_addon_module, {})
        context.window_manager.moodboard_community_link = ''
        flow.notice('Ready to publish a separate copy')
        return {'FINISHED'}


class MIXAR_OT_community_back(Operator):
    bl_idname = 'mixar.community_back'
    bl_label = 'Back to Results'

    def execute(self, context):
        context.window_manager.moodboard_community_selected = -1
        return {'FINISHED'}


class MIXAR_OT_community_download(Operator, ExportHelper):
    bl_idname = 'mixar.community_download'
    bl_label = 'Download Add-on ZIP'
    bl_description = 'Save this source package to inspect or install from Preferences; does not run code'
    filename_ext = '.zip'
    filter_glob: StringProperty(default='*.zip', options={'HIDDEN'})
    index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return not context.window_manager.moodboard_community_busy

    def invoke(self, context, event):
        flow.sync_account()
        if not 0 <= self.index < len(flow.records):
            return {'CANCELLED'}
        record = flow.records[self.index]
        if record.get('kind') != 'addon':
            return {'CANCELLED'}
        self._record = dict(record)
        self._account = flow.identity()
        self.filepath = record['details']['module'] + '-' + record['details']['version'] + '.zip'
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        if not hasattr(self, '_record') or self._account != flow.identity():
            self.report({'ERROR'}, 'Reopen the add-on details before downloading')
            return {'CANCELLED'}
        record, destination = self._record, Path(self.filepath)
        def complete(data):
            if data.get('kind') != 'addon' or data.get('revision') != record['revision']:
                raise ValueError('This add-on changed. Refresh its details and download again')
            asset = next(a for a in data['assets'] if a['id'] == 'package')
            if len(asset['data']) > 23 * 1024 * 1024:
                raise ValueError('Add-on package is too large')
            raw = base64.b64decode(asset['data'], validate=True)
            if len(raw) > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != data['details']['sha256']:
                raise ValueError('Download verification failed. Please try again')
            if not zipfile.is_zipfile(io.BytesIO(raw)):
                raise ValueError('Invalid source package')
            try:
                with destination.open('xb') as handle:
                    handle.write(raw)
            except FileExistsError:
                raise ValueError('A file already exists there. Choose a new filename') from None
            flow.notice('ZIP downloaded. Install it from Preferences → Add-ons → Install from Disk when ready')
            # The file-selector operator is freed before this async callback.
            from mixar.modules.common.notifications import get_notification_store
            get_notification_store().push('success', 'Add-on ZIP downloaded',
                body='Install from Preferences → Add-ons → Install from Disk when ready.')
        path = record['id'] if record.get('id') else 'shared/' + record['token']
        flow.request('get', path, complete, message='Downloading add-on…')
        return {'FINISHED'}


class MIXAR_MT_community(Menu):
    bl_label = 'Community'

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator('mixie.moodboard_explore', text='Explore Moodboards', icon='IMAGE_DATA').kind = 'moodboard'
        layout.operator('mixie.moodboard_explore', text='Explore Add-ons', icon='PLUGIN').kind = 'addon'
        layout.separator()
        layout.operator('mixie.moodboard_share', text='Share this Moodboard', icon='URL')
        layout.operator('mixar.addon_share', text='Publish Add-on', icon='EXPORT')


def draw_community(self, context):
    self.layout.menu('MIXAR_MT_community')


classes = (MIXAR_OT_addon_share, MIXAR_OT_addon_publish, MIXAR_OT_addon_new_publication,
           MIXAR_OT_community_back, MIXAR_OT_community_download, MIXAR_MT_community)


def register():
    for cls in classes:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_community)


def unregister():
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_community)
    for cls in reversed(classes):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
