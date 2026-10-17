# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from mixar.modules.common.i18n import iface_, tip_


class MIXAR_UL_animations(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        title = item.action_name
        if item.slot_name:
            title += ' · ' + item.slot_name
        row.label(text=title, translate=False,
                  icon='CHECKMARK' if item.used else 'ACTION')
        fps = context.scene.render.fps / context.scene.render.fps_base
        row.label(text=iface_("{seconds:.1f}s").format(
            seconds=max(0, item.end - item.start) / fps), translate=False)
        play = row.row(align=True)
        play.enabled = not item.reason
        op = play.operator('mixar.animation_preview', text='', icon='PLAY')
        op.action_name = item.action_name
        op.slot_handle = item.slot_handle
        play.mixar_tooltip(text=tip_("Preview {animation}; Stop restores the original animation").format(
            animation=title))


classes = (MIXAR_UL_animations,)
