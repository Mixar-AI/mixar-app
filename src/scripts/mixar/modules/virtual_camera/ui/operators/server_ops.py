# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual Camera server lifecycle operators.

The server/runtime singletons own all state; these operators only start,
stop, re-pair and copy the link — mirroring the Director rule that behavior
has exactly one owner. They are what the Cinema surface's phone hand-off
button and pairing card invoke, so their ``bl_idname``s are a contract with
``view3d_director_cinema_phone.cc``.

Every one of them refreshes the WindowManager mirror before returning: the
surface must change on the click that caused it, not a pump tick later.
Auto-registered via the ``classes`` tuple.
"""

from __future__ import annotations

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.virtual_camera.core import wm_mirror
from mixar.modules.virtual_camera.core.pairing import generate_token
from mixar.modules.virtual_camera.core.runtime import get_runtime

logger = get_logger(__name__)


def _start(operator, runtime) -> bool:
    if not runtime.start():
        operator.report(
            {'ERROR'},
            runtime.server.state.last_error or "Virtual Camera server failed to start",
        )
        wm_mirror.sync(runtime)
        return False
    wm_mirror.sync(runtime)
    logger.info(
        "virtual_camera: server on port %d (tls=%s)",
        runtime.server.state.port, runtime.server.state.tls,
    )
    return True


class MIXAR_OT_virtual_camera_start(Operator):
    bl_idname = "mixar.virtual_camera_start"
    bl_label = "Start Virtual Camera"
    bl_description = (
        "Start the phone pairing server and show the QR code "
        "(phone and computer must share a Wi-Fi network)"
    )

    def execute(self, context):
        return {'FINISHED'} if _start(self, get_runtime()) else {'CANCELLED'}


class MIXAR_OT_virtual_camera_stop(Operator):
    bl_idname = "mixar.virtual_camera_stop"
    bl_label = "Stop Virtual Camera"
    bl_description = "Disconnect the phone and stop the pairing server"

    def execute(self, context):
        get_runtime().stop()
        return {'FINISHED'}


class MIXAR_OT_virtual_camera_toggle(Operator):
    """The Cinema top strip's phone hand-off button.

    One button for the whole feature: it starts pairing when the server is
    down and hands the camera back when it is up (paired or not). The strip
    paints the three states and says which one the click means, so the
    button never silently does the opposite of what it reads.
    """

    bl_idname = "mixar.virtual_camera_toggle"
    bl_label = "Drive Camera From Your Phone"
    bl_description = (
        "Pair a phone to drive this camera over Wi-Fi, or hand control back "
        "if a session is already running"
    )

    def execute(self, context):
        runtime = get_runtime()
        if runtime.running:
            runtime.stop()
            return {'FINISHED'}
        return {'FINISHED'} if _start(self, runtime) else {'CANCELLED'}


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
        wm_mirror.sync(runtime)
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
    MIXAR_OT_virtual_camera_toggle,
    MIXAR_OT_virtual_camera_new_pairing,
    MIXAR_OT_virtual_camera_copy_url,
)
