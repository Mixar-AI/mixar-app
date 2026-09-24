# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread camera driver: applies phone control to the bound camera.

Only ever called from the ``bpy.app.timers`` pump in :mod:`.runtime` — never
from server threads. The bound camera is held by name so undo/delete can't
leave a dangling reference.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..constants import (
    DEFAULT_LENS_MM,
    MOVE_SPEED_BASE,
    PAN_SPEED_BASE,
    VERTIGO_DEFAULT_DISTANCE,
)
from . import rig_math


def _context_window():
    wm = bpy.context.window_manager
    return wm.windows[0] if wm and wm.windows else None


class CameraDriver:
    def __init__(self) -> None:
        self.camera_name: str | None = None
        self.offset: rig_math.Quat = rig_math.IDENTITY
        self.yaw: float = 0.0
        self.smoothed_q: rig_math.Quat | None = None
        self.recording = False
        self.vertigo_distance: float | None = None
        self._baseline: dict | None = None
        self._last_recorded_frame: int | None = None
        self._needs_recenter = True  # first packet after (re)bind recenters

    # ---- binding ------------------------------------------------------------

    def camera(self):
        if not self.camera_name:
            return None
        obj = bpy.data.objects.get(self.camera_name)
        if obj is None or obj.type != 'CAMERA':
            return None
        return obj

    def ensure_camera(self):
        """Bind to the scene camera (or first camera object) if unbound."""
        cam = self.camera()
        if cam is not None:
            return cam
        scene = bpy.context.scene
        cam = scene.camera if scene else None
        if cam is None or cam.type != 'CAMERA':
            cam = next((o for o in bpy.data.objects if o.type == 'CAMERA'), None)
        if cam is not None:
            self.bind(cam)
        return cam

    def bind(self, cam) -> None:
        self.camera_name = cam.name
        self.smoothed_q = None
        self.yaw = 0.0
        self._needs_recenter = True
        self.vertigo_distance = None
        self._baseline = {
            "matrix": cam.matrix_world.copy(),
            "lens": cam.data.lens,
            "rotation_mode": cam.rotation_mode,
        }
        scene = bpy.context.scene
        if scene and scene.camera is not cam:
            scene.camera = cam

    def revert(self) -> None:
        cam = self.camera()
        if cam is None or self._baseline is None:
            return
        cam.matrix_world = self._baseline["matrix"]
        cam.rotation_mode = self._baseline["rotation_mode"]
        cam.data.lens = self._baseline["lens"]
        self.smoothed_q = None
        self.yaw = 0.0
        self._needs_recenter = True
        self.vertigo_distance = None

    # ---- helpers ------------------------------------------------------------

    def _current_quat(self, cam) -> rig_math.Quat:
        q = cam.matrix_world.to_quaternion()
        return (q.w, q.x, q.y, q.z)

    @staticmethod
    def _write_world_transform(cam, location: Vector,
                               quat: rig_math.Quat) -> None:
        """One matrix_world write: parent-safe and rotation-mode-agnostic
        (Blender decomposes into the object's own rotation mode)."""
        scale = cam.matrix_world.to_scale()
        cam.matrix_world = Matrix.LocRotScale(location, Quaternion(quat), scale)

    def recenter(self, phone_q: rig_math.Quat | None) -> None:
        cam = self.camera()
        if cam is None:
            return
        self.yaw = 0.0
        self.smoothed_q = None
        if phone_q is None:
            # Nothing to measure an offset against — a recenter tapped
            # before the phone has streamed an orientation, which is the
            # normal order when the button is the first thing pressed.
            # Clearing the flag here would consume the request AND disarm
            # the automatic recenter that the first packet carrying an
            # orientation is supposed to do, so the phone would fly the
            # camera from whatever offset it happened to hold.
            self._needs_recenter = True
            return
        self.offset = rig_math.recenter_offset(self._current_quat(cam), phone_q)
        self._needs_recenter = False

    # ---- per-tick apply -----------------------------------------------------

    def apply(self, packet, settings: dict, dt: float) -> bool:
        """Apply one control tick. Returns True when the camera changed."""
        cam = self.ensure_camera()
        if cam is None or packet is None:
            return False

        if packet.quat is not None and self._needs_recenter:
            self.recenter(packet.quat)

        changed = False
        current_q = self._current_quat(cam)
        new_q = current_q

        # -- rotation from device motion + yaw pan from the right stick
        if packet.quat is not None:
            self.yaw += -packet.j2[0] * PAN_SPEED_BASE * dt
            yaw_q = rig_math.q_from_axis_angle((0.0, 0.0, 1.0), self.yaw)
            target = rig_math.q_multiply(
                yaw_q, rig_math.apply_offset(self.offset, packet.quat)
            )
            alpha = rig_math.smoothing_alpha(settings.get("smoothing", 0.0), dt)
            base = self.smoothed_q or current_q
            new_q = rig_math.q_slerp(base, target, alpha)
            self.smoothed_q = new_q
            changed = True
        elif abs(packet.j2[0]) > 0.0:
            # Joystick-only mode: right-stick x pans the camera in place.
            yaw_q = rig_math.q_from_axis_angle(
                (0.0, 0.0, 1.0), -packet.j2[0] * PAN_SPEED_BASE * dt
            )
            new_q = rig_math.q_multiply(yaw_q, current_q)
            changed = True

        # -- translation from sticks
        speed = MOVE_SPEED_BASE * float(settings.get("move_scale", 1.0))
        velocity, _ = rig_math.joystick_velocity(
            packet.j1, packet.j2, new_q, speed
        )
        location = cam.matrix_world.to_translation()
        if any(abs(c) > 1e-9 for c in velocity):
            location = location + Vector(velocity) * dt
            changed = True

        if changed:
            self._write_world_transform(cam, location, new_q)
        return changed

    # ---- lens / vertigo -----------------------------------------------------

    def set_lens(self, lens: float, *, vertigo: bool) -> None:
        cam = self.camera()
        if cam is None:
            return
        lens0 = cam.data.lens or DEFAULT_LENS_MM
        if vertigo and abs(lens - lens0) > 1e-6:
            if self.vertigo_distance is None:
                dof = cam.data.dof
                self.vertigo_distance = (
                    dof.focus_distance
                    if dof and dof.focus_distance > 1e-3
                    else VERTIGO_DEFAULT_DISTANCE
                )
            d0 = self.vertigo_distance
            d1 = rig_math.vertigo_dolly(d0, lens0, lens)
            quat = cam.matrix_world.to_quaternion()
            fwd = quat @ Vector((0.0, 0.0, -1.0))
            location = cam.matrix_world.to_translation()
            subject = location + fwd * d0
            self._write_world_transform(
                cam, subject - fwd * d1, (quat.w, quat.x, quat.y, quat.z)
            )
            self.vertigo_distance = d1
        cam.data.lens = lens

    def reset_vertigo(self) -> None:
        self.vertigo_distance = None

    # ---- recording ----------------------------------------------------------

    def record_keyframes(self) -> None:
        cam = self.camera()
        scene = bpy.context.scene
        if cam is None or scene is None or not self.recording:
            return
        frame = scene.frame_current
        if frame == self._last_recorded_frame:
            return
        self._last_recorded_frame = frame
        cam.keyframe_insert("location", frame=frame)
        if cam.rotation_mode == 'QUATERNION':
            cam.keyframe_insert("rotation_quaternion", frame=frame)
        elif cam.rotation_mode == 'AXIS_ANGLE':
            cam.keyframe_insert("rotation_axis_angle", frame=frame)
        else:
            cam.keyframe_insert("rotation_euler", frame=frame)
        cam.data.keyframe_insert("lens", frame=frame)

    def set_recording(self, on: bool) -> None:
        self.recording = on
        self._last_recorded_frame = None

    # ---- playback -----------------------------------------------------------

    def is_playing(self) -> bool:
        screen = bpy.context.screen
        return bool(screen and screen.is_animation_playing)

    def play_toggle(self) -> None:
        window = _context_window()
        if window is None:
            return
        with bpy.context.temp_override(window=window, screen=window.screen):
            bpy.ops.screen.animation_play()

    def stop_playback(self) -> None:
        window = _context_window()
        scene = bpy.context.scene
        if window is None or scene is None:
            return
        with bpy.context.temp_override(window=window, screen=window.screen):
            if self.is_playing():
                bpy.ops.screen.animation_play()
        scene.frame_set(scene.frame_start)

    # ---- camera management --------------------------------------------------

    def select_camera(self, name: str) -> None:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type == 'CAMERA':
            self.bind(obj)

    def new_camera(self) -> None:
        scene = bpy.context.scene
        if scene is None:
            return
        active = self.camera()
        data = bpy.data.cameras.new("Virtual Camera")
        obj = bpy.data.objects.new("Virtual Camera", data)
        scene.collection.objects.link(obj)
        if active is not None:
            obj.matrix_world = active.matrix_world.copy()
            data.lens = active.data.lens
        self.bind(obj)

    @staticmethod
    def camera_names() -> list[str]:
        return sorted(o.name for o in bpy.data.objects if o.type == 'CAMERA')
