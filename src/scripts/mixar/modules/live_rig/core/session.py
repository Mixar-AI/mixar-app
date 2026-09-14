# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session state for local webcam drive and optional room publishing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .capture import close_capture, open_capture
from .retarget import BonePose


@dataclass
class LiveRigSession:
    """Mutable session held by the pump (not persisted into .blend)."""

    active: bool = False
    camera_index: int = 0
    armature_name: str = ""
    room_id: str = ""
    instance_id: str = ""
    publish: bool = False
    last_pose: Optional[BonePose] = None
    last_error: str = ""
    frames: int = 0
    applied_bones: int = 0
    extras: dict = field(default_factory=dict)


_session = LiveRigSession()


def get_session() -> LiveRigSession:
    return _session


def start_session(
    *,
    camera_index: int = 0,
    armature_name: str = "",
    room_id: str = "",
    instance_id: str = "",
    publish: bool = False,
) -> LiveRigSession:
    open_capture(camera_index)
    _session.active = True
    _session.camera_index = camera_index
    _session.armature_name = armature_name
    _session.room_id = room_id.strip()
    _session.instance_id = instance_id.strip()
    _session.publish = bool(publish and _session.room_id)
    _session.last_error = ""
    _session.frames = 0
    _session.applied_bones = 0
    return _session


def stop_session() -> None:
    _session.active = False
    _session.publish = False
    close_capture()
