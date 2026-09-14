# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply a bone pose onto a Blender armature (main-thread only)."""

from __future__ import annotations

from typing import Optional

from mixar.config.logging_config import get_logger

from .retarget import BonePose

logger = get_logger(__name__)


def resolve_armature(context) -> Optional[object]:
    """Prefer the active armature, else the first selected armature."""
    obj = getattr(context, "active_object", None)
    if obj is not None and getattr(obj, "type", None) == "ARMATURE":
        return obj
    selected = getattr(context, "selected_objects", None) or ()
    for candidate in selected:
        if getattr(candidate, "type", None) == "ARMATURE":
            return candidate
    return None


def apply_bone_pose(armature, pose: BonePose) -> int:
    """Write pose-bone local rotations. Returns how many bones were updated.

    Bones missing from the armature are skipped. Must run on Blender's
    main thread (the live-rig pump already does).
    """
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return 0
    pose_data = getattr(armature, "pose", None)
    if pose_data is None:
        return 0

    updated = 0
    bones = pose_data.bones
    for name, quat in pose.bones.items():
        bone = bones.get(name)
        if bone is None:
            continue
        try:
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = quat
            updated += 1
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.debug("live_rig: skip bone %s: %s", name, exc)
    return updated
