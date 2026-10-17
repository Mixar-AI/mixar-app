# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import IntProperty, StringProperty

from mixar.modules.common.i18n import rpt_, tip_
from ...constants import BASIC_WORKSPACE_NAME
from ...core import animation_browser as browser, animation_preview as preview


class MIXAR_OT_animations_open(bpy.types.Operator):
    bl_idname = 'mixar.animations_open'
    bl_label = 'Animations'
    bl_description = 'Browse and preview animations without leaving Zen Mode'

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'VIEW_3D'
                and context.workspace.name == BASIC_WORKSPACE_NAME)

    def execute(self, context):
        browser.open_browser(context)
        bpy.ops.wm.call_panel('INVOKE_DEFAULT', name='MIXAR_PT_animations', keep_open=True)
        return {'FINISHED'}


class MIXAR_OT_animation_refresh(bpy.types.Operator):
    bl_idname = 'mixar.animation_refresh'
    bl_label = 'Refresh Animations'
    bl_description = 'Refresh animations after importing or editing clips'

    def execute(self, context):
        browser.invalidate()
        return {'FINISHED'}


class MIXAR_OT_animation_preview(bpy.types.Operator):
    bl_idname = 'mixar.animation_preview'
    bl_label = 'Preview Animation'
    bl_description = 'Play this animation in a temporary copy; your project stays unchanged'
    action_name: StringProperty(options={'SKIP_SAVE'})
    slot_handle: IntProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return tip_("Preview {animation} without changing your scene").format(
            animation=properties.action_name)

    @classmethod
    def poll(cls, context):
        if bpy.app.is_job_running('RENDER'):
            cls.poll_message_set('Wait for the render to finish')
            return False
        scene = preview.current().source if preview.current() else context.scene
        if (getattr(scene, 'mixie_chat_is_busy', False)
                or getattr(scene, 'mixie_run_open', False)):
            cls.poll_message_set('Wait for the agent to finish')
            return False
        if context.mode != 'OBJECT':
            cls.poll_message_set('Switch to Object Mode to preview animations')
            return False
        return context.workspace.name == BASIC_WORKSPACE_NAME

    def execute(self, context):
        previous = preview.current()
        try:
            preview.start(context, self.action_name, self.slot_handle)
            bpy.ops.mixar.animation_preview_controls('INVOKE_DEFAULT')
        except (ValueError, RuntimeError, ReferenceError) as exc:
            if preview.current() is not previous:
                preview.stop()
            self.report({'WARNING'}, rpt_("Could not preview animation: {reason}").format(
                reason=rpt_(str(exc))))
            browser.invalidate()
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_animation_stop(bpy.types.Operator):
    bl_idname = 'mixar.animation_stop'
    bl_label = 'Stop Preview'
    bl_description = 'Return to your scene and its original animation'

    @classmethod
    def poll(cls, context):
        return preview.current() is not None

    def execute(self, context):
        preview.stop()
        browser.invalidate()
        return {'FINISHED'}


class MIXAR_OT_animation_pause(bpy.types.Operator):
    bl_idname = 'mixar.animation_pause'
    bl_label = 'Play / Pause Preview'

    @classmethod
    def poll(cls, context):
        return preview.current() is not None and preview.current().ready

    def execute(self, context):
        preview.pause()
        return {'FINISHED'}


class MIXAR_OT_animation_preview_controls(bpy.types.Operator):
    bl_idname = 'mixar.animation_preview_controls'
    bl_label = 'Animation Preview Controls'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self.session = preview.current()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        session = preview.current()
        if session is None or session is not self.session:
            return {'FINISHED'}
        if event.value != 'PRESS':
            return {'PASS_THROUGH'}
        # This modal was installed by a popover button and can run before the
        # popup handler. Let the live browser own text entry and its first Esc.
        if session.window.mixar_refresh_popover('MIXAR_PT_animations'):
            return {'PASS_THROUGH'}
        if event.type == 'SPACE':
            preview.pause()
            return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            preview.stop()
            return {'FINISHED'}
        if event.type == 'Z' and (event.ctrl or event.oskey):
            preview.stop()
            # Per-tab undo refuses internal scenes before undo_pre runs.
            # Restore the source first, then invoke the real undo/redo operator.
            region = next(r for r in session.area.regions if r.type == 'WINDOW')
            with context.temp_override(window=session.window, area=session.area, region=region):
                if event.shift:
                    bpy.ops.ed.redo()
                else:
                    bpy.ops.ed.undo()
            return {'FINISHED'}
        # Navigation remains native. Editing shortcuts first return to the
        # project, so Add/Delete/G/etc cannot create disposable user edits.
        navigation = {'MIDDLEMOUSE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
                      'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
                      'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL',
                      'LEFT_ALT', 'RIGHT_ALT', 'OSKEY', 'NDOF_MOTION'}
        if event.type in navigation or event.type.startswith('NUMPAD'):
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE':
            # Keep the preview's transport/browser interactive. Menus outside
            # the viewport (File/Edit/etc) operate on the original document.
            if (session.area.x <= event.mouse_x < session.area.x + session.area.width
                    and session.area.y <= event.mouse_y < session.area.y + session.area.height):
                return {'PASS_THROUGH'}
        if event.type not in {'TIMER', 'WINDOW_DEACTIVATE'}:
            preview.stop()
            return {'FINISHED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}


classes = (MIXAR_OT_animations_open, MIXAR_OT_animation_refresh,
           MIXAR_OT_animation_preview, MIXAR_OT_animation_stop, MIXAR_OT_animation_pause,
           MIXAR_OT_animation_preview_controls)
