# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Map actor landmarks onto Mixamo / Tripo-style armature bones.

The offline auto-rig path already stamps meshes with a ``spec`` of
``mixamo`` or ``tripo``. Live drive targets the same bone name conventions
so a freshly auto-rigged asset can be driven without a second retarget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .pose_estimate import PoseLandmarks

# Subset of Mixamo bone names we expect on auto-rigged assets. Extended as
# the landmark set grows; unknown bones are simply skipped at apply time.
MIXAMO_BONE_ORDER = (
    "mixamorig:Hips",
    "mixamorig:Spine",
    "mixamorig:Spine1",
    "mixamorig:Spine2",
    "mixamorig:Neck",
    "mixamorig:Head",
    "mixamorig:LeftShoulder",
    "mixamorig:LeftArm",
    "mixamorig:LeftForeArm",
    "mixamorig:LeftHand",
    "mixamorig:RightShoulder",
    "mixamorig:RightArm",
    "mixamorig:RightForeArm",
    "mixamorig:RightHand",
    "mixamorig:LeftUpLeg",
    "mixamorig:LeftLeg",
    "mixamorig:LeftFoot",
    "mixamorig:RightUpLeg",
    "mixamorig:RightLeg",
    "mixamorig:RightFoot",
)


@dataclass
class BonePose:
    """Per-bone local rotation as a quaternion (w, x, y, z)."""

    bones: Dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    schema_version: int = 1
    timestamp: float = 0.0


_IDENTITY = (1.0, 0.0, 0.0, 0.0)


def landmarks_to_bone_pose(
    landmarks: PoseLandmarks,
    *,
    skeleton: str = "mixamo",
) -> BonePose:
    """Retarget landmarks into a bone pose dictionary.

    Scaffold: identity rotations for every known Mixamo bone so apply and
    sync can be exercised end-to-end. Real IK / look-at math lands here.
    """
    del skeleton  # reserved for tripo vs mixamo name tables
    bones = {name: _IDENTITY for name in MIXAMO_BONE_ORDER}
    if landmarks.points:
        # Future: solve bone quaternions from landmark pairs.
        pass
    return BonePose(
        bones=bones,
        schema_version=1,
        timestamp=landmarks.timestamp,
    )


def bone_pose_to_wire(pose: BonePose) -> dict:
    """Serialize a pose for room fan-out."""
    return {
        "schema_version": pose.schema_version,
        "timestamp": pose.timestamp,
        "bones": {name: list(quat) for name, quat in pose.bones.items()},
    }


def bone_pose_from_wire(payload: dict) -> BonePose:
    """Deserialize a pose from room fan-out."""
    bones_raw = payload.get("bones") or {}
    bones: Dict[str, tuple[float, float, float, float]] = {}
    for name, quat in bones_raw.items():
        if not isinstance(quat, (list, tuple)) or len(quat) != 4:
            continue
        bones[str(name)] = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    return BonePose(
        bones=bones,
        schema_version=int(payload.get("schema_version") or 1),
        timestamp=float(payload.get("timestamp") or 0.0),
    )
