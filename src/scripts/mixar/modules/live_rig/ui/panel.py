# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""N-panel UI for Live Rig (webcam drive + multi-instance sync)."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from mixar.modules.live_rig.core.session import get_session


class MIXAR_PT_live_rig(Panel):
    bl_label = "Live Rig"
    bl_idname = "MIXAR_PT_live_rig"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mixar"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.window_manager, "mixar_live_rig", None)
        session = get_session()

        if settings is None:
            layout.label(text="Live Rig is not registered")
            return

        layout.prop(settings, "camera_index")
        row = layout.row(align=True)
        row.prop(settings, "room_id", text="Room")
        row.operator("mixar.live_rig_create_room", text="", icon='ADD')
        layout.prop(settings, "publish")

        row = layout.row(align=True)
        if session.active:
            row.operator("mixar.live_rig_stop", icon='PAUSE')
        else:
            row.operator("mixar.live_rig_start", icon='PLAY')

        if settings.status:
            layout.label(text=settings.status)
        if session.active:
            layout.label(text=f"Frames {session.frames} · Bones {session.applied_bones}")
            if session.last_error:
                layout.label(text=session.last_error, icon='ERROR')


classes = (MIXAR_PT_live_rig,)
