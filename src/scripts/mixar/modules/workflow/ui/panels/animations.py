# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from mixar.modules.common.i18n import iface_
from ...constants import BASIC_WORKSPACE_NAME
from ...core import animation_browser, animation_catalog, animation_nla as nla


def _playing_name(context, state):
    """What the transport shows, read from the NLA: the soloed track, else the
    target's active action."""
    target = nla.play_target(context.scene, state)
    if target is None:
        return ''
    soloed = animation_catalog.soloed_track(target)
    if soloed is not None:
        return soloed.name
    anim = target.animation_data
    return anim.action.name if anim and anim.action else ''


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
        animation_browser.bind(context)
        state = context.window_manager.mixar_animations
        target = animation_catalog.selected_target(context)
        target_name = target.name if target else ''
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        title = layout.row(align=True)
        title.label(text='Animations', icon='ACTION')
        title.operator('mixar.animation_refresh', text='', icon='FILE_REFRESH')
        layout.label(text=target_name or iface_('Select an object to see its animations'),
                     translate=False, icon='OUTLINER_OB_ARMATURE')
        layout.prop(state, 'scope', text='')
        layout.prop(state, 'search', text='', icon='VIEWZOOM')
        if state.loading:
            layout.label(text='Finding animations…', icon='TIME')
        if state.clips and (target or state.scope == 'ALL'):
            clips = layout.column()
            clips.enabled = bool(target and target_name == state.target_name)
            clips.template_list('MIXAR_UL_animations', '', state, 'clips',
                                 state, 'active_index', rows=min(6, len(state.clips)), maxrows=6)
            if 0 <= state.active_index < len(state.clips):
                self.draw_detail(layout, state.clips[state.active_index])
        elif not state.loading:
            if state.search:
                layout.label(text='No matching animations', icon='VIEWZOOM')
            elif target_name:
                layout.label(text='No animations assigned', icon='INFO')
                layout.label(text='Try All in file to find other clips.')
            else:
                layout.label(text='Select an object to see its clips.')
        rig = animation_catalog.hidable_rig(context)
        if rig is not None:
            hidden = rig.hide_get(view_layer=context.view_layer)
            layout.operator('mixar.animation_hide_rig', depress=hidden,
                            text='Show Rig' if hidden else 'Hide Rig',
                            icon='HIDE_ON' if hidden else 'HIDE_OFF')
        if nla.is_playing(context.window, context.scene, state):
            self.draw_transport(layout, context, state)

    @staticmethod
    def draw_detail(layout, clip):
        detail = layout.column()
        detail.label(text=clip.action_name, translate=False)
        if clip.reason:
            detail.label(text=iface_(clip.reason), translate=False, icon='INFO')
        elif clip.kind == 'STRIP':
            detail.label(text=iface_("NLA track: {track}").format(track=clip.track_name),
                         translate=False, icon='NLA')
        elif clip.kind == 'ACTION':
            detail.label(text='Active action', icon='ACTION')
        else:
            detail.label(text='Not on this object yet; Play or Add puts it on a new track',
                         icon='INFO')

    @staticmethod
    def draw_transport(layout, context, state):
        layout.separator()
        player = layout.box()
        player.label(text=iface_("Playing {animation}").format(
            animation=_playing_name(context, state)), translate=False, icon='PLAY')
        controls = player.row(align=True)
        controls.operator('mixar.animation_pause', text='',
                          icon='PAUSE' if context.screen.is_animation_playing else 'PLAY')
        controls.operator('mixar.animation_stop', icon='SNAP_FACE')
        player.prop(context.scene, 'playback_loop_mode', text='')
        player.prop(context.scene, 'frame_current', text='Frame')


classes = (MIXAR_PT_animations,)
