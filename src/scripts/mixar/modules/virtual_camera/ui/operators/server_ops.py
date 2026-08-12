# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual Camera server lifecycle operators.

The server/runtime singletons own all state; these operators only start,
stop, and re-pair — mirroring the Director rule that behavior has exactly
one owner. Auto-registered via the ``classes`` tuple.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.virtual_camera.core import qr_icon
from mixar.modules.virtual_camera.core.pairing import generate_token
from mixar.modules.virtual_camera.core.runtime import get_runtime

logger = get_logger(__name__)


class MIXAR_OT_virtual_camera_start(Operator):
    bl_idname = "mixar.virtual_camera_start"
    bl_label = "Start Virtual Camera"
    bl_description = (
        "Start the phone pairing server and show the QR code "
        "(phone and computer must share a Wi-Fi network)"
    )

    def execute(self, context):
        runtime = get_runtime()
        if not runtime.start():
            self.report(
                {'ERROR'},
                runtime.server.state.last_error or "Virtual Camera server failed to start",
            )
            return {'CANCELLED'}
        # Warm the QR icon so the first panel draw hits the cache.
        qr_icon.get_qr_icon_id(runtime.server.state.url)
        logger.info(
            "virtual_camera: server on port %d (tls=%s)",
            runtime.server.state.port, runtime.server.state.tls,
        )
        return {'FINISHED'}


class MIXAR_OT_virtual_camera_stop(Operator):
    bl_idname = "mixar.virtual_camera_stop"
    bl_label = "Stop Virtual Camera"
    bl_description = "Disconnect the phone and stop the pairing server"

    def execute(self, context):
        get_runtime().stop()
        return {'FINISHED'}


class MIXAR_OT_virtual_camera_new_pairing(Operator):
    bl_idname = "mixar.virtual_camera_new_pairing"
    bl_label = "New Pairing Code"
    bl_description = (
        "Invalidate the current pairing: disconnect the phone and issue a "
        "fresh QR code"
    )

    @classmethod
    def poll(cls, context):
        return get_runtime().running

    def execute(self, context):
        runtime = get_runtime()
        server = runtime.server
        server.drop_connection(reason="re-pairing")
        server.state.token = generate_token()
        qr_icon.get_qr_icon_id(server.state.url)
        return {'FINISHED'}


class MIXAR_OT_virtual_camera_copy_url(Operator):
    bl_idname = "mixar.virtual_camera_copy_url"
    bl_label = "Copy Pairing Link"
    bl_description = (
        "Copy the pairing link to the clipboard (open it in the phone's "
        "browser if the QR code can't be scanned)"
    )

    @classmethod
    def poll(cls, context):
        return get_runtime().running

    def execute(self, context):
        context.window_manager.clipboard = get_runtime().server.state.url
        self.report({'INFO'}, "Pairing link copied")
        return {'FINISHED'}


classes = (
    MIXAR_OT_virtual_camera_start,
    MIXAR_OT_virtual_camera_stop,
    MIXAR_OT_virtual_camera_new_pairing,
    MIXAR_OT_virtual_camera_copy_url,
)
