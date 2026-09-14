# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for starting/stopping live webcam rig drive and room sync."""

from __future__ import annotations

import uuid

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.live_rig.core import sync_client
from mixar.modules.live_rig.core.apply import resolve_armature
from mixar.modules.live_rig.core.pump import ensure_pump, stop_pump
from mixar.modules.live_rig.core.session import get_session, start_session, stop_session

logger = get_logger(__name__)


def _settings(context):
    return getattr(context.window_manager, "mixar_live_rig", None)


class MIXAR_OT_live_rig_start(Operator):
    bl_idname = "mixar.live_rig_start"
    bl_label = "Start Live Rig"
    bl_description = "Drive the active armature from the laptop webcam"
    bl_options = {'REGISTER'}

    def execute(self, context):
        armature = resolve_armature(context)
        if armature is None:
            self.report({'WARNING'}, "Select an armature to drive")
            return {'CANCELLED'}

        settings = _settings(context)
        camera_index = int(getattr(settings, "camera_index", 0) or 0)
        room_id = (getattr(settings, "room_id", "") or "").strip()
        publish = bool(getattr(settings, "publish", False))
        instance_id = str(uuid.uuid4())

        if room_id:
            try:
                sync_client.join_room(room_id)
                instance_id = sync_client.connect_room(room_id, instance_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("live_rig: room join failed: %s", exc)
                if settings is not None:
                    settings.status = f"Room error: {exc}"
                self.report({'WARNING'}, f"Could not join room: {exc}")
                # Local drive still starts without sync.

        start_session(
            camera_index=camera_index,
            armature_name=armature.name,
            room_id=room_id,
            instance_id=instance_id,
            publish=publish,
        )
        ensure_pump()
        if settings is not None:
            settings.status = f"Driving {armature.name}"
        self.report({'INFO'}, f"Live rig started on {armature.name}")
        return {'FINISHED'}


class MIXAR_OT_live_rig_stop(Operator):
    bl_idname = "mixar.live_rig_stop"
    bl_label = "Stop Live Rig"
    bl_description = "Stop webcam drive and disconnect from the room"
    bl_options = {'REGISTER'}

    def execute(self, context):
        stop_pump()
        stop_session()
        sync_client.disconnect_room()
        settings = _settings(context)
        if settings is not None:
            settings.status = "Stopped"
        self.report({'INFO'}, "Live rig stopped")
        return {'FINISHED'}


class MIXAR_OT_live_rig_create_room(Operator):
    bl_idname = "mixar.live_rig_create_room"
    bl_label = "Create Sync Room"
    bl_description = "Create a backend room and store its ID for multi-instance sync"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = _settings(context)
        try:
            payload = sync_client.create_room(label="Live Rig")
        except Exception as exc:  # noqa: BLE001
            self.report({'ERROR'}, f"Create room failed: {exc}")
            if settings is not None:
                settings.status = str(exc)
            return {'CANCELLED'}
        room_id = str(payload.get("room_id") or "")
        if not room_id:
            self.report({'ERROR'}, "Create room returned no room_id")
            return {'CANCELLED'}
        if settings is not None:
            settings.room_id = room_id
            settings.status = f"Room {room_id}"
        self.report({'INFO'}, f"Room created: {room_id}")
        return {'FINISHED'}


classes = (
    MIXAR_OT_live_rig_start,
    MIXAR_OT_live_rig_stop,
    MIXAR_OT_live_rig_create_room,
)
