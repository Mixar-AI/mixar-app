# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simple directing controls over native Blender camera/output properties."""

import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ...constants import ASPECT_PRESETS
from ...core.aspect import apply_ratio, remember_camera_ratio
from ...core.shot_api import active_shot, refresh_manifest
from ...core.viewport import (
    NATIVE_WALK_OPERATOR,
    WALK_OPERATOR,
    enter_camera_view,
    enter_precise_mode,
    invoke_explore_walk,
    invoke_walk,
    set_walk_active,
)


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


# The walk-aim overlay's handle, module-level like `track_pick_overlay`'s. It
# used to live only on the operator instance, so a supervisor that never reached
# _finish -- a file load ending the modal, an exception -- left the handler
# installed with nothing able to reach it, and the next walk stacked another.
# The stale one keeps drawing against a dead region pointer, which a recycled
# address turns into a reticle painted forever.
_walk_draw_handle = None


def _remove_walk_aim() -> None:
    """Drop the overlay if one is installed. Safe to call any number of times."""
    global _walk_draw_handle
    if _walk_draw_handle is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_walk_draw_handle, 'WINDOW')
    except (ValueError, ReferenceError, RuntimeError):
        pass  # already gone with its space type
    _walk_draw_handle = None


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
    # The shader must be bound before a uniform is pushed, otherwise the
    # reticle draws with whatever colour the previous shader left behind.
    shader.bind()
    shader.uniform_float("color", (0.25, 0.92, 0.52, 0.9))
    batch_for_shader(shader, 'LINE_STRIP', {"pos": ring}).draw(shader)
    batch_for_shader(shader, 'LINES', {"pos": ticks}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


class _WalkSupervisor:
    """Shared modal supervision around a running native walk session.

    Native walk grabs and HIDES the pointer for its whole run; when it dies
    the pointer reappears wherever the OS physically left it — after a lot
    of mouse steering that can be anywhere, including outside the window,
    and it stays invisible until wiggled. Supervision fixes the exit for
    every walk the Director starts: an aim reticle marks the focus while
    the pointer is hidden, Esc stops Explore in place instead of Blender
    walk's native snap-back (the pose captured at the Esc press is
    re-applied after walk's revert), and the cursor is warped back to the
    middle of the viewport on every exit so it is always visible and where
    the eye is.

    Subclasses declare WHICH walk they supervise: Navigate drives the shot
    camera through the Cinema walk, Explore free-flies the viewport with
    Blender's own. Watching the wrong id reads as "the walk already ended"
    on the first modal event, so the supervisor cleans up and returns
    FINISHED while the walk it was supervising is still flying.
    """

    #: Overridden by Explore. Not a constructor argument: Blender builds
    #: operator instances itself.
    _walk_operator = WALK_OPERATOR
    #: Does Esc end the walk being supervised? Blender's own walk (Explore)
    #: cancels on it; the Cinema walk (Navigate) does not — its Walk chip is
    #: the one switch. Snapshotting a pose on an Esc that ends nothing would
    #: re-apply that stale pose whenever the chip later stops the walk,
    #: throwing away everything driven since.
    _esc_stops_walk = False

    def _supervise(self, context, window, area, region) -> None:
        self._window = window
        self._area = area
        self._region = region
        self._exit_pose = None
        self._timer = context.window_manager.event_timer_add(
            0.05, window=window,
        )
        global _walk_draw_handle
        _remove_walk_aim()  # a previous supervisor that never reached _finish
        _walk_draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_walk_aim, (region.as_pointer(),), 'WINDOW', 'POST_PIXEL',
        )
        self._draw_handle = _walk_draw_handle
        context.window_manager.modal_handler_add(self)
        set_walk_active(context, True)
        area.tag_redraw()

    def modal(self, context, event):
        if self._walk_running():
            if self._esc_stops_walk and event.type == 'ESC' and event.value == 'PRESS':
                # Native walk cancel snaps back to where the walk began.
                # Directors expect Esc to simply stop here, so keep this
                # pose and re-apply it after walk's revert.
                self._exit_pose = self._snapshot_exit_pose()
            return {'PASS_THROUGH'}
        self._finish(context)
        self._on_walk_finished(context)
        return {'FINISHED'}

    def cancel(self, context):
        self._exit_pose = None
        self._finish(context, reset_cursor=False)

    def _snapshot_exit_pose(self):
        raise NotImplementedError

    def _apply_exit_pose(self, pose) -> None:
        raise NotImplementedError

    def _on_walk_finished(self, _context) -> None:
        pass

    def _walk_running(self) -> bool:
        return _walk_running_in(self._window, self._walk_operator)

    def _finish(self, context, *, reset_cursor: bool = True) -> None:
        if self._exit_pose is not None:
            self._apply_exit_pose(self._exit_pose)
            self._exit_pose = None
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._draw_handle is not None:
            _remove_walk_aim()
            self._draw_handle = None
        # `lock_camera` is NOT released here. It is the Cinema Mode contract
        # now — "Lock Camera to View" stays on for the session, because the
        # camera is what the director is moving — and walk only borrowed
        # something the mode already holds.
        set_walk_active(context, False)
        if reset_cursor:
            # The pointer reappears wherever the OS left it — often off in
            # a corner or outside the window; hand it back in the middle of
            # the frame where it is visible and useful.
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


def _walk_running_in(window, operator: str = WALK_OPERATOR) -> bool:
    modal_operators = getattr(window, "modal_operators", None)
    if modal_operators is None:
        return False
    try:
        return modal_operators.get(operator) is not None
    except (AttributeError, ReferenceError):
        return False


class MIXAR_OT_director_navigate(_WalkSupervisor, Operator):
    bl_idname = "mixar.director_navigate"
    bl_label = "Navigate"
    bl_description = (
        "Walk the camera with WASD; hold the left mouse button to look, Shift "
        "to sprint, Alt to creep. Click again to stop"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def invoke(self, context, _event):
        state = context.scene.mixar_director
        if _walk_running_in(context.window):
            # The chip is a TOGGLE and always was, in everything but its
            # behaviour: it paints lit while walking and publishes "stop" to
            # the QA harness. Starting a second walk on top of the first is
            # what it actually did — two modals both eating WASD, and Esc
            # stopping only the top one. It was unreachable while the walk
            # owned every event in the window; it stopped being unreachable
            # the moment the surface became clickable during a walk.
            state.walk_stop_requested = True
            return {'FINISHED'}
        shot = _editable_shot(context)
        state.navigation_mode = 'NAVIGATE'
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
        self._camera = shot.camera
        self._start_pose = (
            shot.camera.matrix_world.copy(),
            float(shot.camera.data.lens),
        )
        self._supervise(context, window, area, region)
        return {'RUNNING_MODAL'}

    def _snapshot_exit_pose(self):
        return (
            self._camera.matrix_world.copy(),
            float(self._camera.data.lens),
        )

    def _apply_exit_pose(self, pose) -> None:
        matrix, lens = pose
        self._camera.matrix_world = matrix
        self._camera.data.lens = lens

    def _on_walk_finished(self, context) -> None:
        self._auto_capture(context)

    def _auto_capture(self, context) -> None:
        """Capture a keyframe for the completed move when Auto Key is on."""
        state = getattr(context.scene, "mixar_director", None)
        if state is None or not state.auto_key or not state.is_directing:
            return
        if getattr(getattr(context, "screen", None), "is_animation_playing", False):
            return  # The recorder owns the running take; never render a still here.
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

            beat = capture_beat(
                context, shot, state.beat_seconds, replace_existing=True
            )
        except Exception as exc:
            self.report({'WARNING'}, f"Auto Key could not capture: {exc}")
            return
        self.report({'INFO'}, f"Auto keyframe at frame {beat.frame}")


class MIXAR_OT_director_explore(_WalkSupervisor, Operator):
    """Fly the scene freely without moving the shot camera"""

    bl_idname = "mixar.director_explore"
    bl_label = "Explore"
    # Explore flies the VIEWPORT with Blender's own walk, not the camera
    # with the Cinema one — and that walk's Esc cancels, snapping back.
    _walk_operator = NATIVE_WALK_OPERATOR
    _esc_stops_walk = True
    bl_description = (
        "Leave the camera view and fly the scene with WASD and the mouse; "
        "frame a spot, then Add Camera Here starts a new shot there"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def invoke(self, context, _event):
        context.scene.mixar_director.navigation_mode = 'EXPLORE'
        try:
            result, target = invoke_explore_walk(context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        window, area, region, space = target
        if 'RUNNING_MODAL' not in result or window != context.window:
            # Walk refused to start (the free view is still usable with
            # ordinary navigation), or runs in another window where this
            # operator's modal handler would never receive events.
            return result
        self._region_3d = space.region_3d
        self._supervise(context, window, area, region)
        self.report(
            {'INFO'}, "Exploring — frame a view, then Add Camera Here"
        )
        return {'RUNNING_MODAL'}

    def _snapshot_exit_pose(self):
        region_3d = self._region_3d
        return (
            region_3d.view_location.copy(),
            region_3d.view_rotation.copy(),
            float(region_3d.view_distance),
        )

    def _apply_exit_pose(self, pose) -> None:
        location, rotation, distance = pose
        try:
            self._region_3d.view_location = location
            self._region_3d.view_rotation = rotation
            self._region_3d.view_distance = distance
        except ReferenceError:
            pass


class MIXAR_OT_director_return_to_shot(Operator):
    """Snap the viewport back to the active shot camera"""

    bl_idname = "mixar.director_return_to_shot"
    bl_label = "Back to Shot"
    bl_description = (
        "Stop exploring and return to the active shot camera's view"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        if not (state and state.is_directing):
            return False
        shot = active_shot(context.scene)
        return bool(shot is not None and shot.camera is not None)

    def execute(self, context):
        shot = active_shot(context.scene)
        try:
            # enter_camera_view flips EXPLORE back to NAVIGATE itself.
            enter_camera_view(context, shot.camera, remember=False)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_block_input(Operator):
    """Absorb object-editing shortcuts while the Director surface is active"""

    bl_idname = "mixar.director_block_input"
    bl_label = "Director Shortcut Guard"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        if not (state and state.is_directing):
            return False
        # Scoped to a 3D viewport's WINDOW region BY THE POLL, not only by
        # the keymaps it sits in. The walk keys are guarded from the global
        # "User Interface" keymap — the one place that beats the eyedropper's
        # global E — and a guard reachable from every editor would eat W, A,
        # S and D anywhere in the app for as long as a session is directing.
        # Everything else parks in 3D-viewport keymaps already, so this only
        # ever narrows what was already true for them.
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        return bool(
            area is not None
            and area.type == 'VIEW_3D'
            and region is not None
            and region.type == 'WINDOW'
        )

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
        _label, ratio_w, ratio_h = ASPECT_PRESETS[self.preset]
        # The ratio belongs to THIS camera. Blender has one render size and it
        # is the scene's, so the choice is remembered on the camera and mirrored
        # into the scene while that camera is live — otherwise picking 2.39:1
        # for the hero shot silently reshaped the 9:16 cutdown beside it.
        remember_camera_ratio(shot.camera, ratio_w, ratio_h)
        # Applied over the scene's CURRENT short side: the aspect is the shape
        # of the frame and the resolution segment is its quality, and writing a
        # pixel size made the two fight.
        apply_ratio(context.scene, ratio_w, ratio_h)
        if shot.beats:
            refresh_manifest(context.scene, shot)
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_navigate,
    MIXAR_OT_director_precise,
    MIXAR_OT_director_explore,
    MIXAR_OT_director_return_to_shot,
    MIXAR_OT_director_block_input,
    MIXAR_OT_director_set_lens,
    MIXAR_OT_director_set_aspect,
)
