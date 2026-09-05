# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start the Mixar ↔ Unreal connector sidecar after Mixar finishes booting."""

from mixar.config.logging_config import get_logger
from mixar.modules.connector.core.constants import DEFAULT_SIDECAR_PORT
from mixar.modules.connector.core.sidecar import start_sidecar, stop_sidecar

logger = get_logger(__name__)
_timer_registered = False


def _start() -> None:
    try:
        start_sidecar(DEFAULT_SIDECAR_PORT)
    except OSError as exc:
        logger.warning("Connector sidecar already bound or failed: %s", exc)
    return None


def register() -> None:
    global _timer_registered
    import bpy

    if _timer_registered:
        return
    bpy.app.timers.register(_start, first_interval=2.0)
    _timer_registered = True
    logger.debug("Scheduled Mixar connector sidecar")


def unregister() -> None:
    global _timer_registered
    stop_sidecar()
    _timer_registered = False
