# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread timer pump: capture → estimate → retarget → apply → publish."""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.live_rig.constants import PUMP_INTERVAL_S

from .apply import apply_bone_pose, resolve_armature
from .capture import get_capture
from .pose_estimate import estimate_pose
from .retarget import landmarks_to_bone_pose
from .session import get_session
from . import sync_client

logger = get_logger(__name__)


def _pump() -> float | None:
    session = get_session()
    if not session.active:
        return None

    try:
        capture = get_capture()
        if capture is None:
            session.last_error = "Camera is not open"
            return PUMP_INTERVAL_S

        frame = capture.read()
        if frame is None:
            return PUMP_INTERVAL_S

        landmarks = estimate_pose(frame)
        pose = landmarks_to_bone_pose(landmarks)
        session.last_pose = pose
        session.frames += 1

        context = bpy.context
        armature = None
        if session.armature_name:
            armature = bpy.data.objects.get(session.armature_name)
        if armature is None:
            armature = resolve_armature(context)
            if armature is not None:
                session.armature_name = armature.name

        # Prefer remote poses when subscribed; otherwise drive from local cam.
        remote = sync_client.drain_remote_poses(exclude_instance=session.instance_id)
        if remote:
            pose = remote[-1]
            session.last_pose = pose

        session.applied_bones = apply_bone_pose(armature, pose)

        if session.publish and session.room_id:
            sync_client.publish_pose(pose, session.instance_id)

        session.last_error = ""
    except Exception as exc:  # noqa: BLE001 — keep the timer alive
        session.last_error = str(exc)
        logger.warning("live_rig pump: %s", exc)

    return PUMP_INTERVAL_S


def ensure_pump() -> None:
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=PUMP_INTERVAL_S)


def stop_pump() -> None:
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)


def register() -> None:
    return None


def unregister() -> None:
    stop_pump()
