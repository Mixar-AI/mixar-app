# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Session-only discovery data and project-owned publication identity."""
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

VISIBILITY = [('private', 'Private', 'Only you can open this cloud snapshot'),
              ('unlisted', 'Anyone with the link', 'Anyone who receives the link can view and copy'),
              ('public', 'Public in Explore', 'Everyone can discover, view and copy this board')]


def resort(_self, _context):
    from ...core import sharing_flow
    sharing_flow.load(page=0)


def register():
    scene = bpy.types.Scene
    scene.moodboard_share_id = StringProperty()
    scene.moodboard_share_revision = IntProperty(default=0)
    scene.moodboard_share_title = StringProperty(name="Title", maxlen=120)
    scene.moodboard_share_description = StringProperty(name="Description", maxlen=2000)
    scene.moodboard_share_visibility = EnumProperty(name="Visibility", items=VISIBILITY, default='private')
    wm = bpy.types.WindowManager
    for name, label in [('notice', ''), ('link', 'Share link'), ('query', 'Search titles, descriptions or creators'),
                        ('open_link', 'Community link')]:
        setattr(wm, 'moodboard_community_' + name, StringProperty(name=label, options={'SKIP_SAVE'}))
    wm.moodboard_community_kind = EnumProperty(items=[('moodboard', 'Moodboards', ''), ('addon', 'Add-ons', '')], default='moodboard', options={'SKIP_SAVE'})
    wm.moodboard_community_sort = EnumProperty(name='Sort', items=[('newest', 'Newest first', ''), ('updated', 'Recently updated', ''), ('title', 'Title A–Z', '')], default='newest', update=resort, options={'SKIP_SAVE'})
    wm.moodboard_community_selected = IntProperty(default=-1, options={'SKIP_SAVE'})
    wm.moodboard_community_total = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.moodboard_community_busy = BoolProperty(default=False, options={'SKIP_SAVE'})
    wm.moodboard_community_page = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.moodboard_community_more = BoolProperty(default=False, options={'SKIP_SAVE'})
    wm.moodboard_community_mode = EnumProperty(items=[('explore', 'Explore', ''), ('mine', 'My Boards', '')],
                                              default='explore', options={'SKIP_SAVE'})


def unregister():
    for owner, prefix, fields in (
        (bpy.types.Scene, 'moodboard_share_', ('id', 'revision', 'title', 'description', 'visibility')),
        (bpy.types.WindowManager, 'moodboard_community_', ('notice', 'link', 'query', 'open_link', 'busy', 'page', 'more', 'mode', 'kind', 'sort', 'selected', 'total')),
    ):
        for field in fields:
            if hasattr(owner, prefix + field):
                delattr(owner, prefix + field)
