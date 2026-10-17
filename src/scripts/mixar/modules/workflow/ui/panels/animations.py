# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from mixar.modules.common.i18n import iface_
from ...constants import BASIC_WORKSPACE_NAME
from ...core import animation_catalog, animation_preview


class MIXAR_PT_animations(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = 'Animations'
    bl_options = {'HIDE_HEADER'}
    bl_ui_units_x = 18
    bl_order = -100

    @classmethod
    def poll(cls, context):
        return context.workspace and context.workspace.name == BASIC_WORKSPACE_NAME

    def draw(self, context):
        state = context.window_manager.mixar_animations
        session = animation_preview.current()
        target = session.target if session else animation_catalog.selected_target(context)
        target_name = target.name if target else ''
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        title = layout.row(align=True)
        title.label(text='Animations', icon='ACTION')
        title.operator('mixar.animation_refresh', text='', icon='FILE_REFRESH')
        layout.label(text=target_name or iface_('Select an object to preview'),
                     translate=False, icon='OUTLINER_OB_ARMATURE')
        layout.prop(state, 'scope', text='')
        layout.prop(state, 'search', text='', icon='VIEWZOOM')
        if state.error:
            layout.label(text='Preview failed. Try another clip.', icon='ERROR')
        if state.loading:
            layout.label(text='Finding animations…', icon='TIME')
        if state.clips and (target or state.scope == 'ALL'):
            clips = layout.column()
            clips.enabled = bool(target and target_name == state.target_name)
            clips.template_list('MIXAR_UL_animations', '', state, 'clips',
                                 state, 'active_index', rows=min(6, len(state.clips)), maxrows=6)
            if 0 <= state.active_index < len(state.clips):
                clip = state.clips[state.active_index]
                detail = layout.column()
                detail.label(text=clip.action_name, translate=False)
                if clip.reason:
                    detail.label(text=iface_(clip.reason), translate=False, icon='INFO')
                elif clip.used:
                    detail.label(text='Used in scene', icon='CHECKMARK')
        elif not state.loading:
            if state.search:
                layout.label(text='No matching animations', icon='VIEWZOOM')
            elif target_name:
                layout.label(text='No animations assigned', icon='INFO')
                layout.label(text='Try All in file to find other clips.')
            else:
                layout.label(text='Select an object to preview its clips.')
        if state.preview_name:
            layout.separator()
            player = layout.box()
            player.label(text='Preparing preview…' if state.preparing else 'Previewing',
                         icon='TIME' if state.preparing else 'PLAY')
            player.label(text=state.preview_name, translate=False)
            controls = player.row(align=True)
            pause = controls.row(align=True)
            pause.enabled = not state.preparing
            pause.operator('mixar.animation_pause', text='',
                           icon='PAUSE' if state.playing else 'PLAY')
            controls.prop(state, 'loop', toggle=True)
            controls.operator('mixar.animation_stop', icon='SNAP_FACE')
            if session and session.target.type == 'ARMATURE':
                visibility = player.row()
                visibility.enabled = not state.preparing
                visibility.prop(state, 'hide_rig', toggle=True,
                                icon='HIDE_ON' if state.hide_rig else 'HIDE_OFF')
            scrub = player.row()
            scrub.enabled = not state.preparing
            scrub.prop(state, 'position', text='Position', slider=True)
            player.label(text='Preview only · your scene is unchanged')


classes = (MIXAR_PT_animations,)
