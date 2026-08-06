# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simple directing controls over native Blender camera/output properties."""

import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ...constants import ASPECT_PRESETS
from ...core.shot_api import active_shot, refresh_manifest
from ...core.viewport import enter_precise_mode, invoke_walk


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


def _draw_walk_aim(region_pointer):
    """Draw a clear aim marker while the pointer is hidden by walk mode."""
    region = bpy.context.region
    if region is None or region.as_pointer() != region_pointer:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    from math import cos, sin, tau

    center_x = region.width * 0.5
    center_y = region.height * 0.5
    radius = 9.0
    ring = [
        (
            center_x + cos(tau * step / 32) * radius,
            center_y + sin(tau * step / 32) * radius,
        )
        for step in range(33)
    ]
    gap = radius - 4.0
    reach = radius + 5.0
    ticks = [
        (center_x + gap, center_y), (center_x + reach, center_y),
        (center_x - gap, center_y), (center_x - reach, center_y),
        (center_x, center_y + gap), (center_x, center_y + reach),
        (center_x, center_y - gap), (center_x, center_y - reach),
    ]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    shader.uniform_float("color", (0.25, 0.92, 0.52, 0.9))
    batch_for_shader(shader, 'LINE_STRIP', {"pos": ring}).draw(shader)
    batch_for_shader(shader, 'LINES', {"pos": ticks}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


class MIXAR_OT_director_navigate(Operator):
    """Rough-in the camera with Blender's native WASD walk navigation"""

    bl_idname = "mixar.director_navigate"
    bl_label = "Navigate"
    bl_description = (
        "Move the camera with WASD and mouse; click to confirm, Esc to stop"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def invoke(self, context, _event):
        shot = _editable_shot(context)
        context.scene.mixar_director.navigation_mode = 'NAVIGATE'
        try:
            result, target = invoke_walk(context, shot.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        window, area, region, _space = target
        if 'RUNNING_MODAL' not in result or window != context.window:
            # Walk refused to start, or runs in another window where this
            # operator's modal handler would never receive events.
            return result
        self._window = window
        self._area = area
        self._region = region
        self._camera = shot.camera
        self._exit_pose = None
        self._start_pose = (
            shot.camera.matrix_world.copy(),
            float(shot.camera.data.lens),
        )
        self._timer = context.window_manager.event_timer_add(
            0.05, window=window,
        )
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_walk_aim, (region.as_pointer(),), 'WINDOW', 'POST_PIXEL',
        )
        context.window_manager.modal_handler_add(self)
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self._walk_running():
            if event.type == 'ESC' and event.value == 'PRESS':
                # Native walk cancel snaps the camera back to where the walk
                # began. Directors expect Esc to simply stop here, so keep
                # this pose and re-apply it after walk's revert.
                self._exit_pose = (
                    self._camera.matrix_world.copy(),
                    float(self._camera.data.lens),
                )
            return {'PASS_THROUGH'}
        self._finish(context)
        self._auto_capture(context)
        return {'FINISHED'}

    def cancel(self, context):
        self._exit_pose = None
        self._finish(context, reset_cursor=False)

    def _auto_capture(self, context) -> None:
        """Capture a keyframe for the completed move when Auto Key is on."""
        state = getattr(context.scene, "mixar_director", None)
        if state is None or not state.auto_key or not state.is_directing:
            return
        shot = _editable_shot(context)
        if shot is None or shot.camera != self._camera:
            return
        start_matrix, start_lens = self._start_pose
        moved = abs(float(self._camera.data.lens) - start_lens) > 1e-3 or any(
            abs(start_matrix[row][col] - self._camera.matrix_world[row][col]) > 1e-5
            for row in range(4)
            for col in range(4)
        )
        if not moved:
            return
        try:
            from ...core.capture import capture_beat

            beat = capture_beat(context, shot, state.beat_seconds)
        except Exception as exc:
            self.report({'WARNING'}, f"Auto Key could not capture: {exc}")
            return
        self.report({'INFO'}, f"Auto keyframe at frame {beat.frame}")

    def _walk_running(self) -> bool:
        modal_operators = getattr(self._window, "modal_operators", None)
        if modal_operators is None:
            return False
        try:
            return modal_operators.get("VIEW3D_OT_walk") is not None
        except (AttributeError, ReferenceError):
            return False

    def _finish(self, context, *, reset_cursor: bool = True) -> None:
        if self._exit_pose is not None:
            matrix, lens = self._exit_pose
            self._camera.matrix_world = matrix
            self._camera.data.lens = lens
            self._exit_pose = None
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._draw_handle, 'WINDOW',
            )
            self._draw_handle = None
        if reset_cursor:
            # The pointer reappears wherever walk grabbed it, which is often
            # off in a corner; hand it back in the middle of the frame.
            try:
                self._window.cursor_warp(
                    self._region.x + self._region.width // 2,
                    self._region.y + self._region.height // 2,
                )
            except (AttributeError, ReferenceError):
                pass
        try:
            self._area.tag_redraw()
        except (AttributeError, ReferenceError):
            pass


class MIXAR_OT_director_block_input(Operator):
    """Absorb object-editing shortcuts while the Director surface is active"""

    bl_idname = "mixar.director_block_input"
    bl_label = "Director Shortcut Guard"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def invoke(self, _context, _event):
        return {'FINISHED'}

    def execute(self, _context):
        return {'FINISHED'}


class MIXAR_OT_director_precise(Operator):
    """Select the shot camera for native gizmo-based adjustment"""

    bl_idname = "mixar.director_precise"
    bl_label = "Precise"
    bl_description = "Adjust the camera with Blender's transform gizmos"

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def execute(self, context):
        shot = _editable_shot(context)
        context.scene.mixar_director.navigation_mode = 'PRECISE'
        try:
            enter_precise_mode(context, shot.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_set_lens(Operator):
    """Apply a familiar focal-length preset to the active shot camera"""

    bl_idname = "mixar.director_set_lens"
    bl_label = "Set Lens"
    bl_options = {'REGISTER', 'UNDO'}

    lens_mm: IntProperty(name="Lens", default=35, min=1, max=500)

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        shot.camera.data.lens = self.lens_mm
        if shot.beats:
            refresh_manifest(context.scene, shot)
        return {'FINISHED'}


class MIXAR_OT_director_set_aspect(Operator):
    """Apply a director-facing aspect preset to native render settings"""

    bl_idname = "mixar.director_set_aspect"
    bl_label = "Set Aspect"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Aspect",
        items=tuple(
            (key, values[0], f"Set {values[0]} output", index)
            for index, (key, values) in enumerate(ASPECT_PRESETS.items())
        ),
        default="WIDE",
    )

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        _label, width, height = ASPECT_PRESETS[self.preset]
        render = context.scene.render
        render.resolution_x = width
        render.resolution_y = height
        render.pixel_aspect_x = 1.0
        render.pixel_aspect_y = 1.0
        if shot.beats:
            refresh_manifest(context.scene, shot)
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_navigate,
    MIXAR_OT_director_precise,
    MIXAR_OT_director_block_input,
    MIXAR_OT_director_set_lens,
    MIXAR_OT_director_set_aspect,
)

