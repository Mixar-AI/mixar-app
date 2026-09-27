# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Session-only discovery data and project-owned publication identity."""
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

VISIBILITY = [('private', 'Private', 'Only you can open this cloud snapshot'),
              ('unlisted', 'Anyone with the link', 'Anyone who receives the link can view and copy'),
              ('public', 'Public in Explore', 'Everyone can discover, view and copy this board')]


def register():
    scene = bpy.types.Scene
    scene.moodboard_share_id = StringProperty()
    scene.moodboard_share_revision = IntProperty(default=0)
    scene.moodboard_share_title = StringProperty(name="Title", maxlen=120)
    scene.moodboard_share_description = StringProperty(name="Description", maxlen=2000)
    scene.moodboard_share_visibility = EnumProperty(name="Visibility", items=VISIBILITY, default='private')
    wm = bpy.types.WindowManager
    for name, label in [('notice', ''), ('link', 'Share link'), ('query', 'Search boards or creators'),
                        ('open_link', 'Moodboard link')]:
        setattr(wm, 'moodboard_community_' + name, StringProperty(name=label, options={'SKIP_SAVE'}))
    wm.moodboard_community_busy = BoolProperty(default=False, options={'SKIP_SAVE'})
    wm.moodboard_community_page = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.moodboard_community_more = BoolProperty(default=False, options={'SKIP_SAVE'})
    wm.moodboard_community_mode = EnumProperty(items=[('explore', 'Explore', ''), ('mine', 'My Boards', '')],
                                              default='explore', options={'SKIP_SAVE'})


def unregister():
    for owner, prefix, fields in (
        (bpy.types.Scene, 'moodboard_share_', ('id', 'revision', 'title', 'description', 'visibility')),
        (bpy.types.WindowManager, 'moodboard_community_', ('notice', 'link', 'query', 'open_link', 'busy', 'page', 'more', 'mode')),
    ):
        for field in fields:
            if hasattr(owner, prefix + field):
                delattr(owner, prefix + field)
