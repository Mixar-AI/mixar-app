# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Animation browser buttons. Each data change is one REGISTER|UNDO operator
over ``core.animation_nla`` (Blender's NLA data API and screen operators)."""
import bpy
from bpy.props import IntProperty, StringProperty

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import rpt_, tip_
from ...constants import BASIC_WORKSPACE_NAME
from ...core import animation_browser as browser
from ...core import animation_catalog as catalog
from ...core import animation_nla as nla

_logger = get_logger(__name__)
_EDIT = {'REGISTER', 'UNDO', 'INTERNAL'}


def _ready(cls, context):
    """Shared poll: Zen, Object Mode, no render job, no running agent turn."""
    if bpy.app.is_job_running('RENDER'):
        cls.poll_message_set(tip_("Wait for the render to finish"))
        return False
    if (getattr(context.scene, 'mixie_chat_is_busy', False)
            or getattr(context.scene, 'mixie_run_open', False)):
        cls.poll_message_set(tip_("Wait for the agent to finish"))
        return False
    if context.mode != 'OBJECT':
        cls.poll_message_set(tip_("Switch to Object Mode to play animations"))
        return False
    return bool(context.workspace and context.workspace.name == BASIC_WORKSPACE_NAME)


class _Edit:
    """Run one NLA change as one undo step.

    ``ValueError`` is a refusal raised before any data changes, so it cancels.
    A Blender error after a change began still finishes, so the partial change
    is an undo step the user can revert rather than a hidden mutation.
    """

    def run(self, context, change):
        try:
            change()
        except ValueError as exc:
            self.report({'WARNING'}, rpt_("Could not change animation: {reason}").format(
                reason=rpt_(str(exc))))
            return {'CANCELLED'}
        except (RuntimeError, ReferenceError) as exc:
            _logger.warning('Animation browser change failed: %s', exc)
            self.report({'ERROR'}, rpt_("Could not change animation: {reason}").format(
                reason=str(exc)))
        finally:
            browser.invalidate()
            if context.window is not None:
                # Solo/mute icons are read live; redraw the open browser.
                context.window.mixar_refresh_popover("MIXAR_PT_animations")
        return {'FINISHED'}


class _Clip(_Edit):
    action_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    slot_handle: IntProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def clip(self):
        action = bpy.data.actions.get(self.action_name)
        return action, catalog.resolve(action, self.slot_handle)


class _Strip(_Edit):
    track_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    strip_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _ready(cls, context)


class MIXAR_OT_animation_refresh(bpy.types.Operator):
    bl_idname = 'mixar.animation_refresh'
    bl_label = 'Refresh Animations'
    bl_description = 'Refresh animations after importing or editing clips'

    def execute(self, context):
        browser.invalidate()
        return {'FINISHED'}


class MIXAR_OT_animation_play(_Clip, bpy.types.Operator):
    bl_idname = 'mixar.animation_play'
    bl_label = 'Play Animation'
    bl_description = 'Solo this clip in the NLA and play it in its own frame range'
    bl_options = _EDIT
    track_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    strip_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return tip_("Play {animation}").format(animation=properties.action_name)

    @classmethod
    def poll(cls, context):
        return _ready(cls, context)

    def execute(self, context):
        def change():
            action, slot = self.clip()
            nla.play(context.window, context.scene, context.window_manager.mixar_animations,
                     catalog.selected_target(context), action, slot,
                     self.track_name, self.strip_name)
        return self.run(context, change)


class MIXAR_OT_animation_add(_Clip, bpy.types.Operator):
    bl_idname = 'mixar.animation_add'
    bl_label = 'Add to Object'
    bl_description = 'Add this clip to the object as a new NLA track'
    bl_options = _EDIT

    @classmethod
    def description(cls, context, properties):
        return tip_("Add {animation} to the object as an NLA track").format(
            animation=properties.action_name)

    @classmethod
    def poll(cls, context):
        return _ready(cls, context)

    def execute(self, context):
        def change():
            action, slot = self.clip()
            nla.add(catalog.selected_target(context), action, slot)
        return self.run(context, change)


class MIXAR_OT_animation_solo(_Strip, bpy.types.Operator):
    bl_idname = 'mixar.animation_solo'
    bl_label = 'Solo Track'
    bl_description = "Evaluate only this NLA track, like the NLA editor's star"
    bl_options = _EDIT

    @classmethod
    def description(cls, context, properties):
        return tip_("Solo the {track} track").format(track=properties.track_name)

    def execute(self, context):
        return self.run(context, lambda: nla.toggle_solo(
            catalog.selected_target(context), self.track_name, self.strip_name))


class MIXAR_OT_animation_mute(_Strip, bpy.types.Operator):
    bl_idname = 'mixar.animation_mute'
    bl_label = 'Mute Track'
    bl_description = 'Turn this NLA track off or on'
    bl_options = _EDIT

    @classmethod
    def description(cls, context, properties):
        return tip_("Mute the {track} track").format(track=properties.track_name)

    def execute(self, context):
        return self.run(context, lambda: nla.toggle_mute(
            catalog.selected_target(context), self.track_name, self.strip_name))


class MIXAR_OT_animation_delete(_Strip, bpy.types.Operator):
    bl_idname = 'mixar.animation_delete'
    bl_label = 'Delete Strip'
    bl_description = 'Delete this NLA strip, and its track if it becomes empty'
    bl_options = _EDIT

    @classmethod
    def description(cls, context, properties):
        return tip_("Delete the {strip} strip").format(strip=properties.strip_name)

    def execute(self, context):
        return self.run(context, lambda: nla.delete(
            catalog.selected_target(context), self.track_name, self.strip_name))


class MIXAR_OT_animation_stop(_Edit, bpy.types.Operator):
    bl_idname = 'mixar.animation_stop'
    bl_label = 'Stop Animation'
    bl_description = 'Stop playback, clear the solo and restore the preview range'
    bl_options = _EDIT

    @classmethod
    def poll(cls, context):
        return bool(context.window) and nla.is_playing(
            context.window, context.scene, context.window_manager.mixar_animations)

    def execute(self, context):
        return self.run(context, lambda: nla.stop(
            context.window, context.scene, context.window_manager.mixar_animations))


class MIXAR_OT_animation_pause(bpy.types.Operator):
    bl_idname = 'mixar.animation_pause'
    bl_label = 'Play / Pause Animation'
    bl_description = 'Pause or resume playback'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return MIXAR_OT_animation_stop.poll(context)

    def execute(self, context):
        nla.pause(context.window)
        context.window.mixar_refresh_popover("MIXAR_PT_animations")
        return {'FINISHED'}


class MIXAR_OT_animation_hide_rig(bpy.types.Operator):
    bl_idname = 'mixar.animation_hide_rig'
    bl_label = 'Hide Rig'
    bl_description = 'Hide or show the rig; the character keeps deforming'
    bl_options = _EDIT

    @classmethod
    def poll(cls, context):
        return _ready(cls, context) and catalog.hidable_rig(context) is not None

    def execute(self, context):
        nla.toggle_rig_visibility(catalog.hidable_rig(context), context.view_layer)
        context.window.mixar_refresh_popover("MIXAR_PT_animations")
        return {'FINISHED'}


classes = (MIXAR_OT_animation_refresh, MIXAR_OT_animation_play, MIXAR_OT_animation_add,
           MIXAR_OT_animation_solo, MIXAR_OT_animation_mute, MIXAR_OT_animation_delete,
           MIXAR_OT_animation_stop, MIXAR_OT_animation_pause, MIXAR_OT_animation_hide_rig)
