# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fail-open analytics bridge for the native drawer's deliberate toggle."""

from bpy.types import Operator


class MIXIE_CHAT_OT_track_scene_drawer_open(Operator):
    bl_idname = 'mixie_chat.track_scene_drawer_open'
    bl_label = 'Track Scenes Drawer Open'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        try:
            from mixar.modules.common.analytics.essential_events import capture_scene_drawer_open
            capture_scene_drawer_open(context)
        except Exception:
            pass
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_track_scene_drawer_open,)
