# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Session-only add-on publication form. Source paths never enter RNA."""
import bpy
from bpy.props import EnumProperty, StringProperty
from .sharing_props import VISIBILITY


def packages(_self, _context):
    from ...core.addon_publication import choices
    return choices


def selected(_self, _context):
    from ...core import addon_publication
    if not getattr(addon_publication, 'preparing', False):
        addon_publication.select()


def register():
    wm = bpy.types.WindowManager
    wm.community_addon_module = EnumProperty(name='Add-on', items=packages, update=selected, options={'SKIP_SAVE'})
    wm.community_addon_title = StringProperty(name='Title', maxlen=120, options={'SKIP_SAVE'})
    wm.community_addon_description = StringProperty(name='What does it do?', maxlen=2000, options={'SKIP_SAVE'})
    wm.community_addon_version = StringProperty(name='Version', default='1.0.0', maxlen=40, options={'SKIP_SAVE'})
    wm.community_addon_license = EnumProperty(name='License', items=[(v, v, '') for v in
        ('GPL-3.0-or-later', 'GPL-2.0-or-later', 'MIT', 'Apache-2.0', 'BSD-3-Clause')], options={'SKIP_SAVE'})
    wm.community_addon_category = EnumProperty(name='Category', items=[(v, v, '') for v in
        ('Modeling', 'Materials', 'Animation', 'Rendering', 'Workflow', 'Other')], default='Other', options={'SKIP_SAVE'})
    wm.community_addon_visibility = EnumProperty(name='Visibility', items=VISIBILITY, default='private', options={'SKIP_SAVE'})


def unregister():
    for field in ('module', 'title', 'description', 'version', 'license', 'category', 'visibility'):
        if hasattr(bpy.types.WindowManager, 'community_addon_' + field):
            delattr(bpy.types.WindowManager, 'community_addon_' + field)
