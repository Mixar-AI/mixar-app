# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager props for the Live Rig panel (transient, not scene data)."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from mixar.modules.live_rig.constants import DEFAULT_CAMERA_INDEX, WM_PROPS


class MixarLiveRigSettings(PropertyGroup):
    camera_index: IntProperty(
        name="Camera",
        description="Webcam device index",
        default=DEFAULT_CAMERA_INDEX,
        min=0,
        max=8,
    )
    room_id: StringProperty(
        name="Room ID",
        description="Shared room for multi-instance pose sync",
        default="",
        maxlen=64,
    )
    publish: BoolProperty(
        name="Publish Pose",
        description="Broadcast this instance's pose to the room",
        default=False,
    )
    status: StringProperty(
        name="Status",
        description="Last pump status / error",
        default="",
        maxlen=256,
    )


classes = (MixarLiveRigSettings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.mixar_live_rig = PointerProperty(type=MixarLiveRigSettings)


def unregister():
    if hasattr(bpy.types.WindowManager, WM_PROPS):
        del bpy.types.WindowManager.mixar_live_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
