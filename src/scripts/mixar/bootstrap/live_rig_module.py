# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""live_rig bootstrap — WindowManager props + pump unregister on shutdown."""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register():
    try:
        from mixar.modules.live_rig.core import pump
        from mixar.modules.live_rig.ui.properties import live_rig_props

        live_rig_props.register()
        pump.register()
        logger.debug("live_rig bootstrap: registered")
    except Exception as e:  # noqa: BLE001 - never break startup
        logger.error("live_rig bootstrap: FAILED - %s", e, exc_info=True)


def unregister():
    try:
        from mixar.modules.live_rig.core import pump
        from mixar.modules.live_rig.core.session import stop_session
        from mixar.modules.live_rig.core import sync_client
        from mixar.modules.live_rig.ui.properties import live_rig_props

        pump.unregister()
        stop_session()
        sync_client.disconnect_room()
        live_rig_props.unregister()
    except Exception as e:  # noqa: BLE001 - defensive on shutdown
        logger.error("live_rig bootstrap unregister failed: %s", e)
