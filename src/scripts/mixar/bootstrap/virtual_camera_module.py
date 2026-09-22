# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Virtual Camera — bootstrap.

Lifecycle owner for the phone-as-camera feature (modules/virtual_camera):
a LAN HTTPS/WebSocket server pairs a phone browser via QR code; the phone's
gyro + joysticks drive the bound camera through a main-thread timer pump.

The server is user-started from Cinema Mode's phone hand-off button,
never on launch. This module
only wires teardown:

  * ``load_pre`` — a new .blend invalidates the bound camera, any recording
    in flight, and every capture resource, so the whole runtime shuts down
    (the phone app shows "connection lost"; the user restarts pairing).
  * ``unregister`` — full shutdown + a blanked WindowManager mirror.

UI classes (operators/panels) are auto-registered by the UI loader from
``modules/virtual_camera/ui``.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


@persistent
def _virtual_camera_on_load_pre(*_args) -> None:
    try:
        from mixar.modules.virtual_camera.core import runtime

        runtime.shutdown()
    except Exception as exc:
        logger.debug("virtual_camera: load_pre shutdown skipped: %s", exc)


def register() -> None:
    logger.info("virtual_camera: register()")
    if _virtual_camera_on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_virtual_camera_on_load_pre)


def unregister() -> None:
    logger.info("virtual_camera: unregister()")
    if _virtual_camera_on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_virtual_camera_on_load_pre)
    try:
        from mixar.modules.virtual_camera.core import runtime, wm_mirror

        runtime.shutdown(remove_handler=True)
        wm_mirror.clear()
    except Exception as exc:
        logger.debug("virtual_camera: unregister cleanup skipped: %s", exc)
