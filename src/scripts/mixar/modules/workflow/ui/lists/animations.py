# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""One clip per row: name, length, then compact NLA icon buttons.

Solo/mute/playing state is read live from the target's NLA data (draw only
reads); rows store names, never RNA.
"""
import bpy
from mixar.modules.common.i18n import iface_, tip_
from ...core import animation_catalog as catalog, animation_nla as nla


def _button(layout, op, icon, tooltip, enabled=True, **props):
    cell = layout.row(align=True)
    cell.enabled = enabled
    button = cell.operator(op, text='', icon=icon, emboss=False)
    for key, value in props.items():
        setattr(button, key, value)
    cell.mixar_tooltip(text=tooltip)


def playing_row(context, target, item):
    """Data-derived: the soloed track's strips, or the active action when a
    browser Play runs on it with nothing soloed."""
    window, scene = context.window, context.scene
    state = context.window_manager.mixar_animations
    if target is None or not nla.is_playing(window, scene, state):
        return False
    if nla.play_target(scene, state) != target:
        return False
    soloed = catalog.soloed_track(target)
    if item.kind == 'STRIP':
        return soloed is not None and soloed.name == item.track_name
    return item.kind == 'ACTION' and soloed is None


class MIXAR_UL_animations(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        target = context.scene.objects.get(data.target_name) if data.target_name else None
        anim = getattr(target, 'animation_data', None)
        track = anim.nla_tracks.get(item.track_name) if anim and item.track_name else None
        playing = playing_row(context, target, item)
        row = layout.row(align=True)
        title = item.action_name
        if item.slot_name:
            title += ' · ' + item.slot_name
        row.label(text=title, translate=False,
                  icon='PLAY' if playing else ('CHECKMARK' if item.used else 'ACTION'))
        fps = context.scene.render.fps / context.scene.render.fps_base
        length = row.row(align=True)
        length.ui_units_x = 2.2
        length.label(text=iface_("{seconds:.1f}s").format(
            seconds=max(0, item.end - item.start) / fps), translate=False)
        buttons = row.row(align=True)
        if item.kind == 'STRIP':
            strip = dict(track_name=item.track_name, strip_name=item.strip_name)
            alive = track is not None
            _button(buttons, 'mixar.animation_solo',
                    'SOLO_ON' if alive and track.is_solo else 'SOLO_OFF',
                    tip_("Solo the {track} track").format(track=item.track_name),
                    alive, **strip)
            _button(buttons, 'mixar.animation_mute',
                    'CHECKBOX_DEHLT' if alive and track.mute else 'CHECKBOX_HLT',
                    tip_("Mute the {track} track").format(track=item.track_name),
                    alive, **strip)
            _button(buttons, 'mixar.animation_delete', 'TRASH',
                    tip_("Delete the {strip} strip").format(strip=item.strip_name)
                    if not item.nested else tip_("This clip is inside a meta strip"),
                    alive and not item.nested, **strip)
        elif item.kind == 'FILE':
            _button(buttons, 'mixar.animation_add', 'ADD',
                    tip_("Add {animation} to the object as an NLA track").format(
                        animation=title),
                    not item.reason and target is not None,
                    action_name=item.action_name, slot_handle=item.slot_handle)
        _button(buttons, 'mixar.animation_play', 'PLAY',
                tip_("Play {animation}").format(animation=title), not item.reason,
                action_name=item.action_name, slot_handle=item.slot_handle,
                track_name=item.track_name, strip_name=item.strip_name)


classes = (MIXAR_UL_animations,)
